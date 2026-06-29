import logging
import platform
import subprocess
import time
from typing import Optional

logger = logging.getLogger("cortex.computer")

HAS_PYAUTOGUI = False
try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    pass

SYSTEM = platform.system()


def _run(cmd: list[str], timeout: int = 10):
    try:
        subprocess.run(cmd, capture_output=True, timeout=timeout)
    except Exception as e:
        logger.warning(f"Command failed: {' '.join(cmd)}: {e}")


def _powershell_sendkeys(keys: str):
    script = f'''
$wshell = New-Object -ComObject wscript.shell
$wshell.SendKeys([string]::EscapeSpecialChars("{keys}"))
'''
    _run(["powershell", "-Command", script], timeout=10)


def _linux_xdotool(args: list[str]):
    _run(["xdotool"] + args, timeout=10)


class KeyboardController:
    def __init__(self):
        pass

    def type(self, text: str, interval: float = 0.01):
        if HAS_PYAUTOGUI:
            pyautogui.write(text, interval=interval)
            return
        if SYSTEM == "Darwin":
            escaped = text.replace('"', '\\"').replace("\n", "\\n")
            _run(["osascript", "-e",
                  f'tell application "System Events" to keystroke "{escaped}"'])
        elif SYSTEM == "Windows":
            _powershell_sendkeys(text)
        elif SYSTEM == "Linux":
            _linux_xdotool(["type", "--delay", str(int(interval * 1000)), text])
        else:
            logger.error(f"Unsupported platform: {SYSTEM}")

    def press(self, key: str):
        if HAS_PYAUTOGUI:
            pyautogui.press(key)
            return
        if SYSTEM == "Darwin":
            key_map = {
                "enter": "return", "tab": "tab", "escape": "escape",
                "backspace": "delete", "space": "space",
                "up": "up", "down": "down", "left": "left", "right": "right",
                "cmd": "command", "ctrl": "control", "alt": "option", "shift": "shift",
            }
            mapped = key_map.get(key.lower(), key)
            _run(["osascript", "-e",
                  f'tell application "System Events" to keystroke (key code 0) using {{{mapped}}}'])
        elif SYSTEM == "Windows":
            key_map = {
                "enter": "{ENTER}", "tab": "{TAB}", "escape": "{ESC}",
                "backspace": "{BACKSPACE}", "space": " ",
                "up": "{UP}", "down": "{DOWN}", "left": "{LEFT}", "right": "{RIGHT}",
                "ctrl": "^", "alt": "%", "shift": "+",
            }
            mapped = key_map.get(key.lower(), key)
            _powershell_sendkeys(mapped)
        elif SYSTEM == "Linux":
            key_map = {
                "enter": "Return", "tab": "Tab", "escape": "Escape",
                "backspace": "BackSpace", "space": "space",
                "up": "Up", "down": "Down", "left": "Left", "right": "Right",
                "cmd": "Super_L", "ctrl": "Control_L", "alt": "Alt_L", "shift": "Shift_L",
            }
            mapped = key_map.get(key.lower(), key)
            _linux_xdotool(["key", mapped])
        else:
            logger.error(f"Unsupported platform: {SYSTEM}")

    def hotkey(self, *keys: str):
        if SYSTEM != "Darwin":
            keys = tuple("ctrl" if k.lower() == "cmd" else k for k in keys)
        if HAS_PYAUTOGUI:
            pyautogui.hotkey(*keys)
            return
        if SYSTEM == "Darwin":
            key_map = {
                "cmd": "command", "ctrl": "control", "alt": "option",
                "shift": "shift", "tab": "tab", "space": "space",
            }
            mapped = [key_map.get(k.lower(), k) for k in keys]
            seq = ", ".join(mapped)
            _run(["osascript", "-e",
                  f'tell application "System Events" to keystroke (key code 0) using {{{seq}}}'])
        elif SYSTEM == "Windows":
            key_map = {
                "ctrl": "^", "alt": "%", "shift": "+",
                "cmd": "^{ESC}", "tab": "{TAB}", "enter": "{ENTER}",
            }
            mapped = "".join(key_map.get(k.lower(), k) for k in keys)
            _powershell_sendkeys(mapped)
        elif SYSTEM == "Linux":
            key_map = {
                "cmd": "Super_L", "ctrl": "Control_L", "alt": "Alt_L",
                "shift": "Shift_L", "tab": "Tab", "space": "space",
            }
            mapped = "+".join(key_map.get(k.lower(), k) for k in keys)
            _linux_xdotool(["key", mapped])
        else:
            logger.error(f"Unsupported platform: {SYSTEM}")
