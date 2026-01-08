from typing import List, Optional, Any, Dict
from pydantic import BaseModel, Field, model_validator
from datetime import datetime
from enum import Enum
from bson import ObjectId

class RiskLevel(str, Enum):
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"

class ParameterDefinition(BaseModel):
    name: str
    in_: str = Field(..., alias="in")
    description: str
    required: bool = False
    schema_: Dict[str, Any] = Field(..., alias="schema")

class Command(BaseModel):
    id: Optional[str] = Field(None, alias="_id")
    command_set_id: str
    tenant_id: int
    command: str
    summary: str
    description: Optional[str] = None
    tags: List[str] = []
    parameters: Any = None  # Changed to Any to accept dict or list
    examples: List[str] = []
    risk_level: RiskLevel = Field(default=RiskLevel.NORMAL, alias="riskLevel")

    # Response schema describes how the API returns data
    # Examples:
    # - {"type": "object", "root": "body"} - Direct response body
    # - {"type": "wrapped", "wrapper": "data", "items": "array"} - Wrapped in 'data' array
    # - {"type": "wrapped", "wrapper": "data", "items": "object"} - Wrapped in 'data' object
    response_schema: Optional[Dict[str, Any]] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    @model_validator(mode='before')
    @classmethod
    def convert_objectid(cls, data: Any) -> Any:
        """Convert MongoDB ObjectId to string before validation"""
        if isinstance(data, dict):
            if '_id' in data and isinstance(data['_id'], ObjectId):
                data['_id'] = str(data['_id'])
        return data

    class Config:
        populate_by_name = True
        arbitrary_types_allowed = True
