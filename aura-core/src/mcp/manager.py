"""
MCP Manager — manages multiple MCP server connections.
Reads config from mcp_config.json for server definitions.
"""
import json
import os
import logging
from typing import Optional
from .client import MCPClient, MCPTool

logger = logging.getLogger("cortex.mcp")


def load_mcp_config(path: str = "") -> dict:
    paths = [path] if path else []
    paths.extend([
        os.environ.get("AURA_MCP_CONFIG", ""),
        os.path.expanduser("~/.config/aura/mcp.json"),
        os.path.join(os.getcwd(), "mcp_config.json"),
    ])
    for p in paths:
        if p and os.path.exists(p):
            with open(p) as f:
                return json.load(f)
    return {}


class MCPManager:
    def __init__(self, config_path: str = ""):
        self._clients: dict[str, MCPClient] = {}
        config = load_mcp_config(config_path)
        self._build_from_config(config)

    def _build_from_config(self, config: dict):
        servers = config.get("servers", {})
        for name, cfg in servers.items():
            if not cfg.get("enabled", True):
                continue
            client = MCPClient(
                server_name=name,
                command=cfg.get("command", ""),
                args=cfg.get("args", []),
            )
            self._clients[name] = client
            logger.info(f"MCP server '{name}' configured")

    async def connect_all(self):
        for name, client in self._clients.items():
            try:
                await client.connect()
                logger.info(f"MCP '{name}' connected")
            except Exception as e:
                logger.error(f"MCP '{name}' connection failed: {e}")

    async def disconnect_all(self):
        for name, client in self._clients.items():
            try:
                await client.close()
            except Exception:
                pass
        self._clients.clear()

    async def _ensure_connected(self):
        for name, client in self._clients.items():
            if not client._connected:
                try:
                    await client.connect()
                    logger.info(f"MCP '{name}' connected on demand")
                except Exception as e:
                    logger.warning(f"MCP '{name}' connection failed: {e}")

    @property
    async def all_tools(self) -> list[MCPTool]:
        await self._ensure_connected()
        tools = []
        for client in self._clients.values():
            tools.extend(client.tools)
        return tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: dict) -> str:
        await self._ensure_connected()
        client = self._clients.get(server_name)
        if not client:
            return f"Error: MCP server '{server_name}' not connected"
        return await client.call_tool(tool_name, arguments)

    async def call_tool_by_full_name(self, full_name: str, arguments: dict) -> str:
        parts = full_name.split("_", 2)
        if len(parts) < 3:
            return f"Error: invalid tool name '{full_name}'"
        server_name = parts[1]
        tool_name = parts[2]
        return await self.call_tool(server_name, tool_name, arguments)
