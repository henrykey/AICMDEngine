"""
Design API Router

Provides endpoints for BPMN and Form generation using real MCP services.
Routes requests to BPMN-MCP and FORM-MCP services.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import asyncio

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/design", tags=["design"])


class GenerateRequest(BaseModel):
    """Request to generate BPMN or Form"""
    prompt: str
    context: Optional[Dict[str, Any]] = None


class GenerateResponse(BaseModel):
    """Response from generation services"""
    message: str
    generatedContent: Optional[Dict[str, Any]] = None


def get_org_context() -> Dict[str, Any]:
    """Get organizational context for MCP services"""
    # Default org context - in production this would come from Membership service
    return {
        "departments": [
            {"id": "dept_001", "name": "Finance"},
            {"id": "dept_002", "name": "HR"},
            {"id": "dept_003", "name": "Engineering"},
        ],
        "roles": [
            {"id": "role_001", "name": "employee"},
            {"id": "role_002", "name": "manager"},
            {"id": "role_003", "name": "approver"},
            {"id": "role_004", "name": "finance_approver"},
        ],
        "members": [
            {"id": "user_001", "name": "Alice", "roles": ["employee"]},
            {"id": "user_002", "name": "Bob", "roles": ["manager"]},
            {"id": "user_003", "name": "Charlie", "roles": ["approver"]},
        ],
    }


def detect_generation_type(prompt: str) -> str:
    """Detect whether to generate BPMN or Form from prompt"""
    lowerPrompt = prompt.lower()

    # Check for form keywords
    if 'form' in lowerPrompt or '表单' in lowerPrompt:
        return 'form'

    # Check for process/workflow keywords
    if any(kw in lowerPrompt for kw in ['process', 'workflow', 'approval', 'submit', '流程', '审批']):
        return 'bpmn'

    # Default to bpmn
    return 'bpmn'


@router.post("/generate", response_model=GenerateResponse)
async def generate_content(request: GenerateRequest) -> GenerateResponse:
    """
    Generate BPMN workflow or Form based on natural language prompt.

    Routes to appropriate MCP service:
    - BPMN-MCP for workflow/process generation
    - FORM-MCP for form generation
    """
    try:
        prompt = request.prompt
        generation_type = detect_generation_type(prompt)
        org_context = get_org_context()

        logger.info(f"Generating {generation_type} from prompt: {prompt}")

        if generation_type == 'form':
            # Import here to avoid circular imports
            from src.mcp_servers.form_mcp import generate_form

            # Call FORM-MCP service
            result = await generate_form(
                tenant_id="default",
                form_name="Generated Form",
                form_type="task_bound",
                description=prompt,
                org_context={"org_context": org_context},
                use_real_llm=True  # Use real LLM for actual generation
            )

            logger.info(f"Form generation result: {result}")

            if result.get('error'):
                raise HTTPException(status_code=400, detail=result['error'])

            form_def = result.get('form_definition', {})

            return GenerateResponse(
                message=f"I've generated a form with {len(form_def.get('controls', []))} fields based on your requirements.",
                generatedContent={
                    "type": "form",
                    "formDefinition": form_def,
                    "preview": f"Form with {len(form_def.get('controls', []))} fields",
                }
            )

        else:  # bpmn
            # Import here to avoid circular imports
            from src.mcp_servers.bpmn_mcp import generate_process

            # Call BPMN-MCP service
            result = await generate_process(
                tenant_id="default",
                description=prompt,
                org_context=org_context,
                use_real_llm=True  # Use real LLM for actual generation
            )

            logger.info(f"BPMN generation result: {result}")

            if not result.get('valid', False):
                error_msg = '\n'.join(result.get('errors', ['Unknown error']))
                raise HTTPException(status_code=400, detail=f"BPMN generation failed: {error_msg}")

            bpmn_xml = result.get('bpmn_xml', '')
            confidence = result.get('confidence_score', 0)

            return GenerateResponse(
                message=f"I've generated a BPMN workflow based on your requirements (confidence: {confidence:.1%}).",
                generatedContent={
                    "type": "bpmn",
                    "bpmnXml": bpmn_xml,
                    "preview": "Generated workflow process",
                    "metadata": {
                        "confidence": confidence,
                        "valid": result.get('valid', False),
                    }
                }
            )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in generate_content: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Generation failed: {str(e)}")
