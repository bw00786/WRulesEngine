import logging
import json
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, File, UploadFile  # Add UploadFile here
from fastapi.middleware.cors import CORSMiddleware  # Import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from openai import AsyncOpenAI
from fastapi_limiter.depends import RateLimiter
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, JSON, select
from sqlalchemy.ext.declarative import declarative_base
import asyncio
import uvicorn
from concurrent.futures import ThreadPoolExecutor
import aioredis
import prometheus_client
from pydantic import BaseModel, Field
from prometheus_client import Counter, Histogram
from starlette.middleware.base import BaseHTTPMiddleware
from contextlib import asynccontextmanager
import io
import pandas as pd  # For Excel/CSV handling

# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Define the Base for SQLAlchemy models
Base = declarative_base()

# Database Models
class RuleModel(Base):
    __tablename__ = "rules3"
    Id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    conditions = Column(JSON)
    actions = Column(JSON)
    description = Column(String, nullable=True)
    context = Column(String, nullable=True)
    llm_config = Column(JSON, nullable=True)

# Pydantic Models
class LLMConfig(BaseModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model: str = Field(default="gpt-4-turbo-preview")
    max_tokens: int = Field(default=500)

class Rule(BaseModel):
    name: str
    conditions: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]

class EnhancedRule(Rule):
    description: Optional[str] = None
    context: Optional[str] = None
    llm_config: Optional[LLMConfig] = Field(default_factory=LLMConfig)

class RuleValidationResult(BaseModel):
    is_valid: bool
    feedback: str
    suggested_improvements: Optional[List[str]] = None

class Fact(BaseModel):
    facts: Dict[str, Any]

# Global variables
client = AsyncOpenAI(api_key="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")
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP Requests", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["endpoint"])

# Database configuration
DATABASE_URL = "postgresql+asyncpg://user:password@localhost:5432/rules_db"
engine = create_async_engine(DATABASE_URL, echo=False)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis = await aioredis.from_url(
        "redis://localhost:6379",
        encoding="utf8",
        decode_responses=True
    )
    
    await FastAPILimiter.init(redis)
    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    yield
    
    # Shutdown
    await redis.close()
    await engine.dispose()

# Initialize FastAPI app with lifespan
app = FastAPI(lifespan=lifespan)

