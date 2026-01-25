"""
System prompt and prompt builder for AI diagnosis.

Per CONTEXT.md:
- Clinical/technical tone (SRE runbook style)
- Differential diagnosis style (ranked possibilities with evidence)
- "Insufficient data" is an acceptable conclusion

Per RESEARCH.md Pattern 4: Prompt structure that elicits reasoned,
evidence-based diagnosis.
"""

from operator_core.agent.context import DiagnosisContext


SYSTEM_PROMPT = """You are an expert SRE diagnosing issues in a TiKV distributed database cluster.

When analyzing a ticket violation, provide a differential diagnosis:

1. TIMELINE: What happened, in chronological order
2. AFFECTED COMPONENTS: Which stores, regions, or cluster-wide systems
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

Write in clinical/technical tone like an SRE runbook. Be precise, terse, metric-focused.
Reference specific metric values and thresholds. Show your reasoning."""


def build_diagnosis_prompt(context: DiagnosisContext) -> str:
    """Build structured prompt from diagnosis context.

    Creates a markdown-formatted prompt with sections:
    - Ticket details (invariant, store, message, timing)
    - Metrics at violation time
    - Cluster topology
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
- **Store:** {ticket.store_id or "cluster-wide"}
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

    # Cluster topology
    sections.append("## Cluster Topology\n")
    sections.append(f"- **Total stores:** {context.cluster_metrics.store_count}")
    sections.append(f"- **Total regions:** {context.cluster_metrics.region_count}")
    sections.append("")

    # Leader distribution
    if context.cluster_metrics.leader_count:
        sections.append("**Leader distribution:**")
        for store_id, count in context.cluster_metrics.leader_count.items():
            sections.append(f"- Store {store_id}: {count} leaders")
        sections.append("")

    # Store details
    sections.append("**Stores:**")
    for store in context.stores:
        sections.append(f"- Store {store.id} ({store.address}): {store.state}")
    sections.append("")

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

    return "\n".join(sections)
