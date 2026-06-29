"""
Keyboard control — type text, press keys, hotkeys.
Uses PyAutoGUI (fallback: AppleScript via osascript).
"""
import logging
import subprocess
from typing import Optional

logger = logging.getLogger("cortex.computer")

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False


class KeyboardController:
    def __init__(self):
        pass

    def type(self, text: str, interval: float = 0.01):
        if HAS_PYAUTOGUI:
            pyautogui.write(text, interval=interval)
        else:
            escaped = text.replace('"', '\\"').replace("\n", "\\n")
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to keystroke "{escaped}"'],
                capture_output=True, timeout=30,
            )

    def press(self, key: str):
        if HAS_PYAUTOGUI:
            pyautogui.press(key)
        else:
            key_map = {
                "enter": "return", "tab": "tab", "escape": "escape",
                "backspace": "delete", "space": "space",
                "up": "up", "down": "down", "left": "left", "right": "right",
                "cmd": "command", "ctrl": "control", "alt": "option", "shift": "shift",
            }
            mapped = key_map.get(key.lower(), key)
            if HAS_PYAUTOGUI:
                pyautogui.press(mapped)
            else:
                subprocess.run(
                    ["osascript", "-e",
                     f'tell application "System Events" to key code {self._key_code(mapped)}'],
                    capture_output=True, timeout=5,
                )

    def hotkey(self, *keys: str):
        if HAS_PYAUTOGUI:
            pyautogui.hotkey(*keys)
        else:
            key_map = {
                "cmd": "command", "ctrl": "control", "alt": "option",
                "shift": "shift", "tab": "tab", "space": "space",
            }
            mapped = [key_map.get(k.lower(), k) for k in keys]
            seq = ", ".join(mapped)
            subprocess.run(
                ["osascript", "-e",
                 f'tell application "System Events" to keystroke (key code 0) using {{{seq}}}'],
                capture_output=True, timeout=5,
            )
