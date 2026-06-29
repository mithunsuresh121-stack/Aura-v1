"""
Build engine — plan and execute code changes with undo support.
"""
import json
import os
import shutil
import time
import logging
from pathlib import Path
from typing import Optional, List

logger = logging.getLogger("aura.build")


class FileChange:
    def __init__(self, file_path: str, action: str, content: str = "", backup: Optional[str] = None):
        self.file_path = file_path
        self.action = action  # create | modify | delete
        self.content = content
        self.backup = backup
        self.timestamp = int(time.time())

    def to_dict(self):
        return {
            "file_path": self.file_path,
            "action": self.action,
            "content_preview": self.content[:200] if self.content else "",
            "backup_exists": self.backup is not None,
            "timestamp": self.timestamp,
        }


class PlanStep:
    def __init__(self, description: str, file_path: str, action: str, content: str = ""):
        self.description = description
        self.file_path = file_path
        self.action = action
        self.content = content

    def to_dict(self):
        return {
            "description": self.description,
            "file_path": self.file_path,
            "action": self.action,
            "content": self.content,
        }


class BuildPlan:
    def __init__(self, task: str, steps: List[PlanStep]):
        self.task = task
        self.steps = steps
        self.created_at = int(time.time())

    def to_dict(self):
        return {
            "task": self.task,
            "steps": [s.to_dict() for s in self.steps],
            "created_at": self.created_at,
        }


class BuildEngine:
    def __init__(self, workspace: Optional[str] = None):
        if workspace is None:
            workspace = os.getcwd()
        self.workspace = Path(workspace).resolve()
        self.change_history: List[FileChange] = []
        self._backup_dir = self.workspace / ".aura-build-backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        # Track current plan
        self._current_plan: Optional[BuildPlan] = None

    def plan(self, task: str) -> BuildPlan:
        self._current_plan = None
        steps = self._generate_plan(task)
        self._current_plan = BuildPlan(task, steps)
        return self._current_plan

    def _generate_plan(self, task: str) -> List[PlanStep]:
        prompt = f"""Given this task: "{task}"

Create a numbered list of file changes needed. For each change specify:
- what file
- what action (create/modify/delete)
- a short description of the change

Output as JSON array:
[{{"file_path": "path/to/file", "action": "create|modify|delete", "description": "what to do", "content": "full file content or diff"}}]

Only output the JSON array, nothing else."""
        from models.registry import ModelRegistry
        try:
            reg = ModelRegistry()
            backend = reg.get()
            if backend is None:
                return [PlanStep("Create file", "README.md", "create", "# Task\n\n" + task)]
            # Use the model to generate the plan
            result = backend.chat([{"role": "user", "content": prompt}], max_tokens=2048, temperature=0.3)
            text = result.get("content", "") if isinstance(result, dict) else str(result)
            # Try to parse JSON from response
            text = text.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            text = text.strip()
            steps_data = json.loads(text)
            if isinstance(steps_data, list):
                return [
                    PlanStep(s.get("description", s.get("action", "change")), s["file_path"], s.get("action", "modify"), s.get("content", ""))
                    for s in steps_data
                ]
        except Exception as e:
            logger.warning(f"Plan generation failed: {e}")
            pass
        return [PlanStep("Create file", "output.txt", "create", f"Implementation of: {task}")]

    @property
    def current_plan(self) -> Optional[BuildPlan]:
        return self._current_plan

    def execute_step(self, step_index: int) -> Optional[FileChange]:
        if self._current_plan is None or step_index >= len(self._current_plan.steps):
            return None
        step = self._current_plan.steps[step_index]
        file_path = self.workspace / step.file_path

        backup = None
        if step.action == "create":
            parent = file_path.parent
            parent.mkdir(parents=True, exist_ok=True)
            content = step.content
            if file_path.exists():
                backup = self._backup(step.file_path)
            with open(file_path, "w") as f:
                f.write(content)
        elif step.action == "modify":
            if file_path.exists():
                backup = self._backup(step.file_path)
                content = step.content
                with open(file_path, "w") as f:
                    f.write(content)
            else:
                parent = file_path.parent
                parent.mkdir(parents=True, exist_ok=True)
                with open(file_path, "w") as f:
                    f.write(step.content)
        elif step.action == "delete":
            if file_path.exists():
                backup = self._backup(step.file_path)
                file_path.unlink()
        else:
            return None

        change = FileChange(step.file_path, step.action, step.content, backup)
        self.change_history.append(change)
        return change

    def execute_all(self) -> List[FileChange]:
        if self._current_plan is None:
            return []
        results = []
        for i in range(len(self._current_plan.steps)):
            change = self.execute_step(i)
            if change:
                results.append(change)
        return results

    def undo_last(self) -> bool:
        if not self.change_history:
            return False
        change = self.change_history.pop()
        file_path = self.workspace / change.file_path
        if change.backup and os.path.exists(change.backup):
            shutil.copy2(change.backup, file_path)
            os.unlink(change.backup)
            return True
        elif change.action == "create":
            if file_path.exists():
                file_path.unlink()
                return True
        return False

    def _backup(self, relative_path: str) -> str:
        backup_name = relative_path.replace("/", "__").replace("\\", "__")
        backup_path = str(self._backup_dir / f"{backup_name}.{int(time.time())}.bak")
        src = self.workspace / relative_path
        if src.exists():
            shutil.copy2(src, backup_path)
        return backup_path

    def history(self) -> List[dict]:
        return [c.to_dict() for c in self.change_history]

    def set_workspace(self, path: str):
        self.workspace = Path(path).resolve()
        self._backup_dir = self.workspace / ".aura-build-backups"
        self._backup_dir.mkdir(parents=True, exist_ok=True)

    def diff(self, file_path: str) -> Optional[str]:
        change = None
        for c in reversed(self.change_history):
            if c.file_path == file_path:
                change = c
                break
        if change is None:
            return None
        result = f"--- {file_path}\n+++ {file_path} (planned)\n"
        if change.action == "create":
            result += "@@ -0,0 +1,{} @@\n".format(len(change.content.split("\n")))
            for line in change.content.split("\n"):
                result += f"+{line}\n"
        elif change.action == "modify" and change.content:
            lines = change.content.split("\n")
            result += "@@ -1,? +1,{} @@\n".format(len(lines))
            for line in lines:
                result += f" {line}\n"
        elif change.action == "delete":
            result += "@@ -1,? +0,0 @@\n"
            result += "- (file deleted)\n"
        return result
