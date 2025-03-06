import logging
import json
import os
from enum import Enum, auto
from fastapi import FastAPI, HTTPException, Depends, BackgroundTasks, File, UploadFile  # Add UploadFile here
from fastapi.middleware.cors import CORSMiddleware  # Import CORSMiddleware
from fastapi_limiter import FastAPILimiter
from openai import AsyncOpenAI
from fastapi_limiter.depends import RateLimiter
from fastapi_cache import FastAPICache
from fastapi_cache.backends.redis import RedisBackend
from fastapi_cache.decorator import cache
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Set, Tuple
import itertools
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import Column, Integer, String, JSON, Float, select
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
from sqlalchemy import Boolean
import pandas as pd  # For Excel/CSV handling
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

OPEN_AI_KEY=os.getenv('OPEN_AI_KEY')
POSTGRES_URL = "postgresql+asyncpg://ruly:123@localhost:5432/rulesbd"
REDIS_URL = os.getenv('REDIS_URL')
LLM_MODEL= os.getenv('LLM_MODEL')
RULES_TABLE = os.getenv('RULES_TABLE')
REPORTS_TABLE = os.getenv('REPORTS_TABLE')


# Define the Base for SQLAlchemy models
Base = declarative_base()

# Database Models
class RuleModel(Base):
    __tablename__ = RULES_TABLE
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)
    context = Column(String, nullable=True)
    conditions = Column(JSON, nullable=True)
    actions = Column(JSON, nullable=True)
    description = Column(String, nullable=True)
    priority = Column(Integer, default=0)
    llm_config = Column(JSON, nullable=True)

# Pydantic Models
class LLMConfig(BaseModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    model: str = Field(default=LLM_MODEL)
    max_tokens: int = Field(default=500)

class Rule(BaseModel):
    id: int
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
    context: str  # Domain context (e.g., "employee", "finance", "insurance")
    facts: Dict[str, Any]
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    class Config:
        json_schema_extra = {
            "example": {
                "context": "finance",
                "facts": {
                    "age": 55,
                    "savings": 200000,
                    "contribution": 15000
                },
                "metadata": {
                    "source": "annual_review",
                    "timestamp": "2025-02-14T16:40:58"
                }
            }
        }
# Add these new models while keeping your existing ones
class Operator(str, Enum):
    EQUALS = "=="
    NOT_EQUALS = "!="
    GREATER_THAN = ">"
    LESS_THAN = "<"
    GREATER_EQUAL = ">="
    LESS_EQUAL = "<="
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"
    MATCHES_REGEX = "matches_regex"


class Condition(BaseModel):
    field: str
    operator: Operator
    value: Optional[Any] = None

    def evaluate(self, facts: Dict[str, Any]) -> bool:
        if self.operator in [Operator.EXISTS, Operator.NOT_EXISTS]:
            exists = self.field in facts
            return exists if self.operator == Operator.EXISTS else not exists
            
        if self.field not in facts:
            return False
            
        fact_value = facts[self.field]
        
        try:
            if self.operator == Operator.EQUALS:
                return fact_value == self.value
            elif self.operator == Operator.NOT_EQUALS:
                return fact_value != self.value
            elif self.operator == Operator.GREATER_THAN:
                return float(fact_value) > float(self.value)
            elif self.operator == Operator.LESS_THAN:
                return float(fact_value) < float(self.value)
            elif self.operator == Operator.GREATER_EQUAL:
                return float(fact_value) >= float(self.value)
            elif self.operator == Operator.LESS_EQUAL:
                return float(fact_value) <= float(self.value)
            elif self.operator == Operator.IN:
                return fact_value in self.value
            elif self.operator == Operator.NOT_IN:
                return fact_value not in self.value
            elif self.operator == Operator.CONTAINS:
                return self.value in fact_value
            elif self.operator == Operator.NOT_CONTAINS:
                return self.value not in fact_value
            elif self.operator == Operator.MATCHES_REGEX:
                return bool(re.match(self.value, str(fact_value)))
        except (ValueError, TypeError):
            logger.warning(f"Type conversion failed for {self.field}")
            return False
        
        return False

# New Pydantic models for report
class RuleUploadStats(BaseModel):
    total_rules_processed: int
    successful_uploads: int
    failed_uploads: int
    validation_failures: int
    duplicate_rules: int
    database_errors: int
    success_rate: float

class RuleError(BaseModel):
    row: int
    rule_name: str
    error_type: str
    error_message: str
    validation_feedback: Optional[str] = None
    suggested_improvements: Optional[List[str]] = None

class UploadReport(BaseModel):
    report_id: str = Field(default_factory=lambda: datetime.now().strftime("%Y%m%d_%H%M%S"))
    timestamp: datetime = Field(default_factory=datetime.now)
    filename: str
    stats: RuleUploadStats
    successful_rules: List[Dict[str, Any]]
    errors: List[RuleError]
    processing_time: float

# Add this new model to your database models
class UploadReportModel(Base):
    __tablename__ = REPORTS_TABLE
    
    report_id = Column(String, primary_key=True)
    timestamp = Column(String)
    filename = Column(String)
    stats = Column(JSON)
    successful_rules = Column(JSON)
    errors = Column(JSON)
    processing_time = Column(Float)

## conflict resolution code 


# Placeholder for evaluate_with_llm function (replace with your actual implementation)
async def evaluate_with_llm(fact_data: Dict[str, Any], rule: RuleModel) -> Dict[str, Any]:
    """
    Evaluate a rule against fact data using an LLM.
    """
    try:
        # Simplified placeholder - replace with actual LLM call
        conditions = json.loads(rule.conditions)
        actions = json.loads(rule.actions)

        # Example: Check if all conditions are met (simplified)
        conditions_met = True  # Replace with actual LLM logic

        return {
            "conditions_met": conditions_met,
            "actions_to_take": actions if conditions_met else [],
            "confidence_score": 0.9 if conditions_met else 0.1,  # Example confidence
            "reasoning": "LLM evaluated conditions and determined actions"
        }

    except Exception as e:
        logger.error(f"LLM evaluation failed: {str(e)}")
        return {
            "conditions_met": False,
            "actions_to_take": [],
            "confidence_score": 0.0,
            "reasoning": f"LLM evaluation failed: {str(e)}"
        }

# Global variables
client = AsyncOpenAI(api_key=OPEN_AI_KEY)
REQUEST_COUNT = Counter("http_requests_total", "Total HTTP Requests", ["method", "endpoint"])
REQUEST_LATENCY = Histogram("http_request_duration_seconds", "HTTP request latency", ["endpoint"])

# Database configuration
DATABASE_URL = POSTGRES_URL
engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# Lifespan context manager
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    redis = await aioredis.from_url(
        REDIS_URL,
        encoding="utf8",
        decode_responses=True
    )

    await FastAPILimiter.init(redis)
    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")

    # ✅ Fix: Ensure database schema is created before use
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)  # ✅ Ensure table exists

    yield  # Let FastAPI start the application

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

