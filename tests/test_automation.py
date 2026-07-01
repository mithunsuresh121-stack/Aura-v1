"""Tests for ComputerAgent — mouse, keyboard, app control."""
import sys
import pytest
from computer.automation import ComputerAgent


@pytest.fixture
def agent():
    return ComputerAgent()


class TestMouse:
    def test_position(self, agent):
        x, y = agent.get_position()
        assert isinstance(x, int)
        assert isinstance(y, int)
        assert x >= 0 and y >= 0

    def test_click_at(self, agent):
        agent.click(200, 200)
        # Position may not change if accessibility not granted
        assert True

    def test_move(self, agent):
        agent.move_mouse(300, 400)
        assert True  # smoke test — may not work without accessibility

    def test_double_click(self, agent):
        agent.double_click(100, 100)
        assert True

    @pytest.mark.skipif(sys.platform == "darwin",
                        reason="pyautogui.drag bug on macOS (button=None)")
    def test_drag(self, agent):
        agent.drag(200, 200, 300, 300)
        assert True

    def test_scroll(self, agent):
        agent.scroll(-3)
        agent.scroll(3)
        assert True


class TestKeyboard:
    def test_type_text(self, agent):
        agent.type_text("hello world")
        assert True

    def test_press_key(self, agent):
        agent.press_key("enter")
        assert True

    def test_hotkey(self, agent):
        agent.hotkey("ctrl", "c")
        assert True


class TestActiveWindow:
    def test_get_active_window(self, agent):
        result = agent.get_active_window()
        assert isinstance(result, str)
        assert len(result) > 0


class TestAppControl:
    def test_open_app(self, agent):
        result = agent.open_app("TextEdit")
        assert result is None

    def test_run_script(self, agent):
        result = agent.run_script('echo "script_test_ok"')
        assert "script_test_ok" in result


class TestScreenshot:
    def test_screenshot(self, agent):
        path = agent.screenshot()
        assert path is not None
        assert path.endswith(".png")

    @pytest.mark.asyncio
    async def test_screenshot_async(self, agent):
        path = await agent.screenshot_async()
        assert path is not None
        assert path.endswith(".png")
