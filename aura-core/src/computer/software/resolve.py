import os
import sys
import time
import logging
import platform
import subprocess
from typing import Optional
from .base import VideoEditor, _launch_app

logger = logging.getLogger("cortex.software.resolve")

SYSTEM = platform.system()

_RESOLVE_PATHS = {
    "Darwin": "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting/Modules",
    "Windows": os.path.join(os.environ.get("PROGRAMDATA", "C:\\ProgramData"),
                            "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting", "Modules"),
    "Linux": "/opt/resolve/Developer/Scripting/Modules",
}


class DaVinciResolve(VideoEditor):
    name = "DaVinci Resolve"

    def __init__(self):
        super().__init__()
        self._resolve = None
        self._project = None
        self._fusion = None
        self._resolve_script_path = _RESOLVE_PATHS.get(SYSTEM, _RESOLVE_PATHS["Linux"])
        self._has_script_api = os.path.isdir(self._resolve_script_path)

    def _try_init_api(self):
        if not self._has_script_api:
            return False
        try:
            if self._resolve_script_path not in sys.path:
                sys.path.insert(0, self._resolve_script_path)
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
            if SYSTEM == "Darwin":
                _launch_app(self.name)
            elif SYSTEM == "Windows":
                resolve_path = os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"),
                                            "Blackmagic Design", "DaVinci Resolve", "Resolve.exe")
                if os.path.exists(resolve_path):
                    subprocess.Popen([resolve_path], shell=True)
                else:
                    _launch_app("Resolve")
            elif SYSTEM == "Linux":
                subprocess.Popen(["/opt/resolve/bin/resolve"])
            time.sleep(15)
            self._is_open = True
            self._try_init_api()
            return True
        except Exception as e:
            logger.error(f"Failed to launch DaVinci Resolve: {e}")
            return False

    def close(self):
        self._resolve = None
        self._project = None
        if SYSTEM == "Darwin":
            subprocess.run(["osascript", "-e",
                            'tell application "DaVinci Resolve" to quit'],
                           capture_output=True, timeout=10)
        elif SYSTEM == "Windows":
            subprocess.run(["taskkill", "/F", "/IM", "Resolve.exe"],
                           capture_output=True, timeout=10)
        elif SYSTEM == "Linux":
            subprocess.run(["pkill", "-f", "resolve"],
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

        self._keystroke("cmd", "n")
        time.sleep(0.5)
        self._type(name)
        time.sleep(0.3)
        self._press("return")
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

        self._keystroke("cmd", "o")
        time.sleep(0.5)
        self._type(path)
        time.sleep(0.3)
        self._press("return")
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

        self._keystroke("cmd", "s")
        time.sleep(0.5)
        if path:
            self._keystroke("cmd", "shift", "s")
            time.sleep(0.5)
            self._type(path)
            time.sleep(0.3)
            self._press("return")
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
            self._keystroke("cmd", "i")
            time.sleep(0.5)
            self._type(fp)
            time.sleep(0.3)
            self._press("return")
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

        self._keystroke("cmd", "shift", "a")
        time.sleep(0.3)
        self._keystroke("cmd", "down")
        time.sleep(0.3)
        self._press("return")
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

        self._keystroke("cmd", "m")
        time.sleep(1)
        from ..mouse import MouseController
        MouseController().click(400, 300)
        time.sleep(0.5)
        self._type(preset)
        time.sleep(0.3)
        self._press("return")
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

        self._keystroke("cmd", "m")
        time.sleep(1)
        from ..mouse import MouseController
        MouseController().click(800, 400)
        time.sleep(0.5)
        self._type(output_path)
        time.sleep(0.3)
        self._press("return")
        time.sleep(0.5)
        self._press("return")
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

    def _keystroke(self, *keys: str):
        from ..keyboard import KeyboardController
        KeyboardController().hotkey(*keys)

    def _click(self, x: int, y: int):
        from ..mouse import MouseController
        MouseController().click(x, y)

    def _type(self, text: str):
        from ..keyboard import KeyboardController
        KeyboardController().type(text)

    def _press(self, key: str):
        from ..keyboard import KeyboardController
        KeyboardController().press(key)