async def evaluate_facts(
    fact: Fact,
    db: AsyncSession,
    use_llm: bool = False,
    context_filter: Optional[str] = None
) -> Dict[str, Any]:
    """
    Enhanced fact evaluation with flexible rule matching
    """
    try:
        # Build query with optional context filter
        query = select(RuleModel)
        if context_filter:
            query = query.where(RuleModel.context == context_filter)
        
        rules = (await db.execute(query)).scalars().all()
        results = []

        for rule in rules:
            if use_llm:
                result = await evaluate_with_llm(fact.facts, rule)
                if result["conditions_met"]:
                    results.append({
                        "rule_name": rule.name,
                        "actions": result["actions_to_take"],
                        "confidence": result["confidence_score"],
                        "reasoning": result["reasoning"]
                    })
            else:
                # Convert stored JSON conditions to Condition objects
                conditions = [Condition(**cond) for cond in json.loads(rule.conditions)]
                actions = json.loads(rule.actions)
                
                # Evaluate all conditions
                conditions_met = all(condition.evaluate(fact.facts) for condition in conditions)
                
                if conditions_met:
                    results.append({
                        "rule_name": rule.name,
                        "rule_id": rule.id,
                        "actions": actions,
                        "priority": rule.priority
                    })

        # Sort results by priority if any matches found
        if results:
            results.sort(key=lambda x: x.get("priority", 0), reverse=True)

        return {
            "context": fact.context,
            "matches_found": len(results),
            "matching_rules": results,
            "evaluation_method": "llm" if use_llm else "traditional",
            "evaluated_facts": fact.facts
        }

    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

async def evaluate_conditions(conditions: List[Dict[str, Any]], facts: Dict[str, Any]) -> bool:
    """
    Enhanced condition evaluation with type handling and flexible operators
    """
    for condition in conditions:
        fact_value = facts.get(condition["field"])
        if fact_value is None:
            return False

        # Convert types to match if needed
        expected_value = condition["value"]
        try:
            fact_value = type(expected_value)(fact_value)
        except (ValueError, TypeError):
            logger.warning(f"Type conversion failed for {condition['field']}")
            return False

        # Enhanced operator handling
        operator = condition.get("operator", "==")
        if not await check_condition(fact_value, operator, expected_value):
            return False

    return True

async def check_condition(fact_value: Any, operator: str, expected_value: Any) -> bool:
    """
    Flexible condition checking with multiple operator support
    """
    operators = {
        "==": lambda x, y: x == y,
        "!=": lambda x, y: x != y,
        ">": lambda x, y: x > y,
        "<": lambda x, y: x < y,
        ">=": lambda x, y: x >= y,
        "<=": lambda x, y: x <= y,
        "in": lambda x, y: x in y,
        "not_in": lambda x, y: x not in y,
        "contains": lambda x, y: y in x if hasattr(x, '__contains__') else False,
        "starts_with": lambda x, y: str(x).startswith(str(y)),
        "ends_with": lambda x, y: str(x).endswith(str(y))
    }
    
    return operators.get(operator, operators["=="])(fact_value, expected_value)

# Database dependency
async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

