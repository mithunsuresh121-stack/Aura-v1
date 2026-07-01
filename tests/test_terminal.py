"""Tests for TerminalAgent — PTY shell sessions."""
import os
import pytest
from computer.terminal import TerminalAgent

pytestmark = pytest.mark.skipif(os.name == "nt", reason="PTY not available on Windows")


@pytest.fixture
def agent():
    ta = TerminalAgent()
    yield ta
    ta.close_all()


class TestSessionLifecycle:
    def test_create_session(self, agent):
        session = agent.create_session(shell="bash")
        assert session.id is not None
        assert len(session.id) == 12
        assert session.shell == "bash"
        assert session.running() is True

    def test_create_multiple_sessions(self, agent):
        s1 = agent.create_session()
        s2 = agent.create_session(shell="zsh")
        sessions = agent.list_sessions()
        assert len(sessions) == 2
        ids = [s["id"] for s in sessions]
        assert s1.id in ids
        assert s2.id in ids

    def test_list_sessions_empty(self, agent):
        assert agent.list_sessions() == []

    def test_list_sessions_after_create(self, agent):
        agent.create_session()
        assert len(agent.list_sessions()) == 1

    def test_close_session(self, agent):
        session = agent.create_session()
        agent.close_session(session.id)
        assert session.closed is True
        ids = [s["id"] for s in agent.list_sessions()]
        assert session.id not in ids

    def test_close_nonexistent(self, agent):
        assert agent.close_session("nonexistent") is False


class TestExec:
    @pytest.mark.asyncio
    async def test_echo(self, agent):
        session = agent.create_session()
        result = await agent.execute(session.id, "echo hello_test")
        assert "hello_test" in result["output"]

    @pytest.mark.asyncio
    async def test_multiple_commands(self, agent):
        session = agent.create_session()
        r1 = await agent.execute(session.id, "echo first")
        assert "first" in r1["output"]
        r2 = await agent.execute(session.id, "echo second")
        assert "second" in r2["output"]

    @pytest.mark.asyncio
    async def test_command_with_stderr(self, agent):
        session = agent.create_session()
        result = await agent.execute(session.id, "echo stderr_test >&2")
        assert "stderr_test" in result["output"]

    @pytest.mark.asyncio
    async def test_exec_bad_session(self, agent):
        result = await agent.execute("badid", "echo fail")
        assert "error" in result
        assert "not found" in result["error"].lower()


class TestWriteRead:
    def test_write(self, agent):
        session = agent.create_session()
        n = session.write(b"echo write_test\n")
        assert n > 0
        n2 = session.write("echo write_test2\n")
        assert n2 > 0

    def test_read(self, agent):
        session = agent.create_session()
        session.write(b"echo read_test\n")
        import time
        time.sleep(0.3)
        output = session.read(timeout=1)
        assert isinstance(output, bytes)
        assert b"read_test" in output


class TestResize:
    def test_resize(self, agent):
        session = agent.create_session()
        session.resize(rows=40, cols=120)
        assert session.running() is True

    def test_resize_within_bounds(self, agent):
        session = agent.create_session()
        session.resize(rows=5, cols=20)
        assert session.running() is True

    def test_resize_large(self, agent):
        session = agent.create_session()
        session.resize(rows=200, cols=500)
        assert session.running() is True


class TestCloseAll:
    def test_close_all(self, agent):
        agent.create_session()
        agent.create_session()
        agent.create_session()
        assert len(agent.list_sessions()) == 3
        agent.close_all()
        assert agent.list_sessions() == []

    def test_close_all_empty(self, agent):
        agent.close_all()
        assert agent.list_sessions() == []


class TestIdGeneration:
    def test_unique_ids(self, agent):
        ids = set()
        for _ in range(10):
            s = agent.create_session()
            ids.add(s.id)
        assert len(ids) == 10

    def test_id_length(self, agent):
        s = agent.create_session()
        assert len(s.id) == 12


class TestExecAfterClose:
    @pytest.mark.asyncio
    async def test_exec_after_close_raises(self, agent):
        session = agent.create_session()
        agent.close_session(session.id)
        result = await agent.execute(session.id, "echo fail")
        assert "error" in result


class TestShellType:
    def test_bash_session(self, agent):
        s = agent.create_session(shell="bash")
        assert s.shell == "bash"

    @pytest.mark.skipif(not os.path.exists("/bin/zsh"), reason="zsh not available")
    @pytest.mark.asyncio
    async def test_zsh_session(self, agent):
        s = agent.create_session(shell="zsh")
        assert s.shell == "zsh"
        result = await agent.execute(s.id, "echo zsh_works")
        assert "zsh_works" in result["output"]


class TestReadUntil:
    def test_read_until_prompt(self, agent):
        session = agent.create_session()
        output = session.read_until(prompt="$ ", timeout=3)
        assert isinstance(output, bytes)
        assert b"$" in output or output == b""
