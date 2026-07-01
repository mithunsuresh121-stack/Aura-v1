"""
VideoEditAgent — high-level video editing agent.
Takes natural language descriptions of edits and executes them
using the appropriate video editor automation.
"""
import os
import time
import logging
from typing import Optional
from .base import VideoEditor
from .resolve import DaVinciResolve
from .premiere import PremierePro
from .capcut import CapCut

logger = logging.getLogger("cortex.software")


class VideoEditAgent:
    def __init__(self):
        self._editors: dict[str, VideoEditor] = {}
        self._detect_editors()

    def _detect_editors(self):
        for editor_cls in [DaVinciResolve, PremierePro, CapCut]:
            try:
                editor = editor_cls()
                if editor.is_installed():
                    self._editors[editor.name.lower()] = editor
                    logger.info(f"Detected: {editor.name}")
            except Exception as e:
                logger.debug(f"Editor detection failed: {e}")

    @property
    def available_editors(self) -> list[str]:
        return list(self._editors.keys())

    def get_editor(self, name: str) -> Optional[VideoEditor]:
        for key, editor in self._editors.items():
            if name.lower() in key:
                return editor
        return None

    async def execute_edit(
        self,
        description: str,
        editor_name: str = "",
        media_files: Optional[list[str]] = None,
        output_path: str = "",
    ) -> dict:
        editor = self.get_editor(editor_name) if editor_name else next(iter(self._editors.values()), None)
        if not editor:
            return {"status": "error", "message": f"No editor available. Detected: {self.available_editors}"}

        actions_taken = []
        errors = []

        try:
            if not editor.is_running():
                if not editor.launch():
                    return {"status": "error", "message": f"Failed to launch {editor.name}"}
                actions_taken.append(f"Launched {editor.name}")
            else:
                editor.activate()
                actions_taken.append(f"Activated {editor.name}")

            editor.new_project("Aura Auto Edit")
            actions_taken.append("Created new project")

            if media_files:
                existing = [f for f in media_files if os.path.exists(f)]
                if existing:
                    editor.import_media(existing)
                    actions_taken.append(f"Imported {len(existing)} media files")

            editor.set_export_preset()
            actions_taken.append("Set export preset")

            if output_path:
                editor.export(output_path)
                actions_taken.append(f"Export started to: {output_path}")
                editor.wait_for_export()

            editor.save_project()
            actions_taken.append("Project saved")

        except Exception as e:
            logger.error(f"Edit execution failed: {e}")
            errors.append(str(e))

        return {
            "status": "completed" if not errors else "partial",
            "editor": editor.name,
            "output": output_path if output_path else "(not specified)",
            "actions": actions_taken,
            "errors": errors if errors else None,
        }
