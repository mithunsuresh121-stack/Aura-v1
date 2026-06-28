"""
Conversation memory and fact storage for the agent.

Three-tier memory:
  Episodic: recent conversation turns (sliding window, in-memory)
  Semantic: learned facts extracted from conversations (persistent)
  Procedural: tool-use patterns and skill embeddings (persistent)

Each memory type can be converted into task context for the hypernetwork,
influencing the generated LoRA adapters.
"""
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class ConversationMemory:
    """Sliding-window conversation history."""

    def __init__(self, max_turns: int = 20):
        self.max_turns = max_turns
        self.turns: list[dict[str, Any]] = []

    def add(self, role: str, content: str, metadata: dict | None = None):
        self.turns.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        })
        if len(self.turns) > self.max_turns:
            self.turns.pop(0)

    def recent(self, n: int = 5) -> list[dict]:
        return self.turns[-n:]

    def as_context(self, n: int = 5) -> str:
        turns = self.recent(n)
        return "\n".join(
            f"{t['role']}: {t['content']}" for t in turns
        )

    def clear(self):
        self.turns.clear()


class FactMemory:
    """Persistent semantic memory backed by SQLite."""

    def __init__(self, db_path: str = "memory.sqlite"):
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT UNIQUE,
                value TEXT,
                source TEXT,
                confidence REAL DEFAULT 1.0,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            )
        """)
        self._conn.commit()

    def store(self, key: str, value: str, source: str = "", confidence: float = 1.0):
        self._conn.execute(
            """INSERT INTO facts (key, value, source, confidence, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 source = excluded.source,
                 confidence = excluded.confidence,
                 updated_at = datetime('now')""",
            (key, value, source, confidence),
        )
        self._conn.commit()

    def recall(self, key: str) -> str | None:
        cursor = self._conn.execute("SELECT value FROM facts WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else None

    def search(self, query: str, limit: int = 10) -> list[dict]:
        cursor = self._conn.execute(
            "SELECT key, value, source, confidence FROM facts WHERE key LIKE ? OR value LIKE ? ORDER BY confidence DESC LIMIT ?",
            (f"%{query}%", f"%{query}%", limit),
        )
        return [
            {"key": row[0], "value": row[1], "source": row[2], "confidence": row[3]}
            for row in cursor.fetchall()
        ]

    def all_facts(self, limit: int = 50) -> list[dict]:
        cursor = self._conn.execute(
            "SELECT key, value, source, confidence, created_at FROM facts ORDER BY updated_at DESC LIMIT ?",
            (limit,),
        )
        return [
            {"key": row[0], "value": row[1], "source": row[2], "confidence": row[3], "created_at": row[4]}
            for row in cursor.fetchall()
        ]

    def close(self):
        self._conn.close()
