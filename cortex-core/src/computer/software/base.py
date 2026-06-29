"""
Base video editor interface.
All editors implement these operations using their native API (preferred)
or keyboard shortcut / GUI automation (fallback).
"""
import logging
from abc import ABC, abstractmethod

logger = logging.getLogger("cortex.software")


class VideoEditor(ABC):
    name: str = "generic"

    def __init__(self):
        self._is_open = False

    @abstractmethod
    def launch(self) -> bool:
        ...

    @abstractmethod
    def close(self):
        ...

    @abstractmethod
    def new_project(self, name: str) -> bool:
        ...

    @abstractmethod
    def open_project(self, path: str) -> bool:
        ...

    @abstractmethod
    def save_project(self, path: str = "") -> bool:
        ...

    @abstractmethod
    def import_media(self, file_paths: list[str]) -> bool:
        ...

    @abstractmethod
    def add_to_timeline(self, media_name: str, track: int = 0) -> bool:
        ...

    @abstractmethod
    def set_export_preset(self, preset: str = "H.264 Master") -> bool:
        ...

    @abstractmethod
    def export(self, output_path: str) -> bool:
        ...

    @abstractmethod
    def wait_for_export(self, timeout_minutes: int = 60) -> bool:
        ...

    def is_installed(self) -> bool:
        import shutil
        return shutil.which(self.name) is not None or self._app_path() is not None

    def _app_path(self):
        import shutil
        return shutil.which(self.name)

    def is_running(self) -> bool:
        import subprocess
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to exists (processes where name is "{self.name}")'],
                capture_output=True, text=True, timeout=3,
            )
            return "true" in result.stdout.lower()
        except Exception:
            return False

    def activate(self):
        import subprocess
        subprocess.run(["osascript", "-e",
                        f'tell application "{self.name}" to activate'],
                       capture_output=True, timeout=5)
