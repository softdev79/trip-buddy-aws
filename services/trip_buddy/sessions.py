"""Short-term chat memory per session: DynamoDB (with TTL) on AWS, a dict locally.

Only user/assistant text turns are stored. Tool calls are re-done each turn so prices stay fresh.
"""

from __future__ import annotations

import json
import os
import time

KEEP_LAST = 10                    # turns kept: the context window is not free
TTL_SECONDS = 24 * 60 * 60        # DynamoDB deletes a session a day after its last message


class SessionStore:
    def __init__(self, table_name: str | None = None):
        self.table_name = table_name if table_name is not None else os.getenv("SESSIONS_TABLE", "")
        self._memory: dict[str, list[dict]] = {}
        self._table = None
        if self.table_name:
            import boto3

            self._table = boto3.resource("dynamodb", region_name=os.getenv("AWS_REGION", "us-east-1")).Table(
                self.table_name
            )

    @property
    def backend(self) -> str:
        return "dynamodb" if self._table is not None else "memory"

    def load(self, session_id: str) -> list[dict]:
        if self._table is None:
            return list(self._memory.get(session_id, []))
        item = self._table.get_item(Key={"session_id": session_id}).get("Item")
        return json.loads(item["messages"]) if item else []

    def append(self, session_id: str, user: str, assistant: str) -> None:
        history = self.load(session_id)
        history += [{"role": "user", "content": user}, {"role": "assistant", "content": assistant}]
        history = history[-KEEP_LAST:]
        if self._table is None:
            self._memory[session_id] = history
            return
        self._table.put_item(Item={
            "session_id": session_id,
            "messages": json.dumps(history, ensure_ascii=False),
            "expires_at": int(time.time()) + TTL_SECONDS,
        })

    def clear(self, session_id: str) -> None:
        if self._table is None:
            self._memory.pop(session_id, None)
        else:
            self._table.delete_item(Key={"session_id": session_id})
