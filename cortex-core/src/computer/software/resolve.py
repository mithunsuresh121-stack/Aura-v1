"""
DaVinci Resolve automation.
Uses the official DaVinci Resolve Scripting API when available,
falls back to keyboard shortcut + GUI automation.
"""
import os
import sys
import time
import logging
import subprocess
from typing import Optional
from .base import VideoEditor

logger = logging.getLogger("cortex.software.resolve")

RESOLVE_SCRIPT_PATH = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules"


class DaVinciResolve(VideoEditor):
    name = "DaVinci Resolve"

    def __init__(self):
        super().__init__()
        self._resolve = None
        self._project = None
        self._fusion = None
        self._has_script_api = os.path.isdir(RESOLVE_SCRIPT_PATH)

    def _try_init_api(self):
        if not self._has_script_api:
            return False
        try:
            if RESOLVE_SCRIPT_PATH not in sys.path:
                sys.path.insert(0, RESOLVE_SCRIPT_PATH)
            import DaVinciResolveScript as dvr
            self._resolve = dvr.scriptapp("Resolve")
            if self._resolve:
                self._project = self._resolve.GetProjectManager().GetCurrentProject()
                logger.info("DaVinci Resolve scripting API connected")
                return True
        except Exception as e:
            logger.warning(f"DaVinci Resolve scripting API unavailable: {e}")
        return False

    def launch(self) -> bool:
        if self.is_running():
            self._is_open = True
            self._try_init_api()
            return True
        try:
            subprocess.run(["open", "-a", "DaVinci Resolve"], timeout=30)
            time.sleep(15)
            self._is_open = True
            self._try_init_api()
            return True
        except Exception as e:
            logger.error(f"Failed to launch DaVinci Resolve: {e}")
            return False

    def close(self):
        if self._resolve:
            try:
                self._resolve = None
                self._project = None
            except Exception:
                pass
        subprocess.run(["osascript", "-e",
                        'tell application "DaVinci Resolve" to quit'],
                       capture_output=True, timeout=10)
        self._is_open = False

    def new_project(self, name: str) -> bool:
        self.activate()
        time.sleep(1)
        if self._project is not None:
            try:
                pm = self._resolve.GetProjectManager()
                self._project = pm.CreateProject(name)
                return self._project is not None
            except Exception as e:
                logger.warning(f"API new_project failed: {e}")

        self.hotkey("cmd", "n")
        time.sleep(0.5)
        self.type_text(name)
        time.sleep(0.3)
        self.press_key("enter")
        time.sleep(1)
        return True

    def open_project(self, path: str) -> bool:
        self.activate()
        time.sleep(1)
        if self._project is not None:
            try:
                pm = self._resolve.GetProjectManager()
                self._project = pm.LoadProject(os.path.basename(path).replace(".drp", ""))
                return self._project is not None
            except Exception as e:
                logger.warning(f"API open_project failed: {e}")

        self.hotkey("cmd", "o")
        time.sleep(0.5)
        self.type_text(path)
        time.sleep(0.3)
        self.press_key("enter")
        time.sleep(2)
        return True

    def save_project(self, path: str = "") -> bool:
        self.activate()
        time.sleep(0.5)
        if self._project is not None:
            try:
                return self._project.SaveProject()
            except Exception as e:
                logger.warning(f"API save failed: {e}")

        self.hotkey("cmd", "s")
        time.sleep(0.5)
        if path:
            self.hotkey("cmd", "shift", "s")
            time.sleep(0.5)
            self.type_text(path)
            time.sleep(0.3)
            self.press_key("enter")
        time.sleep(1)
        return True

    def import_media(self, file_paths: list[str]) -> bool:
        self.activate()
        time.sleep(1)
        if self._project is not None:
            try:
                media_pool = self._project.GetMediaPool()
                for fp in file_paths:
                    media_pool.ImportMedia([fp])
                logger.info(f"Imported {len(file_paths)} files via API")
                return True
            except Exception as e:
                logger.warning(f"API import_media failed: {e}")

        for fp in file_paths:
            self.hotkey("cmd", "i")
            time.sleep(0.5)
            self.type_text(fp)
            time.sleep(0.3)
            self.press_key("enter")
            time.sleep(1)
        return True

    def add_to_timeline(self, media_name: str, track: int = 0) -> bool:
        self.activate()
        time.sleep(0.5)
        if self._project is not None:
            try:
                media_pool = self._project.GetMediaPool()
                timeline = media_pool.GetCurrentFolder()
                clips = timeline.GetClipList() if timeline else []
                for clip in clips:
                    if media_name.lower() in clip.GetName().lower():
                        media_pool.AppendToTimeline([clip])
                        logger.info(f"Added '{media_name}' to timeline")
                        return True
            except Exception as e:
                logger.warning(f"API add_to_timeline failed: {e}")

        self.hotkey("cmd", "shift", "a")
        time.sleep(0.3)
        self.hotkey("cmd", "down")
        time.sleep(0.3)
        self.press_key("enter")
        time.sleep(1)
        return True

    def set_export_preset(self, preset: str = "H.264 Master") -> bool:
        self.activate()
        time.sleep(0.5)
        if self._project is not None:
            try:
                self._project.LoadRenderPreset(preset)
                logger.info(f"Render preset set: {preset}")
                return True
            except Exception as e:
                logger.warning(f"API set_export_preset failed: {e}")

        self.hotkey("cmd", "m")
        time.sleep(1)
        self.click(400, 300)
        time.sleep(0.5)
        self.type_text(preset)
        time.sleep(0.3)
        self.press_key("enter")
        time.sleep(1)
        return True

    def export(self, output_path: str) -> bool:
        self.activate()
        time.sleep(0.5)
        if self._project is not None:
            try:
                pm = self._resolve.GetProjectManager()
                project = pm.GetCurrentProject()
                project.SetRenderSettings({"TargetDir": os.path.dirname(output_path),
                                           "CustomName": os.path.basename(output_path)})
                project.StartRendering()
                logger.info(f"Export started: {output_path}")
                return True
            except Exception as e:
                logger.warning(f"API export failed: {e}")

        self.hotkey("cmd", "m")
        time.sleep(1)
        self.click(800, 400)
        time.sleep(0.5)
        self.type_text(output_path)
        time.sleep(0.3)
        self.press_key("enter")
        time.sleep(0.5)
        self.press_key("enter")
        time.sleep(2)
        return True

    def wait_for_export(self, timeout_minutes: int = 60) -> bool:
        import time as t
        deadline = t.time() + timeout_minutes * 60
        if self._project is not None:
            try:
                while t.time() < deadline:
                    if not self._project.IsRenderingInProgress():
                        logger.info("Export completed")
                        return True
                    t.sleep(10)
                return False
            except Exception:
                pass

        logger.info("Waiting for export (GUI mode — check manually)")
        return True

    def hotkey(self, *keys: str):
        from ..keyboard import KeyboardController
        KeyboardController().hotkey(*keys)

    def click(self, x: int, y: int):
        from ..mouse import MouseController
        MouseController().click(x, y)

    def type_text(self, text: str):
        from ..keyboard import KeyboardController
        KeyboardController().type(text)

    def press_key(self, key: str):
        from ..keyboard import KeyboardController
        KeyboardController().press(key)