# Helper functions
async def validate_rule_with_llm(rule: EnhancedRule) -> RuleValidationResult:
    """Validate a rule using LLM."""

    conditions_json = json.dumps(rule.conditions, indent=2, ensure_ascii=False)  # Important!
    actions_json = json.dumps(rule.actions, indent=2, ensure_ascii=False)      # Important!

    prompt = f"""
    Please analyze this business rule for logical consistency and potential improvements:
    ID: {rule.id}
    Rule Name: {rule.name}
    Description: {rule.description or 'No description provided'}
    Context: {rule.context or 'No context provided'}

    Conditions: {conditions_json}
    Actions: {actions_json}

    Please analyze the following aspects:
    1. Logical consistency between conditions and actions
    2. Potential conflicts with common business rules
    3. Completeness of the rule
    4. Potential edge cases
    5. Suggested improvements

    Provide your response in JSON format with the following structure:
    {{
        "is_valid": boolean,
        "feedback": "detailed analysis",
        "suggested_improvements": ["improvement1", "improvement2", ...]
    }}
    """

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
            model=LLM_MODEL,
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
            model=LLM_MODEL,
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
            model=LLM_MODEL,
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
        logger.info(f"this is the look of the actions from the LLM call {actions}")
        
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
    """Process rules from Excel file containing natural language text."""
    try:
        logger.info("Processing natural language rules from Excel file")
        contents = await file.read()
        df = pd.read_excel(io.BytesIO(contents))
        
        # Validate required columns
        required_columns = ['id', 'Conditions', 'Actions']
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
                # Extract and validate ID
                # Extract and validate ID (convert to integer)
                try:
                    rule_id = int(row.get('id', ''))  # Convert to integer here
                except ValueError:
                    raise ValueError(f"Invalid ID for row {index + 1}. ID must be an integer.")

                # Extract rule name with fallback
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
                
                # Process conditions text
                conditions_text = str(row.get('Conditions', '')).strip()
                if not conditions_text or conditions_text.lower() == 'nan':
                    raise ValueError(f"Empty conditions text for rule {rule_name}")
                
                logger.info(f"Processing rule text: {conditions_text}")
                rule_conditions = await extract_conditions_from_text(conditions_text, client)
                
                # Validate extracted conditions
                if not rule_conditions:
                    raise ValueError(f"Failed to extract conditions from text for rule {rule_name}")
                
                logger.info(f"DEBUG: Rule Extracted: {json.dumps(rule_conditions, indent=2)}")
                
                # Process actions text
                actions_text = str(row['Actions']).strip()
                if actions_text.lower() == 'nan' or not actions_text:
                    raise ValueError(f"Empty actions text for rule {rule_name}")
                
                logger.info(f"Processing actions text: {actions_text}")
                rule_actions = await extract_actions_from_text(actions_text, client)
                
                # Validate extracted actions
                if not rule_actions:
                    raise ValueError(f"Failed to extract actions from text for rule {rule_name}")
                
                logger.info(f"DEBUG: Actions Extracted: {json.dumps(rule_actions, indent=2)}")
                
                # Create EnhancedRule object for validation
                enhanced_rule = EnhancedRule(
                    id=rule_id,
                    name=rule_name,
                    conditions=rule_conditions,
                    actions=rule_actions,
                    description=rule_description,
                    context=str(row.get('Context', '')).strip() or None,
                    llm_config=LLMConfig()
                )
                
                # Validate rule with LLM
                validation_result = await validate_rule_with_llm(enhanced_rule)
                
                if not validation_result.is_valid:
                    logger.warning(f"Rule {rule_name} failed validation: {validation_result.feedback}")
                    errors.append({
                       "row": index + 1,
                       "rule_name": rule_name,
                       "error": "Validation failed",
                       "feedback": validation_result.feedback,
                       "improvements": validation_result.suggested_improvements
                    })
                    continue  # Skipping rule insertion
                else:
                    logger.info(f"Rule {rule_name} passed validation and will be inserted.")

                
                # Check if rule already exists in the database
                existing_rule = await db.execute(select(RuleModel).where(RuleModel.id == rule_id))
                if existing_rule.scalar():
                    logger.warning(f"Skipping duplicate rule: {rule_name} (ID: {rule_id}) already exists in the database.")
                    continue  # Skip this rule and move to the next one
                
                # Create database rule with proper JSON string conversion
                db_rule = RuleModel(
                    id=rule_id,      # Now an integer
                    name=rule_name,
                    conditions=json.dumps(rule_conditions, ensure_ascii=False),  # Convert to JSON string
                    actions=json.dumps(rule_actions, ensure_ascii=False),        # Convert to JSON string
                    description=rule_description,
                    context=enhanced_rule.context,
                    llm_config=enhanced_rule.llm_config.dict() if enhanced_rule.llm_config else None
                )

                # Add rule to database
                logger.info(f"Adding rule to database: {rule_name}")
                db.add(db_rule)
                await db.commit()
                await db.refresh(db_rule)
                
                try:
                   db.add(db_rule)
                   await db.commit()
                   await db.refresh(db_rule)
                   logger.info(f"Successfully inserted rule {rule_name} with ID {rule_id}")
                except Exception as e:
                   logger.error(f"Failed to insert rule {rule_name}: {str(e)}")
                   await db.rollback()
                   errors.append({"row": index + 1, "rule_name": rule_name, "error": f"Database commit failed: {str(e)}"})


                
                rules_added.append({
                    "name": rule_name,
                    "id": rule_id, # Use the database-assigned ID
                    "original_conditions": conditions_text,
                    "parsed_conditions": rule_conditions,
                    "original_actions": actions_text,
                    "parsed_actions": rule_actions
                })
                
                logger.info(f"Successfully processed rule: {rule_name}")
                
            except ValueError as ve:
                logger.error(f"Validation error in row {index + 1}: {str(ve)}")
                await db.rollback()
                errors.append({
                    "row": index + 1,
                    "rule_name": rule_name if 'rule_name' in locals() else f"Row_{index + 1}",
                    "error": str(ve)
                })
                continue
                
            except Exception as e:
                logger.error(f"Error processing row {index + 1}: {str(e)}", exc_info=True)
                await db.rollback()
                errors.append({
                    "row": index + 1,
                    "rule_name": rule_name if 'rule_name' in locals() else f"Row_{index + 1}",
                    "error": f"Unexpected error: {str(e)}"
                })
                continue
        
        # Prepare response
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
        logger.error(f"Unexpected error processing Excel file: {str(e)}", exc_info=True)
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
            id=rule.id,
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
    
# New endpoint to generate and store upload report
@app.post("/rules/upload-report/", response_model=UploadReport)
async def create_upload_report(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db)
):
    start_time = datetime.now()
    
    try:
        # Process the rules upload
        upload_result = await process_excel_rules(file, db, client)
        
        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()
        
        # Extract successful rules and errors
        successful_rules = upload_result.get("success", {}).get("rules", [])
        errors = upload_result.get("errors", [])
        
        # Calculate statistics
        total_rules = len(successful_rules) + len(errors)
        validation_failures = sum(1 for e in errors if "validation failed" in e.get("error", "").lower())
        duplicate_rules = sum(1 for e in errors if "duplicate" in e.get("error", "").lower())
        database_errors = sum(1 for e in errors if "database" in e.get("error", "").lower())
        
        # Create stats object
        stats = RuleUploadStats(
            total_rules_processed=total_rules,
            successful_uploads=len(successful_rules),
            failed_uploads=len(errors),
            validation_failures=validation_failures,
            duplicate_rules=duplicate_rules,
            database_errors=database_errors,
            success_rate=len(successful_rules) / total_rules if total_rules > 0 else 0
        )
        
        # Format errors for report
        formatted_errors = [
            RuleError(
                row=error.get("row", 0),
                rule_name=error.get("rule_name", "Unknown"),
                error_type=error.get("error", "").split(":")[0],
                error_message=error.get("error", "Unknown error"),
                validation_feedback=error.get("feedback"),
                suggested_improvements=error.get("improvements")
            )
            for error in errors
        ]
        
        # Create report object
        report = UploadReport(
            filename=file.filename,
            stats=stats,
            successful_rules=successful_rules,
            errors=formatted_errors,
            processing_time=processing_time
        )
        
        # Store report in database
        db_report = UploadReportModel(
            report_id=report.report_id,
            timestamp=report.timestamp.isoformat(),
            filename=report.filename,
            stats=report.stats.dict(),
            successful_rules=report.successful_rules,
            errors=[error.dict() for error in report.errors],
            processing_time=report.processing_time
        )
        
        db.add(db_report)
        await db.commit()
        
        return report
        
    except Exception as e:
        logger.error(f"Error generating upload report: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate upload report: {str(e)}"
        )

