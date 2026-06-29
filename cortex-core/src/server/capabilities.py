"""
Capabilities router — exposes model switching, MCP tools, orchestration,
and computer control endpoints.
Mounted under /v1/ in the main server.
"""
import json
import logging
import time
import tempfile
import os
from typing import Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from models.registry import ModelRegistry
from mcp.manager import MCPManager
from orchestration.orchestrator import Orchestrator
from orchestration.sub_agent import SubAgent
from computer.automation import ComputerAgent
from computer.software import VideoEditAgent

logger = logging.getLogger("cortex.capabilities")

router = APIRouter(prefix="/v1")

# Global references set by main server
registry: Optional[ModelRegistry] = None
mcp_manager: Optional[MCPManager] = None
orchestrator: Optional[Orchestrator] = None
computer: Optional[ComputerAgent] = None
video_editor: Optional[VideoEditAgent] = None


def init(
    model_registry: Optional[ModelRegistry] = None,
    mcp: Optional[MCPManager] = None,
    orch: Optional[Orchestrator] = None,
    comp: Optional[ComputerAgent] = None,
    video: Optional[VideoEditAgent] = None,
):
    global registry, mcp_manager, orchestrator, computer, video_editor
    registry = model_registry
    mcp_manager = mcp
    orchestrator = orch
    computer = comp
    video_editor = video


# --- Schemas ---

class ModelSelectRequest(BaseModel):
    model: str


class MCPCallRequest(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)


class OrchestrateRequest(BaseModel):
    task: str
    auto_delegate: bool = True


class ClickRequest(BaseModel):
    x: int
    y: int
    button: str = "left"


class TypeRequest(BaseModel):
    text: str


class PressRequest(BaseModel):
    key: str


class HotkeyRequest(BaseModel):
    keys: list[str]


class ScrollRequest(BaseModel):
    clicks: int


class LookRequest(BaseModel):
    detail: str = "brief"


class ExecutePlanRequest(BaseModel):
    steps: list[dict]


class OpenAppRequest(BaseModel):
    name: str


class RunScriptRequest(BaseModel):
    script: str
    interpreter: str = "bash"


class RegisterSubAgentRequest(BaseModel):
    agent_id: str
    role: str
    system_prompt: Optional[str] = None
    model_name: Optional[str] = None


# --- Model Switching ---

@router.get("/models")
async def list_models():
    if registry is None:
        return {"models": ["local"], "default": "local"}
    return {"models": registry.available, "default": registry.default}


@router.post("/models/select")
async def select_model(req: ModelSelectRequest):
    if registry is None:
        raise HTTPException(503, "Model registry not available")
    try:
        registry.default = req.model
        return {"status": "ok", "model": req.model}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/models/health")
async def model_health():
    if registry is None:
        return {"local": {"status": "ok"}}
    return await registry.health_all()


@router.get("/models/status")
async def model_status():
    if registry is None:
        return {"active": "local"}
    backend = registry.get()
    return {
        "active": registry.default,
        "available": registry.available,
        "model": backend.name,
    }


# --- MCP Tools ---

@router.get("/mcp/tools")
async def mcp_tools():
    if mcp_manager is None:
        return {"tools": []}
    tools = await mcp_manager.all_tools
    return {
        "tools": [
            {"name": t.name, "server": t.server_name, "description": t.description}
            for t in tools
        ]
    }


@router.post("/mcp/call")
async def mcp_call(req: MCPCallRequest):
    if mcp_manager is None:
        raise HTTPException(503, "MCP not available")
    result = await mcp_manager.call_tool_by_full_name(req.tool, req.arguments)
    return {"tool": req.tool, "result": result}


# --- Orchestration ---

@router.get("/orchestrate/agents")
async def list_sub_agents():
    if orchestrator is None:
        return {"agents": []}
    return {
        "agents": [
            {"id": aid, "role": a.role}
            for aid, a in orchestrator._agents.items()
        ]
    }


