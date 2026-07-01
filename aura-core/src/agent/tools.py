from __future__ import annotations
"""
Tool-use scaffold for the agent.

Defines tools the agent can call. Each tool has:
  name, description, parameters (JSON schema)
  execute(params) → result (str)
"""
import json
import urllib.request
import urllib.parse
import subprocess
from datetime import datetime
from typing import Any, Callable


class Tool:
    def __init__(
        self,
        name: str,
        description: str,
        parameters: dict,
        fn: Callable[..., str],
    ):
        self.name = name
        self.description = description
        self.parameters = parameters
        self.fn = fn

    def to_openai_format(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def execute(self, *args, **kwargs) -> str:
        try:
            if args:
                return self.fn(*args)
            return self.fn(**kwargs)
        except Exception as e:
            return f"Error executing {self.name}: {e}"


def tool_current_time(timezone: str = "UTC") -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def tool_calculate(expression: str) -> str:
    """Safe math evaluator using AST parsing — no eval()."""
    import ast
    import operator as op

    allowed_ops = {
        ast.Add: op.add, ast.Sub: op.sub, ast.Mult: op.mul,
        ast.Div: op.truediv, ast.FloorDiv: op.floordiv, ast.Mod: op.mod,
        ast.Pow: op.pow, ast.USub: op.neg, ast.UAdd: op.pos,
    }
    allowed_names = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sum": sum, "int": int, "float": float, "str": str,
        "pi": 3.141592653589793, "e": 2.718281828459045,
    }

    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (int, float)):
                return node.value
            raise TypeError(f"Unsupported constant: {node.value}")
        if isinstance(node, ast.BinOp):
            if type(node.op) not in allowed_ops:
                raise TypeError(f"Unsupported operator: {type(node.op).__name__}")
            return allowed_ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            if type(node.op) not in allowed_ops:
                raise TypeError(f"Unsupported operator: {type(node.op).__name__}")
            return allowed_ops[type(node.op)](_eval(node.operand))
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise TypeError("Only simple function calls allowed")
            if node.func.id not in allowed_names:
                raise TypeError(f"Function not allowed: {node.func.id}")
            args = [_eval(a) for a in node.args]
            return allowed_names[node.func.id](*args)
        if isinstance(node, ast.Name):
            if node.id in allowed_names:
                return allowed_names[node.id]
            raise TypeError(f"Name not allowed: {node.id}")
        raise TypeError(f"Unsupported syntax: {type(node).__name__}")

    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval(tree)
        return str(result)
    except Exception as e:
        return f"Calculation error: {e}"


def tool_search_kb(query: str, knowledge_base: dict | None = None) -> str:
    """Search the knowledge base by keyword matching."""
    if not knowledge_base or not knowledge_base.get("texts"):
        return "Knowledge base is empty."
    texts = knowledge_base["texts"]
    sources = knowledge_base.get("sources", [""] * len(texts))
    q = query.lower()
    results = []
    for i, text in enumerate(texts):
        if q in text.lower():
            score = text.lower().count(q)
            results.append((score, i, text[:200], sources[i]))
    results.sort(key=lambda x: -x[0])
    if not results:
        return f"No results found for: {query}"
    out = [f"Found {len(results)} results for '{query}':"]
    for score, i, snippet, src in results[:3]:
        out.append(f"  [{src}] {snippet}...")
    return "\n".join(out)


def tool_read_file(path: str) -> str:
    """Read a file from disk. Sandboxed to workspace (AURA_WORKSPACE or cwd)."""
    import os
    allowed = os.environ.get("AURA_WORKSPACE", os.getcwd())
    full = os.path.abspath(os.path.join(allowed, path))
    if not full.startswith(os.path.abspath(allowed)):
        return "Error: access denied"
    try:
        with open(full) as f:
            return f.read()[:4096]
    except Exception as e:
        return f"Error reading file: {e}"


def tool_web_fetch(url: str) -> str:
    """Fetch a URL and return its text content."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Cortex/0.1"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read().decode("utf-8", errors="replace")
        import re
        text = re.sub(r"<[^>]+>", " ", content)
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000]
    except Exception as e:
        return f"Error fetching {url}: {e}"


def make_tools(knowledge_base: dict | None = None) -> list[Tool]:
    return [
        Tool(
            name="current_time",
            description="Get the current date and time",
            parameters={
                "type": "object",
                "properties": {
                    "timezone": {"type": "string", "description": "Timezone (default: UTC)", "default": "UTC"}
                },
            },
            fn=tool_current_time,
        ),
        Tool(
            name="calculate",
            description="Evaluate a mathematical expression",
            parameters={
                "type": "object",
                "properties": {
                    "expression": {"type": "string", "description": "Math expression to evaluate"}
                },
                "required": ["expression"],
            },
            fn=tool_calculate,
        ),
        Tool(
            name="search",
            description="Search the knowledge base for relevant information",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"],
            },
            fn=lambda q: tool_search_kb(q, knowledge_base),
        ),
        Tool(
            name="read_file",
            description="Read a file from the workspace",
            parameters={
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Relative file path"}
                },
                "required": ["path"],
            },
            fn=tool_read_file,
        ),
        Tool(
            name="web_fetch",
            description="Fetch a URL and return its text content",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL to fetch"}
                },
                "required": ["url"],
            },
            fn=tool_web_fetch,
        ),
    ]


def format_tools_for_prompt(tools: list[Tool]) -> str:
    lines = ["Available tools:", ""]
    for t in tools:
        lines.append(f"  {t.name}: {t.description}")
        lines.append(f"    Parameters: {json.dumps(t.parameters, indent=2)}")
        lines.append("")
    return "\n".join(lines)
