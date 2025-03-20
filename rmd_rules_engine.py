import logging
import json
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, JSON, Float, select
from sqlalchemy.ext.declarative import declarative_base
import asyncio
import uvicorn
from contextlib import asynccontextmanager

# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Database configuration (replace with your actual database URL)
DATABASE_URL = "sqlite+aiosqlite:///./test.db"  # Example SQLite database for simplicity
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

Base = declarative_base()

class RuleModel(Base):
    __tablename__ = "rules"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    priority = Column(Integer, default=5)
    conditions = Column(JSON)
    actions = Column(JSON)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

rules_cache: List[Dict[str, Any]] = []  # In-memory cache for loaded rules

async def load_rules_from_db(db: AsyncSession):
    global rules_cache
    rules_cache = []
    rules = (await db.execute(select(RuleModel))).scalars().all()
    for rule in rules:
        rules_cache.append({
            "name": rule.name,
            "priority": rule.priority,
            "conditions": rule.conditions,
            "actions": rule.actions,
            "id": rule.id,
        })
    logger.info(f"Loaded {len(rules_cache)} rules from database.")

async def evaluate_condition(condition: Dict[str, Any], facts: Dict[str, Any], all_rules: List[Dict[str, Any]]):
    if "refRule" in condition:
        rule_name = condition["refRule"]
        referenced_rule = next((rule for rule in all_rules if rule["name"] == rule_name), None)
        if referenced_rule:
            return await evaluate_conditions(referenced_rule["conditions"], facts, all_rules)
        return False

    for field, op_val in condition.items():
        if field == "and":
            return all(await evaluate_conditions(c, facts, all_rules) for c in op_val)
        if field == "or":
            return any(await evaluate_conditions(c, facts, all_rules) for c in op_val)

        op = op_val["operator"]
        val = op_val["value"]
        fact_val = facts.get(field)

        if op == "==":
            return fact_val == val
        elif op == "!=":
            return fact_val != val
        elif op == ">=":
            return fact_val >= val
        elif op == "<=":
            return fact_val <= val
        elif op == ">":
            return fact_val > val
        elif op == "<":
            return fact_val < val
        elif op == "in":
            return fact_val in val
        elif op == "not_in":
            return fact_val not in val

    return True

async def evaluate_conditions(conditions: Dict[str, Any], facts: Dict[str, Any], all_rules: List[Dict[str, Any]]):
    return await evaluate_condition(conditions, facts, all_rules)

async def execute_actions(actions: List[Dict[str, Any]], facts: Dict[str, Any]):
    results = []
    for action in actions:
        if action["type"] == "calculate_rmd":
            results.append({"type": "calculate_rmd", "message": f"Calculating RMD for type {action['parameters'].get('rmd_type')}"})
        elif action["type"] == "calculate_rmd_amount":
            results.append({"type": "calculate_rmd_amount", "message": f"Calculating RMD amount for type {action['parameters'].get('calculation_type')}"})
        else:
            results.append(action)
    return results

@app.post("/upload_rules/")
async def upload_rules(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    try:
        content = await file.read()
        rules_data = json.loads(content)
        for rule_data in rules_data:
            rule = RuleModel(
                name=rule_data["name"],
                priority=rule_data.get("priority", 5),
                conditions=rule_data["conditions"],
                actions=rule_data["actions"],
            )
            db.add(rule)
        await db.commit()
        await load_rules_from_db(db)
        return {"message": "Rules uploaded successfully"}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/evaluate/")
async def evaluate_facts(facts: Dict[str, Any], db: AsyncSession = Depends(get_db)):
    await load_rules_from_db(db)
    results = []
    for rule in rules_cache:
        if await evaluate_conditions(rule["conditions"], facts, rules_cache):
            actions_results = await execute_actions(rule["actions"], facts)
            results.append({
                "rule_name": rule["name"],
                "actions": actions_results,
            })
    return results

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