@router.post("/orchestrate/register-agent")
async def register_sub_agent(req: RegisterSubAgentRequest):
    global orchestrator
    if orchestrator is None or registry is None:
        raise HTTPException(503, "Orchestrator not available")
    model_name = req.model_name or registry.default
    if model_name not in registry.available:
        raise HTTPException(400, f"Model '{model_name}' not available")
    backend = registry.get(model_name)
    agent = SubAgent(
        agent_id=req.agent_id,
        role=req.role,
        model_backend=backend,
        system_prompt=req.system_prompt,
    )
    orchestrator.register_agent(agent)
    return {"status": "registered", "agent_id": req.agent_id, "role": req.role}


@router.post("/orchestrate")
async def orchestrate(req: OrchestrateRequest):
    if orchestrator is None:
        raise HTTPException(503, "Orchestrator not available")
    result = await orchestrator.execute(req.task, auto_delegate=req.auto_delegate)
    return {
        "id": f"orchestrate-{int(time.time())}",
        "task": req.task,
        "result": result,
    }


# --- Computer Control ---

@router.post("/computer/screenshot")
async def computer_screenshot():
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    path = computer.screenshot()
    return {"path": path, "note": "Capture saved to " + path}


@router.post("/computer/look")
async def computer_look(req: LookRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    description = await computer.look(req.detail)
    return {"description": description}


@router.post("/computer/click")
async def computer_click(req: ClickRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.click(req.x, req.y, req.button)
    return {"action": "click", "x": req.x, "y": req.y, "button": req.button}


@router.post("/computer/type")
async def computer_type(req: TypeRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.type_text(req.text)
    return {"action": "type", "length": len(req.text)}


@router.post("/computer/press")
async def computer_press(req: PressRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.press_key(req.key)
    return {"action": "press", "key": req.key}


@router.post("/computer/hotkey")
async def computer_hotkey(req: HotkeyRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.hotkey(*req.keys)
    return {"action": "hotkey", "keys": req.keys}


@router.post("/computer/scroll")
async def computer_scroll(req: ScrollRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.scroll(req.clicks)
    return {"action": "scroll", "clicks": req.clicks}


@router.post("/computer/mouse-position")
async def computer_mouse_position():
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    x, y = computer.get_position()
    return {"x": x, "y": y}


@router.post("/computer/open-app")
async def computer_open_app(req: OpenAppRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    computer.open_app(req.name)
    return {"action": "open_app", "app": req.name}


@router.post("/computer/run-script")
async def computer_run_script(req: RunScriptRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    result = computer.run_script(req.script, req.interpreter)
    return {"output": result}


@router.post("/computer/active-window")
async def computer_active_window():
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    name = computer.get_active_window()
    return {"window": name}


@router.post("/computer/execute-plan")
async def computer_execute_plan(req: ExecutePlanRequest):
    if computer is None:
        raise HTTPException(503, "Computer control not available")
    results = await computer.execute_plan(req.steps)
    return {"steps": len(req.steps), "results": results}


# --- Software / Video Editing ---

class EditRequest(BaseModel):
    description: str
    editor: str = ""
    media_files: list[str] = Field(default_factory=list)
    output_path: str = ""


@router.get("/software/editors")
async def list_editors():
    if video_editor is None:
        return {"editors": []}
    return {"editors": video_editor.available_editors}


@router.post("/software/edit")
async def execute_edit(req: EditRequest):
    if video_editor is None:
        raise HTTPException(503, "Video editor agent not available")
    result = await video_editor.execute_edit(
        description=req.description,
        editor_name=req.editor,
        media_files=req.media_files,
        output_path=req.output_path,
    )
    return result


# --- Agent State ---

@router.get("/capabilities")
async def capabilities():
    return {
        "models": {
            "available": registry.available if registry else ["local"],
            "default": registry.default if registry else "local",
        },
        "mcp": {
            "enabled": mcp_manager is not None,
            "tools": len(await mcp_manager.all_tools) if mcp_manager else 0,
        },
        "orchestration": {
            "enabled": orchestrator is not None,
            "sub_agents": len(orchestrator._agents) if orchestrator else 0,
        },
        "computer_control": {
            "enabled": computer is not None,
            "vision": computer.screen.vision_model is not None if computer else False,
        },
        "video_editing": {
            "enabled": video_editor is not None,
            "editors": video_editor.available_editors if video_editor else [],
        },
    }