# CORS Configuration
origins = [
    "http://localhost",  # Allow requests from localhost
    "http://localhost:8000",  # Example: Allow requests from another port
    "http://yourdomain.com",  # Example: Allow requests from your frontend domain
    "https://yourdomain.com", # Example: Allow requests from your frontend domain with https
    "*",  # WARNING: Use with caution in production! Allows all origins.
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,  # Allow sending cookies, authorization headers, etc.
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, PUT, DELETE, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Middleware
class MetricsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        method = request.method
        endpoint = request.url.path
        REQUEST_COUNT.labels(method=method, endpoint=endpoint).inc()
        with REQUEST_LATENCY.labels(endpoint=endpoint).time():
            response = await call_next(request)
        return response

app.add_middleware(MetricsMiddleware)

# Database dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Helper functions
async def validate_rule_with_llm(rule: EnhancedRule) -> RuleValidationResult:
    """Validate a rule using LLM to check for logical consistency and improvements"""
    conditions_json = json.dumps(rule.conditions, indent=2)
    actions_json = json.dumps(rule.actions, indent=2)
    prompt = f"""
    Please analyze this business rule for logical consistency and potential improvements:
    
    Rule Name: {rule.name}
    Description: {rule.description or 'No description provided'}
    Context: {rule.context or 'No context provided'}
    
    Conditions: {json.dumps(rule.conditions, indent=2)}
    Actions: {json.dumps(rule.actions, indent=2)}
    
    Please analyze the following aspects:
    1. Logical consistency between conditions and actions
    2. Potential conflicts with common business rules
    3. Completeness of the rule
    4. Potential edge cases
    5. Suggested improvements
    
    Provide your response in JSON format with the following structure:
    {
        "is_valid": boolean,
        "feedback": "detailed analysis",
        "suggested_improvements": ["improvement1", "improvement2", ...]
    }
    """ .format(
        rule_name=rule.name,
        description=rule.description or 'No description provided',
        context=rule.context or 'No context provided',
        conditions=conditions_json,
        actions=actions_json
    )

    try:
        response = await client.chat.completions.create(
            model=rule.llm_config.model,
            temperature=rule.llm_config.temperature,
            messages=[
                {"role": "system", "content": "You are a business rules analysis expert."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=rule.llm_config.max_tokens,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        logger.info("LLM raw response: %s", response.choices[0].message.content)

        return RuleValidationResult(**result)
    except Exception as e:
        logger.error(f"LLM validation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="LLM validation failed")

async def evaluate_with_llm(facts: Dict[str, Any], rule: RuleModel) -> Dict[str, Any]:
    """Evaluate facts against a rule using LLM"""
    prompt = f"""
    Given these facts: {json.dumps(facts, indent=2)}
    
    And this rule:
    Conditions: {json.dumps(rule.conditions, indent=2)}
    Actions: {json.dumps(rule.actions, indent=2)}
    
    Please evaluate if the conditions are met and determine the appropriate actions.
    Consider edge cases and implicit relationships.
    
    Provide your response in JSON format with the following structure:
    {
        "conditions_met": boolean,
        "reasoning": "explanation of the evaluation",
        "actions_to_take": [actions] or null,
        "confidence_score": float between 0 and 1
    }
    """

    try:
        response = await client.chat.completions.create(
            model="gpt-4-turbo-preview",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a precise rule evaluation engine."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result
    except Exception as e:
        logger.error(f"LLM evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="LLM evaluation failed")
    
async def extract_conditions_from_text(text: str, client: AsyncOpenAI) -> List[dict]:
    """Convert natural language rule text into structured JSON conditions"""
    prompt = f"""
    Convert this business rule text into JSON conditions:
    {text}
    
    Format each condition with:
    - field: what is being checked
    - operator: ==, !=, >, <, >=, <=, in, not_in, contains, starts_with, ends_with
    - value: the comparison value

    For example:
    "If customer age is greater than 25 and total purchase is at least 100"
    Should become:
    [
        {{"field": "customer_age", "operator": ">", "value": 25}},
        {{"field": "total_purchase", "operator": ">=", "value": 100}}
    ]
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4-turbo-preview",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a rule parser that outputs only valid JSON arrays of conditions."},
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract JSON array from the response
        response_text = response.choices[0].message.content
        # Find the first [ and last ] to extract just the JSON array
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']') + 1
        
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON array found in response")
            
        json_str = response_text[start_idx:end_idx]
        conditions = json.loads(json_str)
        
        # Ensure we always return a list
        if isinstance(conditions, dict):
            conditions = [conditions]
        
        return conditions
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}\nResponse: {response_text}")
        raise ValueError(f"Could not parse LLM response into valid JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to parse rule text: {str(e)}")
        raise ValueError(f"Could not parse rule text: {str(e)}")

async def extract_actions_from_text(text: str, client: AsyncOpenAI) -> List[dict]:
    """Convert natural language action text into structured JSON actions"""
    prompt = f"""
    Convert this business rule action text into JSON actions:
    {text}
    
    Format each action with:
    - type: notify, update, create, or delete
    - target: what the action affects
    - parameters: additional parameters object

    For example:
    "Send email to customer and update their status to premium"
    Should become:
    [
        {{"type": "notify", "target": "customer", "parameters": {{"method": "email"}}}},
        {{"type": "update", "target": "customer_status", "parameters": {{"value": "premium"}}}}
    ]
    """
    
    try:
        response = await client.chat.completions.create(
            model="gpt-4-turbo-preview",
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a rule parser that outputs only valid JSON arrays of actions."},
                {"role": "user", "content": prompt}
            ]
        )
        
        # Extract JSON array from the response
        response_text = response.choices[0].message.content
        # Find the first [ and last ] to extract just the JSON array
        start_idx = response_text.find('[')
        end_idx = response_text.rfind(']') + 1
        
        if start_idx == -1 or end_idx == 0:
            raise ValueError("No JSON array found in response")
            
        json_str = response_text[start_idx:end_idx]
        actions = json.loads(json_str)
        
        # Ensure we always return a list
        if isinstance(actions, dict):
            actions = [actions]
        
        return actions
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}\nResponse: {response_text}")
        raise ValueError(f"Could not parse LLM response into valid JSON: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to parse action text: {str(e)}")
        raise ValueError(f"Could not parse action text: {str(e)}")

async def process_excel_rules(file: UploadFile, db: AsyncSession, client: AsyncOpenAI):
    """Process rules from Excel file containing natural language rules"""
    try:
        logger.info("Processing natural language rules from Excel file")
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Validate required columns
        required_columns = ['Id']
        missing_columns = [col for col in required_columns if col not in df.columns]
        if missing_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Excel file missing required columns: {', '.join(missing_columns)}"
            )
        
        rules_added = []
        errors = []
        
        for index, row in df.iterrows():
            try:

                # Extract id with fallback options
                rule_id = str(
                    row.get('Id', '') or 
                    row.get('id', '') or 
                   ''
                ).strip() or None

                # Extract rule name with fallback options
                rule_name = str(
                    row.get('Rule Name', '') or 
                    row.get('Name', '') or 
                    f"Rule_{index + 1}"
                ).strip()
                
                # Get description if available
                rule_description = str(
                    row.get('Description', '') or 
                    row.get('Desc', '') or 
                    ''
                ).strip() or None
                
                # Process rule text
                rule_text = str(row['Conditions']).strip()
                if rule_text.lower() == 'nan' or not rule_text:
                    raise ValueError("Empty rule text")
                
                logger.info(f"Processing rule text: {rule_text}")
                rule_conditions = await extract_conditions_from_text(rule_text, client)
                logger.info(f"DEBUG: Rule Extracted: {json.dumps(rule_conditions, indent=2)}")
                
                # Process actions if present
                rule_actions = []
                if 'Actions' in df.columns:
                    actions_text = str(row['Actions']).strip()
                    if actions_text and actions_text.lower() != 'nan':
                        logger.info(f"Processing actions text: {actions_text}")
                        rule_actions = await extract_actions_from_text(actions_text, client)
                        logger.info(f"DEBUG: Actions Extracted: {json.dumps(rule_actions, indent=2)}")
                
                # Debug logging
                logger.info(f"Processed rule {rule_name}:")
                logger.info("Processed rule %s: Conditions: %s Actions: %s", rule_name, json.dumps(rule_conditions), json.dumps(rule_actions))

                logger.info(f"Conditions: {json.dumps(rule_conditions)}")
                logger.info(f"Actions: {json.dumps(rule_actions)}")
                
                # Create EnhancedRule object with safe defaults
                enhanced_rule = EnhancedRule(
                    id = rule_id,
                    name=rule_name,
                    conditions=rule_conditions,
                    actions=rule_actions,
                    description=rule_description,
                    context=str(row.get('Context', '')).strip() or None,
                    llm_config=LLMConfig()  # Use default config
                )
                
                # Validate rule with LLM
                validation_result = await validate_rule_with_llm(enhanced_rule)
                
                if not validation_result.is_valid:
                    errors.append({
                        "row": index + 1,
                        "rule_name": rule_name,
                        "error": "Validation failed",
                        "feedback": validation_result.feedback,
                        "improvements": validation_result.suggested_improvements
                    })
                    continue
                
                # Create database rule with explicit type conversion
                db_rule = RuleModel(
                    id=str(enhanced_rule.id),
                    name=str(enhanced_rule.name),
                    conditions=[dict(cond) for cond in enhanced_rule.conditions],
                    actions=[dict(action) for action in enhanced_rule.actions],
                    description=enhanced_rule.description,
                    context=enhanced_rule.context,
                    llm_config=enhanced_rule.llm_config.dict() if enhanced_rule.llm_config else None
                )
                logger.info("Adding rules to the database")
                db.add(db_rule)
                await db.commit()
                await db.refresh(db_rule)
                
                rules_added.append({
                    "name": rule_name,
                    "original_text": rule_text,
                    "parsed_conditions": rule_conditions,
                    "parsed_actions": rule_actions
                })
                
            except Exception as e:
                logger.error(f"Error processing rule {rule_name if 'rule_name' in locals() else f'Row_{index + 1}'}: {str(e)}")
                await db.rollback()
                errors.append({
                    "row": index + 1,
                    "rule_name": rule_name if 'rule_name' in locals() else f"Row_{index + 1}",
                    "error": str(e)
                })
                continue
        
        # Return detailed response
        response = {
            "success": {
                "count": len(rules_added),
                "rules": rules_added
            }
        }
        
        if errors:
            response["errors"] = errors
        
        return response
        
    except pd.errors.EmptyDataError:
        raise HTTPException(status_code=400, detail="The Excel file is empty")
    except pd.errors.ParserError as e:
        raise HTTPException(status_code=400, detail=f"Error parsing Excel file: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error processing Excel file: {str(e)}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred: {str(e)}")


# Endpoints (modified)
@app.post("/rules/upload/", response_model=Dict[str, Any])
async def upload_rules(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    """Upload rules from an Excel file with natural language text."""
    try:
        return await process_excel_rules(file, db, client)
    except HTTPException as e:
        raise
    except Exception as e:
        logger.error(f"Error during file upload: {e}")
        raise HTTPException(status_code=500, detail=f"An unexpected error occurred during file upload: {str(e)}")

# Endpoints
@app.post("/rules/validate/")
async def validate_rule(rule: EnhancedRule):
    """Validate a rule using LLM before adding it"""
    validation_result = await validate_rule_with_llm(rule)
    return validation_result

@app.post("/rules/", response_model=Dict[str, str])
async def add_rule(
    rule: EnhancedRule,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    _: None = Depends(RateLimiter(times=5, seconds=60))
):
    """Add a new rule with optional LLM validation"""
    validation_result = await validate_rule_with_llm(rule)
    
    if not validation_result.is_valid:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Rule validation failed",
                "feedback": validation_result.feedback,
                "improvements": validation_result.suggested_improvements
            }
        )
    
    try:
        db_rule = RuleModel(
            name=rule.name,
            conditions=rule.conditions,
            actions=rule.actions,
            description=rule.description,
            context=rule.context,
            llm_config=rule.llm_config.dict() if rule.llm_config else None
        )
        
        db.add(db_rule)
        await db.commit()
        await db.refresh(db_rule)
        
        background_tasks.add_task(FastAPICache.clear)
        
        return {"message": "Rule added successfully"}
    except Exception as e:
        await db.rollback()
        logger.error(f"Failed to add rule: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to add rule")

@app.get("/rules/", response_model=List[Rule])
@cache(expire=60)
async def get_rules(db: AsyncSession = Depends(get_db)):
    """Retrieve all rules"""
    try:
        result = await db.execute(select(RuleModel))
        return result.scalars().all()
    except Exception as e:
        logger.error(f"Failed to fetch rules: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch rules")

@app.post("/evaluate/", response_model=Dict[str, Any])
async def evaluate(
    fact: Fact,
    db: AsyncSession = Depends(get_db),
    use_llm: bool = False,
    _: None = Depends(RateLimiter(times=5, seconds=60))
):
    """Evaluate facts against rules with optional LLM-based evaluation"""
    logger.info(f"Evaluating facts: {fact.facts}")
    
    try:
        if use_llm:
            rules = await db.execute(select(RuleModel))
            rules = rules.scalars().all()
            all_results = []
            
            for rule in rules:
                result = await evaluate_with_llm(fact.facts, rule)
                if result["conditions_met"]:
                    all_results.extend(result["actions_to_take"])
            
            if not all_results:
                raise HTTPException(status_code=400, detail="No matching rules found")
            
            return {
                "actions": all_results,
                "evaluation_method": "llm"
            }
        else:
            # Implement traditional forward-chaining inference
            results = []
            rules = await db.execute(select(RuleModel))
            rules = rules.scalars().all()
            
            for rule in rules:
                conditions_met = all(
                    fact.facts.get(cond["field"]) == cond["value"]
                    for cond in rule.conditions
                )
                if conditions_met:
                    results.extend(rule.actions)
            
            if not results:
                raise HTTPException(status_code=400, detail="No matching rules found")
            
            return {
                "actions": results,
                "evaluation_method": "traditional"
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail="Evaluation failed")

@app.get("/metrics")
async def metrics():
    return prometheus_client.generate_latest()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
