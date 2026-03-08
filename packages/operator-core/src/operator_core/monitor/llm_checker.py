"""LLM-based invariant checker.

Uses Claude to assess system health from a rolling window of observations,
as an alternative to deterministic threshold-based checking.
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime
from typing import Any

import anthropic
from operator_protocols import InvariantViolation

logger = logging.getLogger(__name__)

DEFAULT_SYSTEM_PROMPT = """\
You are a distributed systems health assessor. You receive a rolling window \
of system observations (newest last). Each observation contains application \
metrics, connection pool state, database statistics, and endpoint latency data.

Analyze the observations for health issues. Consider:
- Connection pool saturation or rapid growth
- High or spiking P99 latency
- Database unreachability
- Excessive idle-in-transaction sessions (blocking autovacuum)
- Lock contention
- Table bloat / dead tuple accumulation (even on small tables)
- Error rate spikes
- Search endpoint degradation
- TRENDS across the window: degrading metrics, rapid changes, intermittent failures

Report ONLY issues you are confident about. Prefer fewer false positives over \
catching everything. Each issue needs an invariant_name (snake_case identifier), \
a descriptive message, a severity (critical/warning/info), and an optional \
store_id if the issue is scoped to a specific entity."""

VIOLATIONS_TOOL = {
    "name": "report_violations",
    "description": "Report detected health violations. Call with an empty list if the system appears healthy.",
    "input_schema": {
        "type": "object",
        "properties": {
            "violations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "invariant_name": {
                            "type": "string",
                            "description": "Snake_case identifier, e.g. pool_exhaustion, high_latency",
                        },
                        "message": {
                            "type": "string",
                            "description": "Human-readable description of the issue",
                        },
                        "severity": {
                            "type": "string",
                            "enum": ["critical", "warning", "info"],
                        },
                        "store_id": {
                            "type": "string",
                            "description": "Optional entity identifier",
                        },
                    },
                    "required": ["invariant_name", "message", "severity"],
                },
            },
        },
        "required": ["violations"],
    },
}


class LLMInvariantChecker:
    """InvariantCheckerProtocol implementation that uses an LLM to assess health.

    Maintains a rolling window of recent observations and sends them to Claude
    for health assessment on each check() call.
    """

    def __init__(
        self,
        model: str = "claude-haiku-4-5-20251001",
        window_size: int = 10,
        system_prompt: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._client = anthropic.Anthropic()
        self._model = model
        self._window: deque[tuple[str, dict[str, Any]]] = deque(maxlen=window_size)
        self._system_prompt = system_prompt or DEFAULT_SYSTEM_PROMPT
        self._timeout = timeout
        self._first_seen: dict[str, datetime] = {}

    def check(self, observation: dict[str, Any]) -> list[InvariantViolation]:
        """Check system health by sending observations to Claude."""
        now = datetime.now()
        self._window.append((now.isoformat(), observation))

        try:
            raw_violations = self._query_llm()
        except Exception as e:
            logger.warning(f"LLM checker failed: {e}")
            return []

        # Build InvariantViolation objects with first_seen tracking
        violations: list[InvariantViolation] = []
        seen_keys: set[str] = set()

        for v in raw_violations:
            name = v.get("invariant_name", "unknown")
            store_id = v.get("store_id")
            key = f"{name}:{store_id}" if store_id else name
            seen_keys.add(key)

            if key not in self._first_seen:
                self._first_seen[key] = now

            violations.append(
                InvariantViolation(
                    invariant_name=name,
                    message=v.get("message", ""),
                    first_seen=self._first_seen[key],
                    last_seen=now,
                    store_id=store_id,
                    severity=v.get("severity", "warning"),
                )
            )

        # Clear first_seen for violations that resolved
        for key in list(self._first_seen):
            if key not in seen_keys:
                del self._first_seen[key]

        return violations

    def _query_llm(self) -> list[dict[str, Any]]:
        """Send rolling window to Claude and parse structured response."""
        window_data = [
            {"timestamp": ts, "observation": obs} for ts, obs in self._window
        ]
        user_message = json.dumps(window_data, indent=2, default=str)

        response = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=self._system_prompt,
            tools=[VIOLATIONS_TOOL],
            tool_choice={"type": "tool", "name": "report_violations"},
            messages=[{"role": "user", "content": user_message}],
            timeout=self._timeout,
        )

        # Extract tool call result
        for block in response.content:
            if block.type == "tool_use" and block.name == "report_violations":
                return block.input.get("violations", [])

        return []
