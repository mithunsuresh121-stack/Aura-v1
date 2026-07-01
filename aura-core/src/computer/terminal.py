"""
TerminalAgent — spawns and manages interactive shell sessions.
Supports bash, zsh, PowerShell, and any other shell.

Uses PTY (pseudo-terminal) on POSIX, subprocess pipes on Windows.
"""
from __future__ import annotations
import asyncio
import logging
import os
import platform
import select
import signal
import subprocess
import time
import uuid
from typing import Optional

logger = logging.getLogger("cortex.terminal")

SYSTEM = platform.system()
HAS_PTY = SYSTEM != "Windows"


class ShellSession:
    def __init__(self, shell: str = "bash", rows: int = 24, cols: int = 80):
        self.id = uuid.uuid4().hex[:12]
        self.shell = shell
        self.rows = rows
        self.cols = cols
        self.process: Optional[subprocess.Popen] = None
        self._fd = None
        self._buffer = b""
        self.created_at = time.time()
        self.last_active = time.time()
        self.closed = False

    def start(self):
        if HAS_PTY:
            import pty
            pid, fd = pty.fork()
            if pid == 0:
                os.execvp(self.shell, [self.shell])
            self._pid = pid
            self._fd = fd
        else:
            self.process = subprocess.Popen(
                [self.shell],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if SYSTEM == "Windows" else 0,
            )

    def resize(self, rows: int, cols: int):
        self.rows = rows
        self.cols = cols
        if HAS_PTY and self._fd:
            import termios
            import fcntl
            import struct
            buf = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, buf)

    def write(self, data: str | bytes) -> int:
        self.last_active = time.time()
        if isinstance(data, str):
            data = data.encode()
        if HAS_PTY and self._fd:
            return os.write(self._fd, data)
        elif self.process and self.process.stdin:
            self.process.stdin.write(data)
            self.process.stdin.flush()
            return len(data)
        return 0

    def read(self, timeout: float = 0.1, max_bytes: int = 65536) -> bytes:
        self.last_active = time.time()
        if HAS_PTY and self._fd:
            import pty
            result = b""
            deadline = time.time() + timeout
            while time.time() < deadline and len(result) < max_bytes:
                r, _, _ = select.select([self._fd], [], [], 0.05)
                if r:
                    try:
                        chunk = os.read(self._fd, 4096)
                        if not chunk:
                            break
                        result += chunk
                    except OSError:
                        break
                else:
                    if result:
                        break
            return result
        elif self.process and self.process.stdout:
            import select as sel
            result = b""
            deadline = time.time() + timeout
            while time.time() < deadline and len(result) < max_bytes:
                r, _, _ = sel.select([self.process.stdout], [], [], 0.05)
                if r:
                    chunk = self.process.stdout.read(4096)
                    if not chunk:
                        break
                    result += chunk
                else:
                    if result:
                        break
            return result
        return b""

    def read_until(self, prompt: str = "$ ", timeout: float = 10.0) -> bytes:
        result = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            if HAS_PTY and self._fd:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if r:
                    chunk = os.read(self._fd, 4096)
                    if not chunk:
                        break
                    result += chunk
                    if prompt.encode() in result:
                        break
            elif self.process and self.process.stdout:
                import select as sel
                r, _, _ = sel.select([self.process.stdout], [], [], 0.1)
                if r:
                    chunk = self.process.stdout.read(4096)
                    if not chunk:
                        break
                    result += chunk
                    if prompt.encode() in result:
                        break
            else:
                break
        return result

    def close(self):
        self.closed = True
        if HAS_PTY and self._fd:
            os.close(self._fd)
            try:
                os.kill(self._pid, signal.SIGTERM)
            except OSError:
                pass
        elif self.process:
            self.process.terminate()
            self.process.wait(timeout=5)

    def running(self) -> bool:
        if self.closed:
            return False
        if HAS_PTY:
            try:
                pid, status = os.waitpid(self._pid, os.WNOHANG)
                return pid == 0
            except OSError:
                return False
        else:
            return self.process is not None and self.process.poll() is None


class TerminalAgent:
    def __init__(self):
        self.sessions: dict[str, ShellSession] = {}

    def create_session(self, shell: str = "bash", rows: int = 24, cols: int = 80) -> ShellSession:
        session = ShellSession(shell=shell, rows=rows, cols=cols)
        session.start()
        self.sessions[session.id] = session
        # Wait a moment for shell to start
        import time
        time.sleep(0.3)
        # Clear initial prompt
        session.read(timeout=0.5)
        logger.info(f"Terminal session {session.id} started: {shell}")
        return session

    def get_session(self, session_id: str) -> Optional[ShellSession]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[dict]:
        result = []
        for sid, s in self.sessions.items():
            result.append({
                "id": sid,
                "shell": s.shell,
                "created_at": s.created_at,
                "last_active": s.last_active,
                "running": s.running(),
            })
        return result

    def close_session(self, session_id: str) -> bool:
        session = self.sessions.get(session_id)
        if session:
            session.close()
            del self.sessions[session_id]
            logger.info(f"Terminal session {session_id} closed")
            return True
        return False

    def close_all(self):
        for sid in list(self.sessions.keys()):
            self.close_session(sid)

    async def execute(self, session_id: str, command: str, timeout: float = 30.0) -> dict:
        session = self.get_session(session_id)
        if not session or not session.running():
            return {"error": "Session not found or not running"}

        session.write(command + "\n")
        import asyncio
        output = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = session.read(timeout=0.3)
            if chunk:
                output += chunk
            else:
                # Check if no more data
                import asyncio
                await asyncio.sleep(0.2)
                chunk2 = session.read(timeout=0.1)
                if not chunk2:
                    break
                output += chunk2

        decoded = output.decode("utf-8", errors="replace")
        return {
            "session_id": session_id,
            "output": decoded,
            "bytes": len(output),
        }
