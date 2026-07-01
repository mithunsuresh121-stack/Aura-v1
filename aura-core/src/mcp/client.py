"""
MCP (Model Context Protocol) client.
Connects to MCP servers via stdio or HTTP and exposes tools/resources to the agent.
Spec: https://modelcontextprotocol.io
"""
import json
import asyncio
import logging
from typing import Any, Optional

logger = logging.getLogger("cortex.mcp")


class MCPTool:
    def __init__(self, name: str, description: str, input_schema: dict, server_name: str):
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.server_name = server_name

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": f"mcp_{self.server_name}_{self.name}",
                "description": f"[{self.server_name}] {self.description}",
                "parameters": self.input_schema,
            },
        }


class MCPClient:
    def __init__(self, server_name: str, command: str, args: Optional[list[str]] = None):
        self.server_name = server_name
        self.command = command
        self.args = args or []
        self._process = None
        self._reader = None
        self._writer = None
        self._tools: list[MCPTool] = []
        self._resources: list[dict] = []
        self._connected = False
        self._request_id = 0
        self._pending = {}

    async def connect(self):
        self._process = await asyncio.create_subprocess_exec(
            self.command, *self.args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._reader = self._process.stdout
        self._writer = self._process.stdin

        resp = await self._send_request("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "aura", "version": "0.1.0"},
        })
        if resp and resp.get("capabilities"):
            self._connected = True

        await self._send_notification("initialized", {})
        await self._discover()

    async def _send_request(self, method: str, params: dict) -> Optional[dict]:
        self._request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        future = asyncio.get_event_loop().create_future()
        self._pending[self._request_id] = future
        try:
            line = json.dumps(req) + "\n"
            self._writer.write(line.encode())
            await self._writer.drain()

            resp_line = await asyncio.wait_for(self._reader.readline(), timeout=30)
            resp = json.loads(resp_line.decode())
            if "result" in resp:
                return resp["result"]
            elif "error" in resp:
                logger.error(f"MCP error: {resp['error']}")
                return None
        except Exception as e:
            logger.error(f"MCP request failed: {e}")
            return None
        finally:
            self._pending.pop(self._request_id, None)

    async def _send_notification(self, method: str, params: dict):
        notif = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        line = json.dumps(notif) + "\n"
        self._writer.write(line.encode())
        await self._writer.drain()

    async def _discover(self):
        result = await self._send_request("tools/list", {})
        if result and "tools" in result:
            for t in result["tools"]:
                self._tools.append(MCPTool(
                    name=t["name"],
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                    server_name=self.server_name,
                ))

        result = await self._send_request("resources/list", {})
        if result and "resources" in result:
            self._resources = result["resources"]

        logger.info(f"MCP '{self.server_name}': {len(self._tools)} tools, {len(self._resources)} resources")

    @property
    def tools(self) -> list[MCPTool]:
        return self._tools

    async def call_tool(self, name: str, arguments: dict) -> str:
        result = await self._send_request("tools/call", {
            "name": name,
            "arguments": arguments,
        })
        if result is None:
            return f"Error: tool '{name}' failed"
        content = result.get("content", [])
        parts = []
        for c in content:
            if c.get("type") == "text":
                parts.append(c["text"])
            elif c.get("type") == "resource":
                parts.append(f"[Resource: {c.get('uri', 'unknown')}]")
        return "\n".join(parts) if parts else f"Tool '{name}' executed (no output)"

    async def close(self):
        self._connected = False
        if self._process:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except Exception:
                self._process.kill()