# Endpoint to retrieve a specific report
@app.get("/rules/upload-report/{report_id}", response_model=UploadReport)
async def get_upload_report(
    report_id: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        result = await db.execute(
            select(UploadReportModel).where(UploadReportModel.report_id == report_id)
        )
        report = result.scalar_one_or_none()
        
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
            
        return UploadReport(
            report_id=report.report_id,
            timestamp=datetime.fromisoformat(report.timestamp),
            filename=report.filename,
            stats=RuleUploadStats(**report.stats),
            successful_rules=report.successful_rules,
            errors=[RuleError(**error) for error in report.errors],
            processing_time=report.processing_time
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving upload report: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve upload report: {str(e)}"
        )

# Endpoint to list all reports
@app.get("/rules/upload-reports/", response_model=List[UploadReport])
async def list_upload_reports(
    db: AsyncSession = Depends(get_db),
    skip: int = 0,
    limit: int = 10
):
    try:
        result = await db.execute(
            select(UploadReportModel)
            .order_by(UploadReportModel.timestamp.desc())
            .offset(skip)
            .limit(limit)
        )
        
        reports = result.scalars().all()
        
        return [
            UploadReport(
                report_id=report.report_id,
                timestamp=datetime.fromisoformat(report.timestamp),
                filename=report.filename,
                stats=RuleUploadStats(**report.stats),
                successful_rules=report.successful_rules,
                errors=[RuleError(**error) for error in report.errors],
                processing_time=report.processing_time
            )
            for report in reports
        ]
        
    except Exception as e:
        logger.error(f"Error listing upload reports: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list upload reports: {str(e)}"
        )    

@app.post("/evaluate/", response_model=Dict[str, Any])
async def evaluate(
    fact: Fact,
    db: AsyncSession = Depends(get_db),
    use_llm: bool = False,
    context_filter: Optional[str] = None,
    _: None = Depends(RateLimiter(times=5, seconds=60))
):
    """
    Evaluate facts against rules with flexible matching
    """
    return await evaluate_facts(fact, db, use_llm, context_filter)

# Example of how to create a rule with the new structure
async def create_rule_example(db: AsyncSession):
    rule = RuleModel(
        name="High Value Customer",
        context="finance",
        conditions=json.dumps([
            {
                "field": "savings",
                "operator": Operator.GREATER_THAN,
                "value": 100000
            },
            {
                "field": "age",
                "operator": Operator.GREATER_THAN,
                "value": 50
            }
        ]),
        actions=json.dumps([
            {
                "type": "notify",
                "target": "investment_advisor",
                "parameters": {
                    "priority": "high",
                    "message": "High value customer requires consultation"
                }
            }
        ]),
        priority=1
    )
    
    db.add(rule)
    await db.commit()

class ConflictType(str, Enum):
    CONTRADICTORY = "contradictory"  # Rules with opposite actions
    REDUNDANT = "redundant"          # Rules with same conditions and actions
    SUBSUMPTION = "subsumption"      # One rule is more specific than another
    SHADOWING = "shadowing"          # Higher priority rule always triggers before lower
    CIRCULAR = "circular"            # Rules form a dependency cycle

# Add new Pydantic models for conflict detection
class RuleConflict(BaseModel):
    conflict_type: ConflictType
    rule_ids: List[int]
    description: str
    severity: str  # "high", "medium", "low"
    resolution_suggestions: List[str]

class ConflictDetectionResult(BaseModel):
    conflicts_found: int
    conflicts: List[RuleConflict]
    analysis_timestamp: datetime = Field(default_factory=datetime.now)

# Add this new database model for storing detected conflicts
class ConflictModel(Base):
    __tablename__ = "rule_conflicts"
    
    id = Column(Integer, primary_key=True, index=True)
    conflict_type = Column(String)
    rule_ids = Column(JSON)  # Store list of rule IDs involved
    description = Column(String)
    severity = Column(String)
    resolution_suggestions = Column(JSON)  # Store list of suggestions
    detected_at = Column(String)  # ISO format timestamp
    resolved = Column(Boolean, default=False)
    resolution_notes = Column(String, nullable=True)

# Add these conflict detection and resolution functions

async def detect_contradictory_conflicts(rules: List[RuleModel]) -> List[RuleConflict]:
    """
    Detect rules with same or similar conditions but contradictory actions.
    """
    conflicts = []
    
    # Group rules that have similar conditions
    for i, rule1 in enumerate(rules):
        rule1_conditions = json.loads(rule1.conditions)
        rule1_actions = json.loads(rule1.actions)
        
        for j, rule2 in enumerate(rules[i+1:], i+1):
            if rule1.id == rule2.id:
                continue
                
            rule2_conditions = json.loads(rule2.conditions)
            rule2_actions = json.loads(rule2.actions)
            
            # Check for condition similarity (simplified version)
            condition_similarity = calculate_condition_similarity(rule1_conditions, rule2_conditions)
            
            # If conditions are similar but actions contradict
            if condition_similarity > 0.7 and are_actions_contradictory(rule1_actions, rule2_actions):
                conflicts.append(RuleConflict(
                    conflict_type=ConflictType.CONTRADICTORY,
                    rule_ids=[rule1.id, rule2.id],
                    description=f"Rules {rule1.name} and {rule2.name} have similar conditions but contradictory actions",
                    severity="high",
                    resolution_suggestions=[
                        f"Merge rules with consistent actions",
                        f"Add additional conditions to differentiate rule contexts",
                        f"Adjust rule priorities to ensure consistent behavior"
                    ]
                ))
    
    return conflicts

async def detect_redundant_conflicts(rules: List[RuleModel]) -> List[RuleConflict]:
    """
    Detect rules with identical or near-identical conditions and actions.
    """
    conflicts = []
    
    for i, rule1 in enumerate(rules):
        rule1_conditions = json.loads(rule1.conditions)
        rule1_actions = json.loads(rule1.actions)
        
        for j, rule2 in enumerate(rules[i+1:], i+1):
            if rule1.id == rule2.id:
                continue
                
            rule2_conditions = json.loads(rule2.conditions)
            rule2_actions = json.loads(rule2.actions)
            
            # Check for high similarity in both conditions and actions
            condition_similarity = calculate_condition_similarity(rule1_conditions, rule2_conditions)
            action_similarity = calculate_action_similarity(rule1_actions, rule2_actions)
            
            if condition_similarity > 0.9 and action_similarity > 0.9:
                conflicts.append(RuleConflict(
                    conflict_type=ConflictType.REDUNDANT,
                    rule_ids=[rule1.id, rule2.id],
                    description=f"Rules {rule1.name} and {rule2.name} are redundant with similar conditions and actions",
                    severity="medium",
                    resolution_suggestions=[
                        f"Consolidate these rules into a single rule",
                        f"Delete one of the rules"
                    ]
                ))
    
    return conflicts

async def detect_subsumption_conflicts(rules: List[RuleModel]) -> List[RuleConflict]:
    """
    Detect when one rule's conditions are a subset of another's (one rule is more specific).
    """
    conflicts = []
    
    for i, rule1 in enumerate(rules):
        rule1_conditions = json.loads(rule1.conditions)
        rule1_actions = json.loads(rule1.actions)
        
        for j, rule2 in enumerate(rules):
            if rule1.id == rule2.id:
                continue
                
            rule2_conditions = json.loads(rule2.conditions)
            rule2_actions = json.loads(rule2.actions)
            
            # Check if rule1 is more specific than rule2
            if is_more_specific(rule1_conditions, rule2_conditions):
                # Check if actions are inconsistent
                if not are_actions_consistent(rule1_actions, rule2_actions):
                    conflicts.append(RuleConflict(
                        conflict_type=ConflictType.SUBSUMPTION,
                        rule_ids=[rule1.id, rule2.id],
                        description=f"Rule {rule1.name} is more specific than {rule2.name} but has inconsistent actions",
                        severity="medium",
                        resolution_suggestions=[
                            f"Adjust rule priorities to ensure the more specific rule has higher priority",
                            f"Modify the more general rule to exclude the specific case"
                        ]
                    ))
    
    return conflicts

async def detect_shadowing_conflicts(rules: List[RuleModel]) -> List[RuleConflict]:
    """
    Detect when a higher priority rule always triggers before a lower priority one,
    making the lower priority rule unreachable.
    """
    conflicts = []
    
    # Sort rules by priority (highest first)
    sorted_rules = sorted(rules, key=lambda r: r.priority, reverse=True)
    
    for i, high_rule in enumerate(sorted_rules):
        high_conditions = json.loads(high_rule.conditions)
        
        for low_rule in sorted_rules[i+1:]:
            low_conditions = json.loads(low_rule.conditions)
            
            # Check if high priority rule shadows the low priority one
            if is_shadowing(high_conditions, low_conditions):
                conflicts.append(RuleConflict(
                    conflict_type=ConflictType.SHADOWING,
                    rule_ids=[high_rule.id, low_rule.id],
                    description=f"Higher priority rule {high_rule.name} shadows {low_rule.name}, making it unreachable",
                    severity="high" if low_rule.priority > 0 else "medium",
                    resolution_suggestions=[
                        f"Add conditions to differentiate the rules",
                        f"Consolidate rules if the shadowed rule is not needed",
                        f"Adjust rule priorities"
                    ]
                ))
    
    return conflicts

async def detect_circular_conflicts(rules: List[RuleModel]) -> List[RuleConflict]:
    """
    Detect circular dependencies between rules (primarily applicable in chained rule systems).
    """
    conflicts = []
    
    # Build a dependency graph
    dependencies = {}
    for rule in rules:
        rule_actions = json.loads(rule.actions)
        dependencies[rule.id] = []
        
        # For each rule, identify rules it might trigger
        for action in rule_actions:
            if action.get("type") == "trigger_rule":
                dependencies[rule.id].append(action.get("parameters", {}).get("rule_id"))
    
    # Detect cycles in the dependency graph
    cycles = find_cycles(dependencies)
    
    for cycle in cycles:
        rule_names = [next(r.name for r in rules if r.id == rule_id) for rule_id in cycle]
        conflicts.append(RuleConflict(
            conflict_type=ConflictType.CIRCULAR,
            rule_ids=cycle,
            description=f"Circular dependency detected between rules: {', '.join(rule_names)}",
            severity="high",
            resolution_suggestions=[
                f"Break the dependency cycle by modifying rule actions",
                f"Add conditions to prevent infinite loops",
                f"Implement a maximum execution depth"
            ]
        ))
    
    return conflicts

# Helper functions for conflict detection

def calculate_condition_similarity(conditions1: List[Dict], conditions2: List[Dict]) -> float:
    """
    Calculate similarity between two sets of conditions (0.0 to 1.0).
    Simplified implementation - in real world, consider more sophisticated metrics.
    """
    if not conditions1 or not conditions2:
        return 0.0
    
    # Count matching fields and operators
    matches = 0
    total = max(len(conditions1), len(conditions2))
    
    for cond1 in conditions1:
        for cond2 in conditions2:
            if cond1.get("field") == cond2.get("field") and cond1.get("operator") == cond2.get("operator"):
                # For numeric values, check if they're within a reasonable range
                if isinstance(cond1.get("value"), (int, float)) and isinstance(cond2.get("value"), (int, float)):
                    if abs(cond1.get("value") - cond2.get("value")) / max(abs(cond1.get("value")), abs(cond2.get("value"))) < 0.1:
                        matches += 1
                # For other values, check for equality
                elif cond1.get("value") == cond2.get("value"):
                    matches += 1
    
    return matches / total

def calculate_action_similarity(actions1: List[Dict], actions2: List[Dict]) -> float:
    """
    Calculate similarity between two sets of actions (0.0 to 1.0).
    """
    if not actions1 or not actions2:
        return 0.0
    
    # Count matching action types and targets
    matches = 0
    total = max(len(actions1), len(actions2))
    
    for act1 in actions1:
        for act2 in actions2:
            if act1.get("type") == act2.get("type") and act1.get("target") == act2.get("target"):
                # Compare parameters (simplified)
                param_match = False
                act1_params = act1.get("parameters", {})
                act2_params = act2.get("parameters", {})
                
                if act1_params and act2_params:
                    common_keys = set(act1_params.keys()) & set(act2_params.keys())
                    if common_keys:
                        matching_values = sum(1 for k in common_keys if act1_params[k] == act2_params[k])
                        param_match = matching_values / len(common_keys) > 0.7
                
                if param_match:
                    matches += 1
    
    return matches / total

def are_actions_contradictory(actions1: List[Dict], actions2: List[Dict]) -> bool:
    """
    Determine if two sets of actions contradict each other.
    A contradiction occurs when the same target is modified in opposing ways.
    """
    for act1 in actions1:
        for act2 in actions2:
            # Check for opposing updates to the same target
            if act1.get("type") == act2.get("type") == "update":
                if act1.get("target") == act2.get("target"):
                    # If updating the same field with different values
                    act1_value = act1.get("parameters", {}).get("value")
                    act2_value = act2.get("parameters", {}).get("value")
                    if act1_value is not None and act2_value is not None and act1_value != act2_value:
                        return True
            
            # Check for create and delete on same target
            if (act1.get("type") == "create" and act2.get("type") == "delete" or
                act1.get("type") == "delete" and act2.get("type") == "create"):
                if act1.get("target") == act2.get("target"):
                    return True
    
    return False

def are_actions_consistent(actions1: List[Dict], actions2: List[Dict]) -> bool:
    """
    Check if actions are consistent with each other (not contradictory).
    """
    return not are_actions_contradictory(actions1, actions2)

def is_more_specific(conditions1: List[Dict], conditions2: List[Dict]) -> bool:
    """
    Determine if conditions1 is more specific than conditions2
    (i.e., conditions1 is a subset of conditions2 with additional constraints).
    """
    # If conditions1 has more conditions, it might be more specific
    if len(conditions1) <= len(conditions2):
        return False
    
    # Check if all conditions in conditions2 are present in conditions1
    for cond2 in conditions2:
        found_match = False
        for cond1 in conditions1:
            if (cond1.get("field") == cond2.get("field") and 
                cond1.get("operator") == cond2.get("operator") and
                cond1.get("value") == cond2.get("value")):
                found_match = True
                break
        
        if not found_match:
            return False
    
    return True

def is_shadowing(high_conditions: List[Dict], low_conditions: List[Dict]) -> bool:
    """
    Determine if the high priority rule shadows the low priority rule.
    This happens when high_conditions is a subset of or equal to low_conditions.
    """
    # If high rule has more conditions, it's less likely to shadow
    if len(high_conditions) > len(low_conditions):
        return False
    
    # Check if all conditions in high_conditions have matching or broader conditions in low_conditions
    for high_cond in high_conditions:
        found_match = False
        for low_cond in low_conditions:
            if high_cond.get("field") == low_cond.get("field"):
                # Check if high condition is broader or equal to low condition
                high_op = high_cond.get("operator")
                low_op = low_cond.get("operator")
                high_val = high_cond.get("value")
                low_val = low_cond.get("value")
                
                # Example: Check numeric ranges
                if high_op in [">", ">="] and low_op in [">", ">="]:
                    if high_val <= low_val:
                        found_match = True
                        break
                elif high_op in ["<", "<="] and low_op in ["<", "<="]:
                    if high_val >= low_val:
                        found_match = True
                        break
                # Equality operators
                elif high_op == "==" and low_op == "==":
                    if high_val == low_val:
                        found_match = True
                        break
        
        if not found_match:
            return False
    
    return True

def find_cycles(dependency_graph: Dict[int, List[int]]) -> List[List[int]]:
    """
    Find cycles in a dependency graph using DFS.
    """
    cycles = []
    visited = set()
    path = []
    
    def dfs(node, parent=None):
        if node in path:
            # Cycle detected
            cycle_start = path.index(node)
            cycles.append(path[cycle_start:] + [node])
            return
        
        if node in visited:
            return
        
        visited.add(node)
        path.append(node)
        
        for neighbor in dependency_graph.get(node, []):
            if neighbor is not None and neighbor != parent:
                dfs(neighbor, node)
        
        path.pop()
    
    for node in dependency_graph:
        if node not in visited:
            dfs(node)
    
    return cycles

# Add the conflict resolution strategy models

class ResolutionStrategy(str, Enum):
    PRIORITY = "priority"                # Use rule priorities to resolve conflicts
    SPECIFICITY = "specificity"          # More specific rules override general ones
    RECENCY = "recency"                  # Recently added/modified rules take precedence
    CONTEXT_BASED = "context_based"      # Use context to determine which rule applies
    LLM_ASSISTED = "llm_assisted"        # Use LLM to resolve ambiguous cases

class ConflictResolutionConfig(BaseModel):
    primary_strategy: ResolutionStrategy = ResolutionStrategy.PRIORITY
    secondary_strategy: Optional[ResolutionStrategy] = ResolutionStrategy.SPECIFICITY
    use_llm_for_complex_cases: bool = False
    allow_multiple_matches: bool = False
    max_matches: int = 3  # Only return top N matches when multiple matches are allowed

# Add this to your RuleModel
# priority = Column(Integer, default=0)  # Already exists in your model
# created_at = Column(String, default=lambda: datetime.now().isoformat())
# updated_at = Column(String, default=lambda: datetime.now().isoformat())
# specificity_score = Column(Float, default=0.0)  # Higher means more specific

# New function to resolve conflicts during fact evaluation

async def resolve_conflicts(matching_rules: List[Dict], resolution_config: ConflictResolutionConfig) -> List[Dict]:
    """
    Apply conflict resolution strategies to determine which rules should be applied.
    """
    if not matching_rules:
        return []
    
    if len(matching_rules) == 1 or resolution_config.allow_multiple_matches:
        # No conflicts or we're allowing multiple matches
        if resolution_config.allow_multiple_matches and len(matching_rules) > resolution_config.max_matches:
            # Apply primary strategy to limit the number of matches
            sorted_rules = await apply_resolution_strategy(
                matching_rules, 
                resolution_config.primary_strategy
            )
            return sorted_rules[:resolution_config.max_matches]
        return matching_rules
    
    # Apply primary resolution strategy
    resolved_rules = await apply_resolution_strategy(
        matching_rules, 
        resolution_config.primary_strategy
    )
    
    # If we still have multiple rules and a secondary strategy is defined
    if len(resolved_rules) > 1 and resolution_config.secondary_strategy:
        resolved_rules = await apply_resolution_strategy(
            resolved_rules,
            resolution_config.secondary_strategy
        )
    
    # If we still have multiple rules and LLM assistance is enabled
    if len(resolved_rules) > 1 and resolution_config.use_llm_for_complex_cases:
        resolved_rules = await resolve_with_llm(resolved_rules)
    
    # Return only the top rule if we're not allowing multiple matches
    if not resolution_config.allow_multiple_matches:
        return resolved_rules[:1]
    
    return resolved_rules[:resolution_config.max_matches]

async def apply_resolution_strategy(rules: List[Dict], strategy: ResolutionStrategy) -> List[Dict]:
    """
    Apply a specific resolution strategy to sort/filter rules.
    """
    if strategy == ResolutionStrategy.PRIORITY:
        # Sort by priority (highest first)
        return sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)
    
    elif strategy == ResolutionStrategy.SPECIFICITY:
        # Sort by specificity score (highest first)
        return sorted(rules, key=lambda r: r.get("specificity_score", 0), reverse=True)
    
    elif strategy == ResolutionStrategy.RECENCY:
        # Sort by updated_at (most recent first)
        return sorted(rules, key=lambda r: r.get("updated_at", ""), reverse=True)
    
    elif strategy == ResolutionStrategy.CONTEXT_BASED:
        # This would require additional context information
        # For now, return as-is
        return rules
    
    return rules

