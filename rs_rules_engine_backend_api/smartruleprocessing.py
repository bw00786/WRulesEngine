from fastapi import File, UploadFile, BackgroundTasks, HTTPException, Depends
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional, Union
import pandas as pd
from io import BytesIO
import re
from enum import Enum
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import json
from datetime import datetime
import aiohttp
import numpy as np

class RuleFormat(str, Enum):
    STANDARD = "standard"
    JSON = "json"
    IF_THEN = "if_then"
    NATURAL = "natural"

class FileFormat(str, Enum):
    XLSX = "xlsx"
    XLS = "xls"
    CSV = "csv"

class RuleType(str, Enum):
    SIMPLE = "simple"
    COMPLEX = "complex"
    CONDITIONAL = "conditional"
    TEMPORAL = "temporal"

class ValidationLevel(str, Enum):
    BASIC = "basic"
    STRICT = "strict"
    LLM = "llm"

class RuleOperator(str, Enum):
    EQUALS = "equals"
    GREATER_THAN = "greater_than"
    LESS_THAN = "less_than"
    CONTAINS = "contains"
    IN = "in"
    BETWEEN = "between"
    REGEX = "regex"

@dataclass
class RuleCondition:
    field: str
    operator: RuleOperator
    value: Any
    logic: Optional[str] = "AND"

@dataclass
class RuleAction:
    action_type: str
    target: str
    value: Any
    priority: int = 1

class EnhancedExcelRule(BaseModel):
    rule_id: str
    rule_name: str
    rule_type: RuleType
    rules: str
    description: Optional[str]
    priority: Optional[int] = 1
    tags: Optional[List[str]]
    effective_date: Optional[datetime]
    expiration_date: Optional[datetime]
    version: Optional[str]
    author: Optional[str]

class BatchProcessingConfig(BaseModel):
    batch_size: int = 100
    max_workers: int = 3
    timeout: int = 300
    retry_attempts: int = 3

class ValidationConfig(BaseModel):
    level: ValidationLevel
    custom_validators: Optional[List[str]]
    min_confidence: float = 0.7
    require_llm_validation: bool = False

class RuleParsingResult(BaseModel):
    conditions: List[Dict[str, Any]]
    actions: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    confidence_score: float

