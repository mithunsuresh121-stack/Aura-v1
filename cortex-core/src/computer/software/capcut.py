"""
CapCut desktop automation.
Uses keyboard shortcuts. CapCut has no scripting API.
"""
import time
import logging
import subprocess
from .base import VideoEditor

logger = logging.getLogger("cortex.software.capcut")


class CapCut(VideoEditor):
    name = "CapCut"

    def launch(self) -> bool:
        if self.is_running():
            self._is_open = True
            return True
        try:
            subprocess.run(["open", "-a", "CapCut"], timeout=30)
            time.sleep(15)
            self._is_open = True
            return True
        except Exception as e:
            logger.error(f"Failed to launch CapCut: {e}")
            return False

    def close(self):
        subprocess.run(["osascript", "-e",
                        'tell application "CapCut" to quit'],
                       capture_output=True, timeout=10)
        self._is_open = False

    def new_project(self, name: str) -> bool:
        self.activate()
        time.sleep(1)
        self._keystroke("cmd", "n")
        time.sleep(0.5)
        self._type(name)
        time.sleep(0.3)
        self._press("return")
        time.sleep(2)
        return True

    def open_project(self, path: str) -> bool:
        self.activate()
        time.sleep(1)
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
        self._keystroke("cmd", "i")
        time.sleep(0.5)
        for fp in file_paths:
            self._type(fp)
            time.sleep(0.3)
            self._press("return")
            time.sleep(1.5)
        return True

    def add_to_timeline(self, media_name: str, track: int = 0) -> bool:
        self.activate()
        time.sleep(0.5)
        self._type(media_name)
        time.sleep(0.5)
        self._press("return")
        time.sleep(1)
        return True

    def set_export_preset(self, preset: str = "1080p") -> bool:
        self.activate()
        time.sleep(0.5)
        self._keystroke("cmd", "m")
        time.sleep(1)
        self._type(preset)
        time.sleep(0.3)
        self._press("return")
        time.sleep(1)
        return True

    def export(self, output_path: str) -> bool:
        self.activate()
        time.sleep(0.5)
        self._keystroke("cmd", "m")
        time.sleep(1.5)
        self._keystroke("cmd", "shift", "e")
        time.sleep(0.5)
        self._type(output_path)
        time.sleep(0.3)
        self._press("return")
        time.sleep(0.5)
        self._press("return")
        time.sleep(2)
        return True

    def wait_for_export(self, timeout_minutes: int = 60) -> bool:
        logger.info("Waiting for CapCut export (monitor progress manually)")
        return True

    def _keystroke(self, *keys: str):
        from ..keyboard import KeyboardController
        KeyboardController().hotkey(*keys)

    def _type(self, text: str):
        from ..keyboard import KeyboardController
        KeyboardController().type(text)

    def _press(self, key: str):
        from ..keyboard import KeyboardController
        KeyboardController().press(key)
