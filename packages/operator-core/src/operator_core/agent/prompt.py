"""
System prompt and prompt builder for AI diagnosis.

Per CONTEXT.md:
- Clinical/technical tone (SRE runbook style)
- Differential diagnosis style (ranked possibilities with evidence)
- "Insufficient data" is an acceptable conclusion

Per RESEARCH.md Pattern 4: Prompt structure that elicits reasoned,
evidence-based diagnosis.
"""

import json
from typing import Any

from operator_core.agent.context import DiagnosisContext


SYSTEM_PROMPT = """You are an expert SRE diagnosing issues in a distributed system.

When analyzing a ticket violation, provide a differential diagnosis:

1. TIMELINE: What happened, in chronological order
2. AFFECTED COMPONENTS: Which nodes, services, or cluster-wide systems
3. METRIC READINGS: Key values at violation time

4. PRIMARY DIAGNOSIS: The most likely root cause
   - State your confidence in natural language ("The evidence strongly suggests...", "This could be...")
   - List supporting evidence (specific metrics, log entries)

5. ALTERNATIVES CONSIDERED: What else this could be
   - For each alternative, state supporting and contradicting evidence
   - Explain why you ruled it out (or didn't)
   - "Insufficient data" is acceptable - state what's missing

6. RECOMMENDED ACTION:
   - Severity: Critical / Warning / Info
   - Conceptual description of what to do
   - Copy-paste ready CLI commands where applicable
   - "Wait and observe" is a valid recommendation
   - ALWAYS include potential risks/side effects

7. STRUCTURED ACTIONS (recommended_actions):
   - If Available Actions are listed, use them in the recommended_actions field
   - CRITICAL: Fill in ALL required parameters from the observation data
   - Example: For reset_counter with key parameter, extract the counter key from the violation
   - The parameters dict must contain all required fields or the action will fail validation

Write in clinical/technical tone like an SRE runbook. Be precise, terse, metric-focused.
Reference specific metric values and thresholds. Show your reasoning."""


def _format_observation(observation: dict[str, Any]) -> str:
    """Format observation dict for display in prompt.

    Handles common observation structures (nodes, counters, etc.)
    in a readable way, with fallback to JSON for unknown structures.

    Args:
        observation: Observation dict from subject.observe()

    Returns:
        Formatted string for prompt
    """
    lines = []

    # Handle common keys with nice formatting
    if "nodes" in observation:
        lines.append("**Nodes:**")
        for node in observation["nodes"]:
            node_id = node.get("id", "?")
            address = node.get("address", "unknown")
            state = node.get("state", "unknown")
            lines.append(f"- {node_id} ({address}): {state}")
        lines.append("")

    if "counters" in observation:
        lines.append("**Counters:**")
        for counter in observation["counters"]:
            key = counter.get("key", "?")
            count = counter.get("count", 0)
            limit = counter.get("limit", 0)
            remaining = counter.get("remaining", 0)
            status = "OVER LIMIT" if count > limit else "OK"
            lines.append(f"- {key}: count={count}, limit={limit}, remaining={remaining} [{status}]")
        lines.append("")

    if "stores" in observation:
        lines.append("**Stores:**")
        for store in observation["stores"]:
            store_id = store.get("id", "?")
            address = store.get("address", "unknown")
            state = store.get("state", "unknown")
            lines.append(f"- Store {store_id} ({address}): {state}")
        lines.append("")

    if "redis_connected" in observation:
        status = "Connected" if observation["redis_connected"] else "DISCONNECTED"
        lines.append(f"**Redis:** {status}")
        lines.append("")

    # Format remaining keys as JSON
    handled_keys = {"nodes", "counters", "stores", "redis_connected", "node_metrics"}
    remaining = {k: v for k, v in observation.items() if k not in handled_keys}
    if remaining:
        lines.append("**Additional data:**")
        lines.append("```json")
        lines.append(json.dumps(remaining, indent=2, default=str))
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def build_diagnosis_prompt(context: DiagnosisContext) -> str:
    """Build structured prompt from diagnosis context.

    Creates a markdown-formatted prompt with sections:
    - Ticket details (invariant, component, message, timing)
    - Metrics at violation time
    - Current cluster observation
    - Recent logs (if available)
    - Similar past tickets

    Args:
        context: DiagnosisContext with all gathered information

    Returns:
        Markdown-formatted prompt string for Claude
    """
    sections = []

    # Ticket information
    ticket = context.ticket
    sections.append(f"""## Ticket

- **Invariant:** {ticket.invariant_name}
- **Component:** {ticket.store_id or "cluster-wide"}
- **Message:** {ticket.message}
- **First seen:** {ticket.first_seen_at}
- **Occurrences:** {ticket.occurrence_count}
""")

    # Metrics at violation time
    if context.metric_snapshot:
        sections.append("## Metrics at Violation Time\n")
        for key, value in context.metric_snapshot.items():
            sections.append(f"- **{key}:** {value}")
        sections.append("")

    # Current cluster observation (generic)
    sections.append("## Current Cluster State\n")
    if context.observation:
        sections.append(_format_observation(context.observation))
    else:
        sections.append("*No observation data available*\n")

    # Recent logs (if available)
    if context.log_tail:
        line_count = len(context.log_tail.splitlines())
        sections.append(f"## Recent Logs ({line_count} lines)\n")
        sections.append("```")
        sections.append(context.log_tail)
        sections.append("```")
        sections.append("")

    # Similar past tickets
    if context.similar_tickets:
        sections.append("## Similar Past Tickets\n")
        for t in context.similar_tickets:
            resolved_status = str(t.resolved_at) if t.resolved_at else "unresolved"
            sections.append(f"### Ticket {t.id} ({resolved_status})")
            sections.append(f"- **Message:** {t.message}")
            if t.diagnosis:
                # Truncate long diagnoses to first 300 chars
                diagnosis_preview = t.diagnosis[:300]
                if len(t.diagnosis) > 300:
                    diagnosis_preview += "..."
                sections.append(f"- **Diagnosis:** {diagnosis_preview}")
            else:
                sections.append("- **Diagnosis:** None")
            sections.append("")

    # Available actions (for structured recommendations)
    if context.action_definitions:
        sections.append("## Available Actions\n")
        sections.append("When recommending actions, use these exact action names and parameters:\n")
        for action in context.action_definitions:
            sections.append(f"### `{action.name}`")
            sections.append(f"- **Description:** {action.description}")
            if action.parameters:
                sections.append("- **Parameters:**")
                for param_name, param_def in action.parameters.items():
                    required = "required" if param_def.required else "optional"
                    sections.append(f"  - `{param_name}` ({param_def.type}, {required}): {param_def.description}")
            sections.append(f"- **Risk Level:** {action.risk_level}")
            sections.append("")

    return "\n".join(sections)
