import logging
import platform
import subprocess
from abc import ABC, abstractmethod

logger = logging.getLogger("cortex.software")

SYSTEM = platform.system()
HAS_PSUTIL = False
try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    pass


def _find_process(name: str) -> bool:
    if HAS_PSUTIL:
        for proc in psutil.process_iter(["name"]):
            try:
                if name.lower() in proc.info["name"].lower():
                    return True
            except Exception:
                pass
        return False
    if SYSTEM == "Darwin":
        result = subprocess.run(
            ["pgrep", "-i", name.replace(" ", "")],
            capture_output=True, timeout=3,
        )
        return result.returncode == 0
    elif SYSTEM == "Linux":
        result = subprocess.run(
            ["pgrep", "-i", name.replace(" ", "")],
            capture_output=True, timeout=3,
        )
        return result.returncode == 0
    elif SYSTEM == "Windows":
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {name}.exe"],
            capture_output=True, text=True, timeout=3,
        )
        return name.lower() in result.stdout.lower()
    return False


def _activate_window(name: str):
    if SYSTEM == "Darwin":
        subprocess.run(["osascript", "-e",
                        f'tell application "{name}" to activate'],
                       capture_output=True, timeout=5)
    elif SYSTEM == "Linux":
        subprocess.run(["xdotool", "search", "--name", name, "windowactivate"],
                       capture_output=True, timeout=5)
    elif SYSTEM == "Windows":
        try:
            import ctypes
            from ctypes import wintypes
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32

            def enum_callback(hwnd, lparam):
                length = user32.GetWindowTextLengthW(hwnd) + 1
                buf = ctypes.create_unicode_buffer(length)
                user32.GetWindowTextW(hwnd, buf, length)
                if name.lower() in buf.value.lower():
                    user32.SetForegroundWindow(hwnd)
                    return False
                return True

            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            callback = WNDENUMPROC(enum_callback)
            user32.EnumWindows(callback, 0)
        except Exception as e:
            logger.warning(f"Windows activate_window failed: {e}")


def _launch_app(path_or_name: str):
    if SYSTEM == "Darwin":
        subprocess.run(["open", "-a", path_or_name], capture_output=True, timeout=30)
    elif SYSTEM == "Linux":
        subprocess.run([path_or_name], capture_output=True, timeout=30)
    elif SYSTEM == "Windows":
        subprocess.run(["start", path_or_name], shell=True, capture_output=True, timeout=30)
    else:
        subprocess.run([path_or_name], capture_output=True, timeout=30)


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
        return _find_process(self.name)

    def activate(self):
        _activate_window(self.name)
