"""
Design API Router

Provides endpoints for BPMN and Form generation using real MCP services.
Routes requests to BPMN-MCP and FORM-MCP services.
"""

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import asyncio
import time
from src.mcp.registry import MCPRegistry

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


async def get_org_context(mcp_registry: Optional[MCPRegistry] = None) -> Dict[str, Any]:
    """
    Get organizational context from Membership MCP service.

    Fetches real organizational structure (departments, roles, members) from Membership service.
    Falls back to mock data if Membership MCP is not available.

    Args:
        mcp_registry: Optional MCPRegistry instance. If not provided, uses mock data.

    Returns:
        Dictionary with departments, roles, and members
    """
    # Mock fallback data - used when Membership MCP is not available
    mock_org_context = {
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

    if not mcp_registry:
        logger.debug("No MCP registry provided, using mock org context")
        return mock_org_context

    try:
        # Try to get real org data from Membership MCP
        org_context = {"departments": [], "roles": [], "members": []}

        # Get organizations (departments)
        orgs_result = await mcp_registry.execute_command("membership", "list_orgs", limit=100)
        if orgs_result.success:
            orgs_data = orgs_result.data.get("data", [])
            org_context["departments"] = [
                {"id": org.get("id"), "name": org.get("name"), "type": org.get("type")}
                for org in orgs_data
            ]
            logger.debug(f"Fetched {len(org_context['departments'])} departments from Membership")

        # Get roles
        roles_result = await mcp_registry.execute_command("membership", "list_roles", limit=100)
        if roles_result.success:
            roles_data = roles_result.data.get("roles", [])
            org_context["roles"] = [
                {"id": role.get("id"), "name": role.get("name")}
                for role in roles_data
            ]
            logger.debug(f"Fetched {len(org_context['roles'])} roles from Membership")

        # Get members
        members_result = await mcp_registry.execute_command("membership", "list_members", limit=100)
        if members_result.success:
            members_data = members_result.data.get("members", [])
            org_context["members"] = [
                {"id": member.get("id"), "name": member.get("username"), "email": member.get("email")}
                for member in members_data
            ]
            logger.debug(f"Fetched {len(org_context['members'])} members from Membership")

        return org_context

    except Exception as e:
        logger.warning(f"Failed to fetch org context from Membership MCP: {e}, using mock data")
        return mock_org_context


def normalize_form_definition(form_def: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize form definition to use 'controls' property (BPM standard).
    Converts 'fields' to 'controls' and normalizes field properties.
    """
    if 'fields' in form_def and 'controls' not in form_def:
        # Convert fields to controls and normalize field structure
        fields = form_def.pop('fields', [])
        controls = []

        for i, field in enumerate(fields):
            # Normalize field properties to FormControl format
            control = {
                'id': field.get('field_id', f"control_{i}"),
                'type': field.get('field_type', 'text'),
                'label': field.get('field_label', field.get('field_id', f'Field {i+1}')),
                'props': {
                    'placeholder': field.get('placeholder', ''),
                    'required': field.get('required', False),
                    'validation': field.get('validation', {}),
                    'options': field.get('options', []),
                },
                'width': '100%',
            }
            controls.append(control)

        form_def['controls'] = controls

    # Ensure required fields
    if 'formId' not in form_def:
        form_def['formId'] = f"form_{int(time.time() * 1000)}"
    if 'version' not in form_def:
        form_def['version'] = "1.0.0"
    if 'title' not in form_def:
        form_def['title'] = form_def.get('form_name', 'Untitled Form')
    if 'formType' not in form_def:
        form_def['formType'] = form_def.get('form_type', 'task_bound')

    # Remove non-standard fields
    form_def.pop('form_name', None)
    form_def.pop('form_type', None)
    form_def.pop('workflow_config', None)

    return form_def


def ensure_bpmn_diagram_interchange(bpmn_xml: str) -> str:
    """
    Ensure BPMN XML has a BPMNDiagram element for rendering.
    If missing, generate one with calculated element positions.
    """
    # Already has diagram, return as-is
    if '<bpmndi:BPMNDiagram' in bpmn_xml:
        return bpmn_xml

    try:
        import re

        # Ensure all namespaces are declared first
        if 'xmlns:bpmndi' not in bpmn_xml:
            bpmn_xml = re.sub(
                r'<bpmn:definitions\s+',
                '<bpmn:definitions xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI" '
                'xmlns:dc="http://www.omg.org/spec/DD/20100524/DC" '
                'xmlns:di="http://www.omg.org/spec/DD/20100524/DI" ',
                bpmn_xml,
                count=1
            )

        # Extract process id
        match = re.search(r'<bpmn:process\s+id="([^"]+)"', bpmn_xml)
        if not match:
            return bpmn_xml
        process_id = match.group(1)

        # Find all element ids for positioning
        elements = []
        for elem_match in re.finditer(r'<bpmn:(startEvent|endEvent|userTask|task)\s+id="([^"]+)"', bpmn_xml):
            elem_type, elem_id = elem_match.groups()
            elements.append((elem_type, elem_id))

        if not elements:
            return bpmn_xml

        # Calculate positions
        positions = {}
        x, y, x_step = 100, 100, 180

        for idx, (elem_type, elem_id) in enumerate(elements):
            if elem_type == 'startEvent':
                positions[elem_id] = (x, y, 36, 36)
            elif elem_type == 'endEvent':
                positions[elem_id] = (x + x_step * (len(elements) + 1), y, 36, 36)
            else:  # task
                positions[elem_id] = (x + x_step * (idx + 1), y, 100, 80)

        # Build diagram section
        shapes = []
        for elem_id, (px, py, pw, ph) in positions.items():
            shapes.append(
                f'    <bpmndi:BPMNShape id="{elem_id}_di" bpmnElement="{elem_id}">\n'
                f'      <dc:Bounds x="{px}" y="{py}" width="{pw}" height="{ph}"/>\n'
                f'    </bpmndi:BPMNShape>'
            )

        edges = []
        for flow_match in re.finditer(
            r'<bpmn:sequenceFlow\s+id="([^"]+)"\s+sourceRef="([^"]+)"\s+targetRef="([^"]+)"',
            bpmn_xml
        ):
            flow_id, src_id, tgt_id = flow_match.groups()
            if src_id in positions and tgt_id in positions:
                sx, sy, sw, sh = positions[src_id]
                tx, ty, tw, th = positions[tgt_id]
                sc_x, sc_y = int(sx + sw / 2), int(sy + sh / 2)
                tc_x, tc_y = int(tx + tw / 2), int(ty + th / 2)

                edges.append(
                    f'    <bpmndi:BPMNEdge id="{flow_id}_di" bpmnElement="{flow_id}">\n'
                    f'      <di:waypoint x="{sc_x}" y="{sc_y}"/>\n'
                    f'      <di:waypoint x="{tc_x}" y="{tc_y}"/>\n'
                    f'    </bpmndi:BPMNEdge>'
                )

        diagram = (
            f'  <bpmndi:BPMNDiagram id="BPMNDiagram_1">\n'
            f'    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="{process_id}">\n'
            + '\n'.join(shapes + edges) +
            '\n    </bpmndi:BPMNPlane>\n'
            f'  </bpmndi:BPMNDiagram>'
        )

        # Insert before closing definitions tag
        bpmn_xml = bpmn_xml.replace('</bpmn:definitions>', f'{diagram}\n</bpmn:definitions>')

        return bpmn_xml

    except Exception as e:
        logger.warning(f"Failed to add BPMN diagram: {e}")
        return bpmn_xml


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
async def generate_content(request: GenerateRequest, http_request: Request) -> GenerateResponse:
    """
    Generate BPMN workflow or Form based on natural language prompt.

    Routes to appropriate MCP service:
    - BPMN-MCP for workflow/process generation
    - FORM-MCP for form generation
    """
    try:
        prompt = request.prompt
        generation_type = detect_generation_type(prompt)

        # Get MCP registry from app context
        mcp_registry = getattr(http_request.app, "mcp_registry", None)
        org_context = await get_org_context(mcp_registry)

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

            # Normalize form definition to use 'controls' property (BPM standard)
            form_def = normalize_form_definition(form_def)

            # Get field count from normalized form
            field_count = len(form_def.get('controls', []))

            return GenerateResponse(
                message=f"I've generated a form with {field_count} fields based on your requirements.",
                generatedContent={
                    "type": "form",
                    "formDefinition": form_def,
                    "preview": f"Form with {field_count} fields",
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

            # Ensure BPMN has diagram interchange information for rendering
            bpmn_xml = ensure_bpmn_diagram_interchange(bpmn_xml)

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


@router.get("/org-structure")
async def get_org_structure(http_request: Request) -> Dict[str, Any]:
    """
    Get organizational structure from Membership MCP.

    Returns departments, roles, and members for use in form/workflow generation.
    This endpoint is called by the frontend to populate selection modals.

    Returns:
        Dictionary with departments, roles, and members
    """
    try:
        mcp_registry = getattr(http_request.app, "mcp_registry", None)
        org_context = await get_org_context(mcp_registry)

        return {
            "success": True,
            "data": org_context
        }

    except Exception as e:
        logger.error(f"Error fetching org structure: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to fetch organization structure: {str(e)}")
