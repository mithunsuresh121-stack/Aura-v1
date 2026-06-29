"""
ComputerAgent — high-level computer control agent.
Combines screen, mouse, and keyboard into a tool-based interface
that the LLM can use to control the user's computer.
"""
import logging
from typing import Optional
from .screen import ScreenController
from .mouse import MouseController
from .keyboard import KeyboardController

logger = logging.getLogger("cortex.computer")


class ComputerAgent:
    def __init__(self, vision_model=None):
        self.screen = ScreenController(vision_model=vision_model)
        self.mouse = MouseController()
        self.keyboard = KeyboardController()

    def screenshot(self) -> str:
        return self.screen.capture()

    async def look(self, detail: str = "brief") -> str:
        return await self.screen.describe(detail)

    def click(self, x: int, y: int, button: str = "left"):
        self.mouse.click(x, y, button)

    def move_mouse(self, x: int, y: int):
        self.mouse.move(x, y)

    def double_click(self, x: int, y: int):
        self.mouse.double_click(x, y)

    def drag(self, x1: int, y1: int, x2: int, y2: int):
        self.mouse.drag(x1, y1, x2, y2)

    def scroll(self, clicks: int):
        self.mouse.scroll(clicks)

    def type_text(self, text: str):
        self.keyboard.type(text)

    def press_key(self, key: str):
        self.keyboard.press(key)

    def hotkey(self, *keys: str):
        self.keyboard.hotkey(*keys)

    def get_position(self) -> tuple[int, int]:
        return self.mouse.position

    def open_app(self, app_name: str):
        import subprocess
        subprocess.run(["open", "-a", app_name], capture_output=True, timeout=10)
        logger.info(f"Opened app: {app_name}")

    def run_script(self, script: str, interpreter: str = "bash") -> str:
        import subprocess
        try:
            result = subprocess.run(
                [interpreter, "-c", script],
                capture_output=True, text=True, timeout=30,
            )
            output = result.stdout + result.stderr
            return output[:2000] if output else "(no output)"
        except Exception as e:
            return f"Script error: {e}"

    def get_active_window(self) -> str:
        import subprocess
        try:
            result = subprocess.run(
                ["osascript", "-e",
                 'tell application "System Events" to get name of first process whose frontmost is true'],
                capture_output=True, text=True, timeout=3,
            )
            name = result.stdout.strip()
            if name:
                return name
        except Exception:
            pass
        try:
            result = subprocess.run(
                ["python3.9", "-c", "import Quartz; ws = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionOnScreenOnly, 0); print(ws[0].get('kCGWindowOwnerName', 'unknown'))"],
                capture_output=True, text=True, timeout=3,
            )
            name = result.stdout.strip()
            if name:
                return name
        except Exception:
            pass
        return "unknown"

    async def execute_plan(self, steps: list[dict]) -> list[str]:
        results = []
        for step in steps:
            action = step.get("action")
            params = step.get("params", {})
            try:
                if action == "look":
                    r = await self.look(params.get("detail", "brief"))
                elif action == "click":
                    self.click(params["x"], params["y"], params.get("button", "left"))
                    r = f"Clicked at ({params['x']}, {params['y']})"
                elif action == "type":
                    self.type_text(params["text"])
                    r = f"Typed: {params['text'][:50]}..."
                elif action == "press":
                    self.press_key(params["key"])
                    r = f"Pressed: {params['key']}"
                elif action == "hotkey":
                    self.hotkey(*params["keys"])
                    r = f"Hotkey: {'+'.join(params['keys'])}"
                elif action == "scroll":
                    self.scroll(params["clicks"])
                    r = f"Scrolled {params['clicks']} clicks"
                elif action == "open":
                    self.open_app(params["app"])
                    r = f"Opened app: {params['app']}"
                elif action == "screenshot":
                    r = self.screenshot()
                else:
                    r = f"Unknown action: {action}"
                results.append(r)
            except Exception as e:
                results.append(f"Error in {action}: {e}")
        return results
