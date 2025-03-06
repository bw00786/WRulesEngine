# WRulesEngine
A comprehensive implementation of a rule-based system using FastAPI, SQLAlchemy, and an external LLM (Language Model) service. This system handles business rules, validates them, evaluates facts against these rules, and detects/resolves conflicts between rules.

## Key Components

### FastAPI Application
- Built using FastAPI for high-performance API development with Python 3.7+
- Includes endpoints for rule management, validation, evaluation, and conflict resolution

### Database Models (SQLAlchemy)
- `RuleModel`: Stores business rules
- `UploadReportModel`: Stores reports from rule uploads
- `ConflictModel`: Stores detected rule conflicts

### API Models (Pydantic)
- Models for request/response validation and serialization
- Includes `Rule`, `EnhancedRule`, `Fact`, `RuleValidationResult`, `RuleConflict`, and more

### LLM Integration
- External LLM service integration for rule validation
- Extraction of conditions/actions from natural language
- Complex conflict resolution assistance

### Rule Evaluation
- Evaluation of facts against stored rules
- Support for traditional and LLM-based evaluation methods

### Conflict Management
- Detection of various conflict types (contradictory, redundant, subsumption, etc.)
- Multiple conflict resolution strategies

### Excel Integration
- Upload rules from Excel files containing natural language text
- Automatic extraction of conditions and actions using LLM

### Monitoring
- Prometheus metrics for monitoring HTTP requests and latency

## Key Endpoints

### Rule Management
- `POST /rules/upload/`: Upload rules from Excel file
- `POST /rules/`: Add a new rule with optional LLM validation
- `GET /rules/`: Retrieve all rules

### Rule Validation
- `POST /rules/validate/`: Validate rules using LLM

### Fact Evaluation
- `POST /evaluate/`: Evaluate facts against rules
- `POST /evaluate/with-resolution/`: Evaluate with conflict resolution

### Conflict Management
- `POST /rules/detect-conflicts/`: Detect potential conflicts
- `GET /rules/conflicts/`: Get detected rule conflicts
- `POST /rules/resolve-conflict/{conflict_id}`: Mark conflict as resolved

### Metrics
- `GET /metrics`: Expose Prometheus metrics

## Running the Application

The application can be run using Uvicorn:

```bash
uvicorn app:app --host 0.0.0.0 --port 8000 --workers 1
```

## Deployment

This application can be deployed to Kubernetes. See the `kubernetes/` directory for deployment files:
- `deployment.yaml`: Defines the application deployment
- `service.yaml`: Exposes the application as a service
- `configmap.yaml`: Contains configuration parameters
- `hpa.yaml`: Horizontal Pod Autoscaler for scaling

## Error Handling

The system includes comprehensive error handling and logging. Errors are logged using the Python logging module, and appropriate HTTP status codes are returned for different types of errors.
