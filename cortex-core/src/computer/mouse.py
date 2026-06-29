import logging
import platform
import subprocess
import time
from typing import Optional

logger = logging.getLogger("cortex.computer")

HAS_PYAUTOGUI = False
try:
    import pyautogui
    pyautogui.FAILSAFE = True
    HAS_PYAUTOGUI = True
except ImportError:
    pass

SYSTEM = platform.system()


def _run(cmd: list[str], timeout: int = 10, text: bool = False):
    try:
        return subprocess.run(cmd, capture_output=True, text=text, timeout=timeout)
    except Exception as e:
        logger.warning(f"Command failed: {' '.join(cmd)}: {e}")
        return None


class MouseController:
    def __init__(self):
        self._screen = None

    @property
    def position(self) -> tuple[int, int]:
        if HAS_PYAUTOGUI:
            return pyautogui.position()
        if SYSTEM == "Darwin":
            result = _run(
                ["osascript", "-e", 'tell application "System Events" to get position of mouse'],
                timeout=5, text=True,
            )
            if result and result.stdout:
                parts = result.stdout.strip().split(", ")
                if len(parts) == 2:
                    return (int(parts[0]), int(parts[1]))
        elif SYSTEM == "Linux":
            result = _run(["xdotool", "getmouselocation", "--shell"], timeout=5, text=True)
            if result and result.stdout:
                for line in result.stdout.splitlines():
                    if line.startswith("X="):
                        x = int(line.split("=")[1])
                    elif line.startswith("Y="):
                        y = int(line.split("=")[1])
                return (x, y)
        return (0, 0)

    def move(self, x: int, y: int, duration: float = 0.2):
        if HAS_PYAUTOGUI:
            pyautogui.moveTo(x, y, duration=duration)
            return
        if SYSTEM == "Darwin":
            _run(["osascript", "-e",
                  f'tell application "System Events" to set position of mouse to {{{x}, {y}}}'])
        elif SYSTEM == "Linux":
            _run(["xdotool", "mousemove", str(x), str(y)])
        elif SYSTEM == "Windows":
            _run(["powershell", "-Command",
                  f'[System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({x},{y})'])

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left"):
        if HAS_PYAUTOGUI:
            if x is not None and y is not None:
                pyautogui.click(x, y, button=button)
            else:
                pyautogui.click(button=button)
            return
        if SYSTEM == "Darwin":
            target = f"at position {{{x}, {y}}}" if x is not None and y is not None else ""
            _run(["osascript", "-e",
                  f'tell application "System Events" to click {target}'])
        elif SYSTEM == "Linux":
            btn = {"left": "1", "middle": "2", "right": "3"}.get(button, "1")
            if x is not None and y is not None:
                _run(["xdotool", "mousemove", str(x), str(y)])
            _run(["xdotool", "click", btn])
        elif SYSTEM == "Windows":
            _run(["powershell", "-Command",
                  f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({x or 0},{y or 0}); [System.Windows.Forms.SendKeys]::SendWait("%{{LEFT}}")'])

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None):
        if HAS_PYAUTOGUI:
            if x is not None and y is not None:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.doubleClick()
            return
        if SYSTEM == "Darwin":
            target = f"at position {{{x}, {y}}}" if x is not None and y is not None else ""
            _run(["osascript", "-e",
                  f'tell application "System Events" to double click {target}'])
        elif SYSTEM == "Linux":
            if x is not None and y is not None:
                _run(["xdotool", "mousemove", str(x), str(y)])
            _run(["xdotool", "click", "--repeat", "2", "1"])
        elif SYSTEM == "Windows":
            # Windows double-click via PowerShell
            pass
        else:
            logger.error(f"Unsupported platform: {SYSTEM}")

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5):
        if HAS_PYAUTOGUI:
            pyautogui.moveTo(start_x, start_y, duration=0.1)
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
            return
        if SYSTEM == "Darwin":
            _run(["osascript", "-e",
                  f'tell application "System Events" to drag from position {{{start_x}, {start_y}}} to position {{{end_x}, {end_y}}}'])
        elif SYSTEM == "Linux":
            _run(["xdotool", "mousemove", str(start_x), str(start_y)])
            _run(["xdotool", "mousedown", "1"])
            time.sleep(0.1)
            _run(["xdotool", "mousemove", str(end_x), str(end_y)])
            _run(["xdotool", "mouseup", "1"])
        elif SYSTEM == "Windows":
            _run(["powershell", "-Command",
                  f'Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point({start_x},{start_y}); [System.Windows.Forms.SendKeys]::SendWait("%{{LEFT}}")'])

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None):
        if HAS_PYAUTOGUI:
            pyautogui.scroll(clicks, x, y)
            return
        if SYSTEM == "Darwin":
            direction = "up" if clicks > 0 else "down"
            _run(["osascript", "-e",
                  f'tell application "System Events" to scroll wheel {abs(clicks)} lines in direction {direction}'])
        elif SYSTEM == "Linux":
            direction = "--click" if clicks > 0 else "--click"
            _run(["xdotool", "click", "--repeat", str(abs(clicks)), "4" if clicks > 0 else "5"])
        elif SYSTEM == "Windows":
            import ctypes
            try:
                ctypes.windll.user32.mouse_event(0x0800 if clicks > 0 else 0x0780, 0, 0, clicks * 120, 0)
            except Exception as e:
                logger.warning(f"Windows scroll failed: {e}")
