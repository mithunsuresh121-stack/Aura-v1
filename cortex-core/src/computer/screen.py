"""
Screen control — screenshot capture and analysis.
Uses macOS screencapture utility for screenshots.
Vision analysis is pluggable (default: returns raw info, can use a vision model).
"""
import os
import subprocess
import tempfile
import logging
from typing import Optional

logger = logging.getLogger("cortex.computer")


class ScreenController:
    def __init__(self, vision_model=None):
        self.vision_model = vision_model
        self._display_id = None

    def capture(self, path: Optional[str] = None) -> str:
        path = path or os.path.join(tempfile.gettempdir(), "aura_screen.png")
        subprocess.run(
            ["screencapture", "-x", path],
            capture_output=True, timeout=10,
        )
        if not os.path.exists(path):
            raise RuntimeError("Screenshot capture failed")
        return path

    def capture_to_base64(self) -> str:
        import base64
        path = self.capture()
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    async def describe(self, detail: str = "brief") -> str:
        path = self.capture()
        img_b64 = self._image_to_base64(path)
        os.remove(path)

        if self.vision_model:
            return await self._analyze_with_vision(img_b64, detail)

        return self._basic_description(path if os.path.exists(path) else "")

    def _basic_description(self, path: str) -> str:
        if not os.path.exists(path):
            return "Screenshot unavailable"
        try:
            result = subprocess.run(
                ["file", path], capture_output=True, text=True, timeout=5,
            )
            size = os.path.getsize(path)
            return f"Screenshot captured ({size // 1024} KB, {result.stdout.strip()})"
        except Exception as e:
            return f"Screenshot captured (analysis unavailable: {e})"

    def _image_to_base64(self, path: str) -> str:
        import base64
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()

    async def _analyze_with_vision(self, img_b64: str, detail: str) -> str:
        prompt = "Describe what you see in this screenshot." if detail == "brief" \
            else f"Provide a detailed analysis of this screenshot. Focus on: UI elements, text content, and layout. Detail level: {detail}"
        return await self.vision_model.generate(messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                ],
            },
        ])

    @property
    def display_size(self) -> tuple[int, int]:
        result = subprocess.run(
            ["system_profiler", "SPDisplaysDataType"],
            capture_output=True, text=True, timeout=10,
        )
        import re
        match = re.search(r"Resolution: (\d+) x (\d+)", result.stdout)
        if match:
            return (int(match.group(1)), int(match.group(2)))
        return (1920, 1080)
