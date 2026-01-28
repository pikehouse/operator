"""
Session-level risk tracking for multi-action pattern detection (SAFE-07).

This module provides session-level risk tracking to detect suspicious patterns
across multiple actions:
- Cumulative risk scoring with time-windowed analysis
- Rapid action frequency detection (multiplier for speed)
- Privilege escalation pattern detection (restart+exec, repeated destructive)
- Risk level classification (LOW/MEDIUM/HIGH/CRITICAL)

The SessionRiskTracker accumulates risk across actions within a session,
applying contextual analysis to detect patterns that may indicate:
- Aggressive remediation (too many changes too quickly)
- Privilege escalation attempts (restart followed by shell access)
- Repeated destructive actions (multiple removals, restarts)

Per project patterns:
- Time-windowed scoring (actions older than 5 minutes decay)
- Pattern matching for known escalation sequences
- Four-tier risk levels with configurable thresholds
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import Enum
from typing import Any


class RiskLevel(str, Enum):
    """
    Risk levels for session activity.

    Based on cumulative risk scores, with thresholds defining transitions:
    - LOW: Normal operation, minor changes
    - MEDIUM: Multiple actions, moderate risk
    - HIGH: Significant changes, rapid actions
    - CRITICAL: Dangerous patterns detected
    """

    LOW = "low"
    """Normal operation, cumulative risk < 10."""

    MEDIUM = "medium"
    """Multiple actions, cumulative risk 10-24."""

    HIGH = "high"
    """Significant changes, cumulative risk 25-49."""

    CRITICAL = "critical"
    """Dangerous patterns, cumulative risk >= 50."""


# Base risk scores for different action types
ACTION_RISK_SCORES: dict[str, int] = {
    # Low risk (1-2)
    "get_status": 1,
    "list_stores": 1,
    "get_config": 1,
    "check_health": 1,

    # Medium risk (3-5)
    "transfer_leader": 3,
    "add_peer": 4,
    "remove_peer": 5,
    "update_config": 4,

    # High risk (6-10)
    "docker_restart": 6,
    "host_write_file": 7,
    "docker_exec": 8,
    "host_delete_file": 9,
    "reset_counter": 10,

    # Default for unknown actions
    "_default": 3,
}

# Risk level thresholds (cumulative score boundaries)
RISK_THRESHOLDS = {
    RiskLevel.LOW: 0,      # 0-9
    RiskLevel.MEDIUM: 10,  # 10-24
    RiskLevel.HIGH: 25,    # 25-49
    RiskLevel.CRITICAL: 50,  # 50+
}

# Time window for scoring (actions older than this decay)
SCORE_WINDOW = timedelta(minutes=5)

# Rapid action threshold (actions within this window get multiplier)
RAPID_THRESHOLD = timedelta(seconds=30)

# Frequency multiplier for rapid actions (applied when multiple actions in rapid succession)
RAPID_MULTIPLIER = 1.5

# Escalation patterns (action sequences that indicate privilege escalation)
ESCALATION_PATTERNS = [
    # Docker restart followed by exec (potential container escape)
    {"sequence": ["docker_restart", "docker_exec"], "bonus": 20},

    # Repeated destructive actions
    {"sequence": ["remove_peer", "remove_peer"], "bonus": 15},
    {"sequence": ["host_delete_file", "host_delete_file"], "bonus": 15},
]


class SessionRiskTracker:
    """
    Session-level risk tracker for multi-action pattern detection.

    Tracks cumulative risk across actions within a session, detecting:
    - Rapid action succession (frequency-based risk)
    - Escalation patterns (restart+exec, repeated destructive)
    - Overall session risk level

    Example:
        tracker = SessionRiskTracker("session-abc")

        # Add actions as they occur
        tracker.add_action("transfer_leader", {"region_id": 1})
        tracker.add_action("remove_peer", {"store_id": 123})

        # Calculate current risk
        score, level = tracker.calculate_risk_score()
        print(f"Risk: {level.value} (score={score})")
    """

    def __init__(self, session_id: str) -> None:
        """
        Initialize session risk tracker.

        Args:
            session_id: Unique identifier for this session
        """
        self.session_id = session_id
        self._action_history: list[dict[str, Any]] = []

    def add_action(self, action_name: str, parameters: dict[str, Any]) -> None:
        """
        Record an action in the session history.

        Args:
            action_name: Name of the action being performed
            parameters: Action parameters
        """
        self._action_history.append({
            "action_name": action_name,
            "parameters": parameters,
            "timestamp": datetime.now(),
        })

    def calculate_risk_score(self) -> tuple[int, RiskLevel]:
        """
        Calculate cumulative risk score and level for the session.

        Applies:
        - Base risk scores for each action
        - Time-windowed decay (only recent actions count)
        - Frequency multiplier for rapid actions
        - Pattern detection bonuses for escalation sequences

        Returns:
            Tuple of (cumulative_score, risk_level)
        """
        if not self._action_history:
            return 0, RiskLevel.LOW

        now = datetime.now()
        cutoff = now - SCORE_WINDOW

        # Filter to actions within time window
        recent_actions = [
            action for action in self._action_history
            if action["timestamp"] >= cutoff
        ]

        if not recent_actions:
            return 0, RiskLevel.LOW

        # Calculate base cumulative score
        base_score = sum(
            ACTION_RISK_SCORES.get(action["action_name"], ACTION_RISK_SCORES["_default"])
            for action in recent_actions
        )

        # Apply frequency multiplier for rapid actions
        rapid_count = 0
        for i in range(1, len(recent_actions)):
            time_diff = recent_actions[i]["timestamp"] - recent_actions[i-1]["timestamp"]
            if time_diff < RAPID_THRESHOLD:
                rapid_count += 1

        frequency_bonus = int(base_score * (RAPID_MULTIPLIER - 1.0)) if rapid_count >= 2 else 0

        # Detect escalation patterns
        pattern_bonus = 0
        action_names = [action["action_name"] for action in recent_actions]

        for pattern in ESCALATION_PATTERNS:
            sequence = pattern["sequence"]
            # Look for consecutive occurrences of the pattern
            for i in range(len(action_names) - len(sequence) + 1):
                window = action_names[i:i+len(sequence)]
                if window == sequence:
                    pattern_bonus += pattern["bonus"]

        # Total cumulative score
        total_score = base_score + frequency_bonus + pattern_bonus

        # Determine risk level based on thresholds
        risk_level = RiskLevel.LOW
        for level in [RiskLevel.CRITICAL, RiskLevel.HIGH, RiskLevel.MEDIUM, RiskLevel.LOW]:
            if total_score >= RISK_THRESHOLDS[level]:
                risk_level = level
                break

        return total_score, risk_level

    def get_action_history(self, limit: int | None = None) -> list[dict[str, Any]]:
        """
        Get recent action history.

        Args:
            limit: Maximum number of actions to return (most recent first)

        Returns:
            List of action records with timestamps
        """
        history = sorted(self._action_history, key=lambda x: x["timestamp"], reverse=True)
        if limit:
            history = history[:limit]
        return history