async def resolve_with_llm(rules: List[Dict]) -> List[Dict]:
    """
    Use LLM to resolve complex rule conflicts.
    """
    try:
        rules_json = json.dumps([{
            "name": rule.get("rule_name"),
            "id": rule.get("rule_id"),
            "priority": rule.get("priority", 0),
            "actions": rule.get("actions", [])
        } for rule in rules], indent=2)
        
        prompt = f"""
        I need to resolve a conflict between these business rules that all matched:
        {rules_json}
        
        Please analyze these rules and determine which one(s) should take precedence.
        Consider:
        1. Rule specificity and priority
        2. Potential business impact
        3. Best practices for rule engines
        
        Return your response in JSON format with this structure:
        {{
            "selected_rule_ids": [list of rule IDs in order of precedence],
            "reasoning": "explanation of your decision"
        }}
        """
        
        response = await client.chat.completions.create(
            model=LLM_MODEL,
            temperature=0,
            messages=[
                {"role": "system", "content": "You are a business rules expert helping resolve rule conflicts."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        selected_ids = result.get("selected_rule_ids", [])
        
        # Reorder rules based on LLM selection
        id_to_rule = {rule.get("rule_id"): rule for rule in rules}
        reordered_rules = [id_to_rule[rule_id] for rule_id in selected_ids if rule_id in id_to_rule]
        
        # Add any rules not mentioned by the LLM at the end
        for rule in rules:
            if rule.get("rule_id") not in selected_ids:
                reordered_rules.append(rule)
        
        return reordered_rules
    
    except Exception as e:
        logger.error(f"LLM conflict resolution failed: {str(e)}")
        # Fall back to priority
        return sorted(rules, key=lambda r: r.get("priority", 0), reverse=True)

# Add this function to calculate and update rule specificity scores
async def calculate_rule_specificity(rule: RuleModel, db: AsyncSession) -> None:
    """
    Calculate and update a rule's specificity score.
    More specific rules have higher scores.
    """
    try:
        conditions = json.loads(rule.conditions)
        score = 0.0
        
        # Base score based on number of conditions
        score += len(conditions) * 10
        
        # Additional points for certain operator types
        for condition in conditions:
            operator = condition.get("operator")
            
            # Exact matches are more specific than ranges
            if operator == "==":
                score += 5
            elif operator in ["in", "not_in"]:
                score += 3
            elif operator in [">", "<", ">=", "<="]:
                score += 2
            
            # Field specificity
            if condition.get("field", "").count(".") > 0:  # Nested fields
                score += 3
        
        # Update the rule in the database
        rule.specificity_score = score
        await db.commit()
        
    except Exception as e:
        logger.error(f"Failed to calculate rule specificity: {str(e)}")

# Modify the evaluate_facts function to use conflict resolution

async def evaluate_facts(
    fact: Fact,
    db: AsyncSession,
    use_llm: bool = False,
    context_filter: Optional[str] = None,
    conflict_resolution: Optional[ConflictResolutionConfig] = None
) -> Dict[str, Any]:
    """
    Enhanced fact evaluation with conflict resolution
    """
    try:
        # Use default conflict resolution config if none provided
        if conflict_resolution is None:
            conflict_resolution = ConflictResolutionConfig()
        
        # Build query with optional context filter
        query = select(RuleModel)
        if context_filter:
            query = query.where(RuleModel.context == context_filter)
        
        rules = (await db.execute(query)).scalars().all()
        matching_rules = []

        for rule in rules:
            if use_llm:
                result = await evaluate_with_llm(fact.facts, rule)
                if result["conditions_met"]:
                    matching_rules.append({
                        "rule_name": rule.name,
                        "rule_id": rule.id,
                        "actions": result["actions_to_take"],
                        "confidence": result["confidence_score"],
                        "reasoning": result["reasoning"],
                        "priority": rule.priority,
                        "specificity_score": getattr(rule, "specificity_score", 0),
                        "updated_at": getattr(rule, "updated_at", "")
                    })
            else:
                # Convert stored JSON conditions to Condition objects
                conditions = [Condition(**cond) for cond in json.loads(rule.conditions)]
                actions = json.loads(rule.actions)
                
                # Evaluate all conditions
                conditions_met = all(condition.evaluate(fact.facts) for condition in conditions)
                
                if conditions_met:
                    matching_rules.append({
                        "rule_name": rule.name,
                        "rule_id": rule.id,
                        "actions": actions,
                        "priority": rule.priority,
                        "specificity_score": getattr(rule, "specificity_score", 0),
                        "updated_at": getattr(rule, "updated_at", "")
                    })

        # Apply conflict resolution
        resolved_rules = await resolve_conflicts(matching_rules, conflict_resolution)

        # Sort resolved rules by priority if any matches found
        if resolved_rules:
            resolved_rules.sort(key=lambda x: x.get("priority", 0), reverse=True)

        return {
            "context": fact.context,
            "matches_found": len(matching_rules),
            "matching_rules_before_resolution": len(matching_rules),
            "matching_rules_after_resolution": len(resolved_rules),
            "matching_rules": resolved_rules,
            "evaluation_method": "llm" if use_llm else "traditional",
            "conflict_resolution_strategy": conflict_resolution.primary_strategy,
            "evaluated_facts": fact.facts
        }

    except Exception as e:
        logger.error(f"Evaluation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(e)}")

# Add new endpoints for conflict detection and resolution

@app.post("/rules/detect-conflicts/", response_model=ConflictDetectionResult)
async def detect_conflicts(
    db: AsyncSession = Depends(get_db),
    context_filter: Optional[str] = None
):
    """
    Detect potential conflicts between rules
    """
    try:
        # Build query with optional context filter
        query = select(RuleModel)
        if context_filter:
            query = query.where(RuleModel.context == context_filter)
        
        rules = (await db.execute(query)).scalars().all()
        
        # Run all conflict detection methods
        contradictory = await detect_contradictory_conflicts(rules)
        redundant = await detect_redundant_conflicts(rules)
        subsumption = await detect_subsumption_conflicts(rules)
        shadowing = await detect_shadowing_conflicts(rules)
        circular = await detect_circular_conflicts(rules)
        
        # Combine all conflicts
        all_conflicts = contradictory + redundant + subsumption + shadowing + circular
        
        # Store conflicts in database
        for conflict in all_conflicts:
            db_conflict = ConflictModel(
                conflict_type=conflict.conflict_type,
                rule_ids=conflict.rule_ids,
                description=conflict.description,
                severity=conflict.severity,
                resolution_suggestions=conflict.resolution_suggestions,
                detected_at=datetime.now().isoformat(),
                resolved=False
            )
            db.add(db_conflict)
        
        await db.commit()
        
        return ConflictDetectionResult(
            conflicts_found=len(all_conflicts),
            conflicts=all_conflicts
        )
        
    except Exception as e:
        logger.error(f"Conflict detection failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Conflict detection failed: {str(e)}")

@app.post("/evaluate/with-resolution/", response_model=Dict[str, Any])
async def evaluate_with_resolution(
    fact: Fact,
    conflict_resolution: ConflictResolutionConfig,
    db: AsyncSession = Depends(get_db),
    use_llm: bool = False,
    context_filter: Optional[str] = None,
    _: None = Depends(RateLimiter(times=5, seconds=60))
):
    """
    Evaluate facts against rules with configurable conflict resolution
    """
    return await evaluate_facts(fact, db, use_llm, context_filter, conflict_resolution)

@app.get("/rules/conflicts/", response_model=List[RuleConflict])
async def get_conflicts(
    db: AsyncSession = Depends(get_db),
    resolved: Optional[bool] = None,
    severity: Optional[str] = None
):
    """
    Get all detected rule conflicts with optional filtering
    """
    try:
        query = select(ConflictModel)
        
        if resolved is not None:
            query = query.where(ConflictModel.resolved == resolved)
            
        if severity:
            query = query.where(ConflictModel.severity == severity)
            
        conflicts = (await db.execute(query)).scalars().all()
        
        return [
            RuleConflict(
                conflict_type=conflict.conflict_type,
                rule_ids=conflict.rule_ids,
                description=conflict.description,
                severity=conflict.severity,
                resolution_suggestions=conflict.resolution_suggestions
            ) for conflict in conflicts
        ]
        
    except Exception as e:
        logger.error(f"Failed to fetch conflicts: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to fetch conflicts")

@app.post("/rules/resolve-conflict/{conflict_id}", response_model=Dict[str, str])
async def resolve_conflict(
    conflict_id: int,
    resolution_notes: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """
    Mark a conflict as resolved with optional resolution notes
    """
    try:
        conflict = await db.get(ConflictModel, conflict_id)
        if not conflict:
            raise HTTPException(status_code=404, detail="Conflict not found")

        conflict.resolved = True
        conflict.resolution_notes = resolution_notes
        await db.commit()

        return {"message": f"Conflict {conflict_id} resolved"}

    except Exception as e:
        logger.error(f"Failed to resolve conflict: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to resolve conflict")

@app.get("/metrics")
async def metrics():
    return prometheus_client.generate_latest()

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
