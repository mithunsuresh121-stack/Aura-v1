"""
Mouse control — click, move, drag, scroll.
Uses PyAutoGUI (fallback: AppleScript via osascript).
"""
import logging
import subprocess
import time
from typing import Optional

logger = logging.getLogger("cortex.computer")

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class MouseController:
    def __init__(self):
        self._screen = None

    @property
    def position(self) -> tuple[int, int]:
        if HAS_PYAUTOGUI:
            return pyautogui.position()
        result = subprocess.run(
            ["osascript", "-e", "tell application \"System Events\" to get position of mouse"],
            capture_output=True, text=True, timeout=5,
        )
        parts = result.stdout.strip().split(", ")
        if len(parts) == 2:
            return (int(parts[0]), int(parts[1]))
        return (0, 0)

    def move(self, x: int, y: int, duration: float = 0.2):
        if HAS_PYAUTOGUI:
            pyautogui.moveTo(x, y, duration=duration)
        else:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to set position of mouse to {{{x}, {y}}}'],
                capture_output=True, timeout=5,
            )

    def click(self, x: Optional[int] = None, y: Optional[int] = None, button: str = "left"):
        if HAS_PYAUTOGUI:
            if x is not None and y is not None:
                pyautogui.click(x, y, button=button)
            else:
                pyautogui.click(button=button)
        else:
            target = f"at position {{{x}, {y}}}" if x is not None and y is not None else ""
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to click {target}'],
                capture_output=True, timeout=5,
            )

    def double_click(self, x: Optional[int] = None, y: Optional[int] = None):
        if HAS_PYAUTOGUI:
            if x is not None and y is not None:
                pyautogui.doubleClick(x, y)
            else:
                pyautogui.doubleClick()
        else:
            target = f"at position {{{x}, {y}}}" if x is not None and y is not None else ""
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to double click {target}'],
                capture_output=True, timeout=5,
            )

    def drag(self, start_x: int, start_y: int, end_x: int, end_y: int, duration: float = 0.5):
        if HAS_PYAUTOGUI:
            pyautogui.moveTo(start_x, start_y, duration=0.1)
            pyautogui.drag(end_x - start_x, end_y - start_y, duration=duration)
        else:
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to drag from position {{{start_x}, {start_y}}} to position {{{end_x}, {end_y}}}'],
                capture_output=True, timeout=10,
            )

    def scroll(self, clicks: int, x: Optional[int] = None, y: Optional[int] = None):
        if HAS_PYAUTOGUI:
            pyautogui.scroll(clicks, x, y)
        else:
            direction = "up" if clicks > 0 else "down"
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to scroll wheel {abs(clicks)} lines in direction {direction}'],
                capture_output=True, timeout=5,
            )
