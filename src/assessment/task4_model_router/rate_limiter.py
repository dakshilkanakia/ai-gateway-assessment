"""SQLite-backed exact sliding-window token rate limiter."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    used_tokens: int
    remaining_tokens: int
    retry_after_seconds: float = 0.0


class SqliteTokenRateLimiter:
    def __init__(
        self,
        database: str | Path,
        *,
        limit: int = 50_000,
        window_seconds: float = 60.0,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.database = str(database)
        self.limit = limit
        self.window_seconds = window_seconds
        self._clock = clock
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=5.0, isolation_level=None)
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS token_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_key TEXT NOT NULL,
                    occurred_at REAL NOT NULL,
                    tokens INTEGER NOT NULL CHECK(tokens > 0)
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_events_tenant_time "
                "ON token_events(tenant_key, occurred_at)"
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_token_events_time "
                "ON token_events(occurred_at)"
            )

    async def consume(self, tenant_key: str, tokens: int) -> LimitDecision:
        if tokens <= 0:
            raise ValueError("tokens must be positive")
        return await asyncio.to_thread(self._consume_sync, tenant_key, tokens, self._clock())

    def _consume_sync(self, tenant_key: str, tokens: int, now: float) -> LimitDecision:
        cutoff = now - self.window_seconds
        connection = self._connect()
        try:
            # Serializing the short read-check-write transaction makes admission
            # atomic across coroutines and separate gateway worker processes.
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "DELETE FROM token_events WHERE occurred_at <= ?",
                (cutoff,),
            )
            row = connection.execute(
                "SELECT COALESCE(SUM(tokens), 0), MIN(occurred_at) "
                "FROM token_events WHERE tenant_key = ?",
                (tenant_key,),
            ).fetchone()
            used, oldest = int(row[0]), row[1]
            if used + tokens > self.limit:
                retry_after = (
                    max(0.0, float(oldest) + self.window_seconds - now)
                    if oldest is not None
                    else self.window_seconds
                )
                connection.commit()
                return LimitDecision(False, used, max(0, self.limit - used), retry_after)
            connection.execute(
                "INSERT INTO token_events(tenant_key, occurred_at, tokens) VALUES (?, ?, ?)",
                (tenant_key, now, tokens),
            )
            connection.commit()
            new_used = used + tokens
            return LimitDecision(True, new_used, self.limit - new_used)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

