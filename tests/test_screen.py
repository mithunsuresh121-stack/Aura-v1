"""Tests for ScreenController — screenshot capture."""
import os
import pytest
from computer.screen import ScreenController


class TestCapture:
    def test_capture_returns_path(self):
        s = ScreenController()
        path = s.capture("/tmp/test_capture_unit.png")
        assert path == "/tmp/test_capture_unit.png"
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000  # at least 1KB
        os.remove(path)

    def test_capture_default_path(self):
        s = ScreenController()
        path = s.capture()
        assert path.endswith("aura_screen.png")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000
        os.remove(path)

    def test_capture_multiple(self):
        s = ScreenController()
        p1 = s.capture("/tmp/test_cap_a.png")
        p2 = s.capture("/tmp/test_cap_b.png")
        assert os.path.exists(p1)
        assert os.path.exists(p2)
        os.remove(p1)
        os.remove(p2)

    def test_capture_format(self):
        s = ScreenController()
        path = s.capture("/tmp/test_format.png")
        with open(path, "rb") as f:
            header = f.read(8)
        assert header[:4] == b'\x89PNG'
        os.remove(path)


class TestCaptureAsync:
    @pytest.mark.asyncio
    async def test_capture_async(self):
        s = ScreenController()
        path = await s.capture_async("/tmp/test_cap_async.png")
        assert os.path.exists(path)
        assert os.path.getsize(path) > 1000
        os.remove(path)


class TestDisplaySize:
    def test_display_size_returns_tuple(self):
        s = ScreenController()
        w, h = s.display_size
        assert isinstance(w, int)
        assert isinstance(h, int)
        assert w > 0 and h > 0
        assert w >= 800  # minimum reasonable width
        assert h >= 600  # minimum reasonable height


class TestCaptureToBase64:
    def test_capture_to_base64(self):
        s = ScreenController()
        b64 = s.capture_to_base64()
        assert isinstance(b64, str)
        assert len(b64) > 100
        assert b64 == b64.strip()  # no whitespace


class TestDescribe:
    @pytest.mark.asyncio
    async def test_describe_basic(self):
        s = ScreenController()
        desc = await s.describe("brief")
        assert isinstance(desc, str)
        assert len(desc) > 0
        assert "KB" in desc or "Screenshot" in desc

    @pytest.mark.asyncio
    async def test_describe_without_vision(self):
        s = ScreenController()
        desc = await s.describe("detailed")
        assert isinstance(desc, str)
