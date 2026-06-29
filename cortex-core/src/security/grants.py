"""
Permission grant store — tracks which system-level permissions
have been granted, for what purpose, and by which capability.
"""
import json
import os
import time
from pathlib import Path
from typing import Optional


GRANT_DEFINITIONS = [
    {
        "name": "screen_recording",
        "label": "Screen Recording",
        "group": "system",
        "description": "Take screenshots and describe what's on screen",
        "purpose": "Computer control needs to capture your screen to see what's visible",
        "required_by": ["Computer Control", "Computer Agent"],
    },
    {
        "name": "accessibility",
        "label": "Accessibility (System Events)",
        "group": "system",
        "description": "Move mouse, click, type, press keys",
        "purpose": "Computer control needs to control your mouse and keyboard to interact with apps",
        "required_by": ["Computer Control", "Video Editing"],
    },
    {
        "name": "file_system",
        "label": "File System Access",
        "group": "files",
        "description": "Read and write files on your computer",
        "purpose": "Video editing, script execution, and file operations need file access",
        "required_by": ["Video Editing", "Script Execution", "MCP Filesystem"],
    },
    {
        "name": "automation",
        "label": "App Automation",
        "group": "system",
        "description": "Launch and control other applications via AppleScript",
        "purpose": "Automating apps like DaVinci Resolve, Premiere, CapCut requires automation control",
        "required_by": ["Video Editing", "Computer Control"],
    },
    {
        "name": "script_execution",
        "label": "Script Execution",
        "group": "system",
        "description": "Run arbitrary bash/applescript commands",
        "purpose": "Some complex automations require executing scripts directly",
        "required_by": ["Computer Control", "Automation"],
    },
    {
        "name": "video_editing",
        "label": "Video Editing",
        "group": "creative",
        "description": "Control DaVinci Resolve, Premiere Pro, CapCut",
        "purpose": "Video editor agents need to control video editing software",
        "required_by": ["Video Editing Agent"],
    },
    {
        "name": "photo_editing",
        "label": "Photo Editing",
        "group": "creative",
        "description": "Control photo editing software (Photoshop, etc.)",
        "purpose": "Future photo editing capabilities",
        "required_by": [],
    },
    {
        "name": "sound_editing",
        "label": "Sound Editing",
        "group": "creative",
        "description": "Control audio editing software (Audacity, etc.)",
        "purpose": "Future audio editing capabilities",
        "required_by": [],
    },
    {
        "name": "network_access",
        "label": "Network API Access",
        "group": "network",
        "description": "Connect to cloud models (OpenAI, Gemini) and external APIs",
        "purpose": "Premium cloud models and MCP servers need network access",
        "required_by": ["Cloud Models", "MCP Connectors"],
    },
]

GROUP_LABELS = {
    "system": "System Permissions",
    "creative": "Creative Suite",
    "files": "File Access",
    "network": "Network & APIs",
}


class GrantStore:
    def __init__(self, path: Optional[str] = None):
        if path is None:
            path = str(Path(__file__).resolve().parent.parent.parent / "grants.json")
        self.path = path
        self._grants: dict = {}
        self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path) as f:
                    self._grants = json.load(f)
            except Exception:
                self._grants = {}
        for g in GRANT_DEFINITIONS:
            if g["name"] not in self._grants:
                self._grants[g["name"]] = {
                    "granted": False,
                    "granted_at": None,
                    "purpose": g["purpose"],
                }

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self._grants, f, indent=2)

    def all(self) -> list[dict]:
        result = []
        for g in GRANT_DEFINITIONS:
            state = self._grants.get(g["name"], {})
            result.append({
                **g,
                "granted": state.get("granted", False),
                "granted_at": state.get("granted_at"),
                "group_label": GROUP_LABELS.get(g["group"], g["group"]),
            })
        return result

    def get(self, name: str) -> Optional[dict]:
        for g in GRANT_DEFINITIONS:
            if g["name"] == name:
                state = self._grants.get(name, {})
                return {
                    **g,
                    "granted": state.get("granted", False),
                    "granted_at": state.get("granted_at"),
                    "group_label": GROUP_LABELS.get(g["group"], g["group"]),
                }
        return None

    def grant(self, name: str, grant: bool = True) -> bool:
        if name not in self._grants:
            return False
        self._grants[name]["granted"] = grant
        self._grants[name]["granted_at"] = int(time.time()) if grant else None
        self._save()
        return True

    def revoke(self, name: str) -> bool:
        return self.grant(name, False)

    def grant_group(self, group: str, grant: bool = True) -> int:
        count = 0
        for g in GRANT_DEFINITIONS:
            if g["group"] == group:
                if self.grant(g["name"], grant):
                    count += 1
        return count

    def revoke_group(self, group: str) -> int:
        return self.grant_group(group, False)

    def grant_all(self, grant: bool = True) -> int:
        count = 0
        for g in GRANT_DEFINITIONS:
            if self.grant(g["name"], grant):
                count += 1
        return count

    def revoke_all(self) -> int:
        return self.grant_all(False)

    @property
    def groups(self) -> list[dict]:
        seen = []
        for g in GRANT_DEFINITIONS:
            if g["group"] not in [s["name"] for s in seen]:
                seen.append({
                    "name": g["group"],
                    "label": GROUP_LABELS.get(g["group"], g["group"]),
                })
        return seen

    def is_granted(self, name: str) -> bool:
        state = self._grants.get(name, {})
        return state.get("granted", False)

    def check(self, name: str) -> bool:
        granted = self.is_granted(name)
        if not granted:
            return False
        return True
