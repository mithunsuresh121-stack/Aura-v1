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
from computer.terminal import TerminalAgent
from security.grants import GrantStore
from build.engine import BuildEngine

logger = logging.getLogger("cortex.capabilities")

router = APIRouter(prefix="/v1")

# Global references set by main server
registry: Optional[ModelRegistry] = None
mcp_manager: Optional[MCPManager] = None
orchestrator: Optional[Orchestrator] = None
computer: Optional[ComputerAgent] = None
video_editor: Optional[VideoEditAgent] = None
terminal: Optional[TerminalAgent] = None
grant_store: Optional[GrantStore] = None
build_engine: Optional[BuildEngine] = None


def init(
    model_registry: Optional[ModelRegistry] = None,
    mcp: Optional[MCPManager] = None,
    orch: Optional[Orchestrator] = None,
    comp: Optional[ComputerAgent] = None,
    video: Optional[VideoEditAgent] = None,
    grants: Optional[GrantStore] = None,
    build: Optional[BuildEngine] = None,
    term: Optional[TerminalAgent] = None,
):
    global registry, mcp_manager, orchestrator, computer, video_editor, grant_store, build_engine, terminal
    registry = model_registry
    mcp_manager = mcp
    orchestrator = orch
    computer = comp
    video_editor = video
    grant_store = grants
    build_engine = build
    if term:
        terminal = term


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
    path = await computer.screenshot_async()
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


# --- Terminal ---

class TerminalCreateRequest(BaseModel):
    shell: str = "bash"
    rows: int = 24
    cols: int = 80


class TerminalExecRequest(BaseModel):
    command: str
    timeout: float = 30.0


class TerminalResizeRequest(BaseModel):
    rows: int
    cols: int


@router.post("/terminal/create")
async def terminal_create(req: TerminalCreateRequest):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    session = terminal.create_session(shell=req.shell, rows=req.rows, cols=req.cols)
    return {
        "session_id": session.id,
        "shell": session.shell,
    }


@router.post("/terminal/exec")
async def terminal_exec(session_id: str, req: TerminalExecRequest):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    result = await terminal.execute(session_id, req.command, req.timeout)
    if "error" in result:
        raise HTTPException(404, result["error"])
    return result


@router.post("/terminal/{session_id}/read")
async def terminal_read(session_id: str, timeout: float = 0.5):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    session = terminal.get_session(session_id)
    if not session or not session.running():
        raise HTTPException(404, "Session not found or closed")
    data = session.read(timeout=timeout)
    return {"output": data.decode("utf-8", errors="replace"), "bytes": len(data)}


@router.post("/terminal/{session_id}/write")
async def terminal_write(session_id: str, data: str):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    session = terminal.get_session(session_id)
    if not session or not session.running():
        raise HTTPException(404, "Session not found or closed")
    session.write(data)
    return {"written": len(data)}


@router.post("/terminal/{session_id}/resize")
async def terminal_resize(session_id: str, req: TerminalResizeRequest):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    session = terminal.get_session(session_id)
    if not session or not session.running():
        raise HTTPException(404, "Session not found or closed")
    session.resize(req.rows, req.cols)
    return {"rows": req.rows, "cols": req.cols}


@router.post("/terminal/{session_id}/close")
async def terminal_close(session_id: str):
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    ok = terminal.close_session(session_id)
    if not ok:
        raise HTTPException(404, "Session not found")
    return {"closed": session_id}


@router.get("/terminal/sessions")
async def terminal_sessions():
    if terminal is None:
        raise HTTPException(503, "Terminal not available")
    return {"sessions": terminal.list_sessions()}


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


# --- Permission Grants ---

class GrantRequest(BaseModel):
    name: str

class GrantGroupRequest(BaseModel):
    group: str


@router.get("/permissions")
async def list_permissions():
    if grant_store is None:
        return {"permissions": [], "groups": []}
    return {
        "permissions": grant_store.all(),
        "groups": grant_store.groups,
    }


@router.post("/permissions/grant")
async def grant_permission(req: GrantRequest):
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    ok = grant_store.grant(req.name)
    if not ok:
        raise HTTPException(404, f"Permission '{req.name}' not found")
    return {"status": "granted", "name": req.name}


@router.post("/permissions/revoke")
async def revoke_permission(req: GrantRequest):
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    ok = grant_store.revoke(req.name)
    if not ok:
        raise HTTPException(404, f"Permission '{req.name}' not found")
    return {"status": "revoked", "name": req.name}


@router.post("/permissions/grant-group")
async def grant_group(req: GrantGroupRequest):
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    count = grant_store.grant_group(req.group)
    return {"status": "granted", "group": req.group, "count": count}


@router.post("/permissions/revoke-group")
async def revoke_group(req: GrantGroupRequest):
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    count = grant_store.revoke_group(req.group)
    return {"status": "revoked", "group": req.group, "count": count}


@router.post("/permissions/grant-all")
async def grant_all():
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    count = grant_store.grant_all()
    return {"status": "granted_all", "count": count}


@router.post("/permissions/revoke-all")
async def revoke_all():
    if grant_store is None:
        raise HTTPException(503, "Grant store not available")
    count = grant_store.revoke_all()
    return {"status": "revoked_all", "count": count}


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


# --- Build / Code Generation ---

class BuildPlanRequest(BaseModel):
    task: str

class BuildExecuteRequest(BaseModel):
    step_index: int = 0

class WorkspaceRequest(BaseModel):
    path: str


@router.post("/build/plan")
async def build_plan(req: BuildPlanRequest):
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    plan = build_engine.plan(req.task)
    return plan.to_dict()


@router.post("/build/execute")
async def build_execute(req: BuildExecuteRequest):
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    change = build_engine.execute_step(req.step_index)
    if change is None:
        raise HTTPException(400, "Invalid step index or no plan set")
    return change.to_dict()


@router.post("/build/execute-all")
async def build_execute_all():
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    changes = build_engine.execute_all()
    return {"count": len(changes), "changes": [c.to_dict() for c in changes]}


@router.post("/build/undo")
async def build_undo():
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    ok = build_engine.undo_last()
    return {"status": "undone" if ok else "nothing_to_undo"}


@router.get("/build/history")
async def build_history():
    if build_engine is None:
        return {"changes": []}
    return {"changes": build_engine.history()}


@router.get("/build/plan")
async def build_get_plan():
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    plan = build_engine.current_plan
    if plan is None:
        return {"task": "", "steps": []}
    return plan.to_dict()


@router.post("/build/diff")
async def build_diff(req: WorkspaceRequest):
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    d = build_engine.diff(req.path)
    if d is None:
        return {"diff": "", "path": req.path}
    return {"diff": d, "path": req.path}


@router.post("/build/workspace")
async def build_set_workspace(req: WorkspaceRequest):
    if build_engine is None:
        raise HTTPException(503, "Build engine not available")
    build_engine.set_workspace(req.path)
    return {"status": "ok", "workspace": str(build_engine.workspace)}


# --- Agent State ---

@router.get("/capabilities")
async def capabilities():
    perms = grant_store.all() if grant_store else []
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
        "permissions": {
            "total": len(perms),
            "granted": sum(1 for p in perms if p["granted"]),
            "groups": grant_store.groups if grant_store else [],
        },
        "terminal": {
            "enabled": terminal is not None,
            "sessions": len(terminal.list_sessions()) if terminal else 0,
        },
        "build": {
            "enabled": build_engine is not None,
            "changes": len(build_engine.history()) if build_engine else 0,
            "workspace": str(build_engine.workspace) if build_engine else "",
        },
    }