async def parse_complex_rule(rule_text: str, rule_format: RuleFormat) -> RuleParsingResult:
    """Enhanced rule parsing with support for multiple formats"""
    
    async def parse_if_then_format(text: str) -> Dict:
        patterns = {
            'if_then': r'IF\s+(.+?)\s+THEN\s+(.+?)(?:\s+ELSE\s+(.+))?$',
            'condition': r'(\w+)\s*(=|>|<|IN|BETWEEN|CONTAINS)\s*(.+?)(?:\s+AND|OR|$)',
            'action': r'SET\s+(\w+)\s*=\s*(.+?)(?:\s+AND|OR|$)'
        }
        
        match = re.match(patterns['if_then'], text, re.IGNORECASE)
        if not match:
            return None
            
        conditions_text, actions_text, else_text = match.groups()
        
        conditions = []
        for cond_match in re.finditer(patterns['condition'], conditions_text):
            field, op, value = cond_match.groups()
            conditions.append({
                'field': field.strip(),
                'operator': op.strip().lower(),
                'value': value.strip()
            })
            
        actions = []
        for action_match in re.finditer(patterns['action'], actions_text):
            target, value = action_match.groups()
            actions.append({
                'action_type': 'SET',
                'target': target.strip(),
                'value': value.strip()
            })
            
        return {'conditions': conditions, 'actions': actions}

    async def parse_json_format(text: str) -> Dict:
        try:
            data = json.loads(text)
            return {
                'conditions': data.get('conditions', []),
                'actions': data.get('actions', [])
            }
        except json.JSONDecodeError:
            return None

    async def parse_natural_language(text: str) -> Dict:
        # Use LLM to parse natural language rules
        prompt = f"""
        Parse this business rule into structured conditions and actions:
        {text}
        
        Return JSON in this format:
        {{
            "conditions": [
                {{"field": "field_name", "operator": "operator", "value": "value"}}
            ],
            "actions": [
                {{"action_type": "type", "target": "target", "value": "value"}}
            ]
        }}
        """
        
        try:
            response = await client.chat.completions.create(
                model="gpt-4-turbo-preview",
                messages=[
                    {"role": "system", "content": "You are a rule parsing expert."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0,
                response_format={"type": "json_object"}
            )
            return json.loads(response.choices[0].message.content)
        except Exception as e:
            logger.error(f"LLM parsing failed: {str(e)}")
            return None

    parsers = {
        RuleFormat.IF_THEN: parse_if_then_format,
        RuleFormat.JSON: parse_json_format,
        RuleFormat.NATURAL: parse_natural_language
    }
    
    parser = parsers.get(rule_format, parse_natural_language)
    result = await parser(rule_text)
    
    if not result:
        raise ValueError(f"Failed to parse rule using format {rule_format}")
        
    return RuleParsingResult(
        conditions=result['conditions'],
        actions=result['actions'],
        metadata={'format': rule_format.value},
        confidence_score=0.9 if rule_format != RuleFormat.NATURAL else 0.7
    )

class ExcelProcessor:
    def __init__(self, batch_config: BatchProcessingConfig):
        self.batch_config = batch_config
        self.executor = ThreadPoolExecutor(max_workers=batch_config.max_workers)
        
    async def process_file(self, file: UploadFile, file_format: FileFormat) -> pd.DataFrame:
        """Process different file formats"""
        content = await file.read()
        if file_format in [FileFormat.XLSX, FileFormat.XLS]:
            return pd.read_excel(BytesIO(content))
        elif file_format == FileFormat.CSV:
            return pd.read_csv(BytesIO(content))
        raise ValueError(f"Unsupported file format: {file_format}")
    
    async def validate_dataframe(self, df: pd.DataFrame) -> None:
        """Validate DataFrame structure and content"""
        required_columns = {'Rule ID', 'Rule Name', 'Rules', 'Description'}
        missing_columns = required_columns - set(df.columns)
        if missing_columns:
            raise ValueError(f"Missing required columns: {missing_columns}")
            
        # Validate data types and content
        if df['Rule ID'].duplicated().any():
            raise ValueError("Duplicate Rule IDs found")
            
        if df['Rules'].isna().any():
            raise ValueError("Empty rules found")
            
    async def process_rules_batch(
        self,
        rules: List[EnhancedExcelRule],
        db: AsyncSession,
        validation_config: ValidationConfig
    ) -> Dict[str, Any]:
        """Process a batch of rules with validation"""
        results = []
        
        async def process_single_rule(rule: EnhancedExcelRule) -> Dict[str, Any]:
            try:
                # Determine rule format
                if rule.rules.strip().startswith('{'):
                    rule_format = RuleFormat.JSON
                elif rule.rules.upper().startswith('IF '):
                    rule_format = RuleFormat.IF_THEN
                else:
                    rule_format = RuleFormat.NATURAL
                    
                # Parse rule
                parsed_rule = await parse_complex_rule(rule.rules, rule_format)
                
                # Validate based on configuration
                if validation_config.level == ValidationLevel.STRICT:
                    await self.validate_rule_strict(parsed_rule)
                elif validation_config.level == ValidationLevel.LLM:
                    llm_validation = await validate_rule_with_llm(rule)
                    if not llm_validation.is_valid:
                        raise ValueError(llm_validation.feedback)
                
                # Create database entry
                db_rule = EnhancedRuleModel(
                    name=rule.rule_name,
                    rule_type=rule.rule_type,
                    conditions=parsed_rule.conditions,
                    actions=parsed_rule.actions,
                    description=rule.description,
                    priority=rule.priority,
                    tags=rule.tags,
                    effective_date=rule.effective_date,
                    expiration_date=rule.expiration_date,
                    version=rule.version,
                    author=rule.author,
                    metadata={
                        'confidence_score': parsed_rule.confidence_score,
                        'format': rule_format.value,
                        'processing_date': datetime.utcnow().isoformat()
                    }
                )
                
                db.add(db_rule)
                return {
                    'rule_id': rule.rule_id,
                    'status': 'success',
                    'details': db_rule
                }
                
            except Exception as e:
                return {
                    'rule_id': rule.rule_id,
                    'status': 'failed',
                    'error': str(e)
                }
        
        # Process rules in batches
        for i in range(0, len(rules), self.batch_config.batch_size):
            batch = rules[i:i + self.batch_config.batch_size]
            batch_results = await asyncio.gather(
                *[process_single_rule(rule) for rule in batch]
            )
            results.extend(batch_results)
            
            # Commit batch
            try:
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.error(f"Batch commit failed: {str(e)}")
                
        return {
            'total': len(rules),
            'successful': len([r for r in results if r['status'] == 'success']),
            'failed': len([r for r in results if r['status'] == 'failed']),
            'results': results
        }

@app.post("/upload/")
async def upload_rules(
    file: UploadFile = File(...),
    batch_config: BatchProcessingConfig = BatchProcessingConfig(),
    validation_config: ValidationConfig = ValidationConfig(level=ValidationLevel.STRICT),
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks
):
    """
    Enhanced upload endpoint with support for multiple formats and batch processing
    """
    # Determine file format
    file_format = FileFormat(file.filename.split('.')[-1].lower())
    
    # Initialize processor
    processor = ExcelProcessor(batch_config)
    
    try:
        # Read and validate file
        df = await processor.process_file(file, file_format)
        await processor.validate_dataframe(df)
        
        # Convert to enhanced rules
        rules = []
        for _, row in df.iterrows():
            rule = EnhancedExcelRule(
                rule_id=str(row['Rule ID']),
                rule_name=str(row['Rule Name']),
                rule_type=RuleType.COMPLEX if 'IF' in str(row['Rules']).upper() else RuleType.SIMPLE,
                rules=str(row['Rules']),
                description=str(row.get('Description', '')),
                priority=int(row.get('Priority', 1)),
                tags=row.get('Tags', '').split(',') if 'Tags' in row else None,
                effective_date=pd.to_datetime(row.get('Effective Date')) if 'Effective Date' in row else None,
                expiration_date=pd.to_datetime(row.get('Expiration Date')) if 'Expiration Date' in row else None,
                version=str(row.get('Version', '1.0')),
                author=str(row.get('Author', 'System'))
            )
            rules.append(rule)
        
        # Process rules in batches
        results = await processor.process_rules_batch(rules, db, validation_config)
        
        # Clear cache in background
        background_tasks.add_task(FastAPICache.clear)
        
        return JSONResponse(
            status_code=200,
            content={
                'message': f"Processed {results['successful']} out of {results['total']} rules successfully",
                'results': results
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing file: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))