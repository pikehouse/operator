"""
Pydantic models for structured AI diagnosis output.

Per CONTEXT.md: Diagnosis should read like an SRE would write it -
professional, metric-backed, actionable. The "options considered"
section is the core value - shows AI is actually reasoning, not
pattern matching.
"""

from pydantic import BaseModel, Field


class Alternative(BaseModel):
    """An alternative hypothesis considered during diagnosis.

    Per CONTEXT.md: Differential diagnosis style - ranked possibilities
    with supporting/contradicting evidence. Show top 2-3 alternatives
    alongside primary diagnosis.
    """

    hypothesis: str = Field(description="The alternative explanation")
    supporting: str = Field(description="Evidence supporting this hypothesis")
    contradicting: str = Field(description="Evidence contradicting this hypothesis")
    conclusion: str = Field(description="Why this was ruled out or kept")


class DiagnosisOutput(BaseModel):
    """Structured diagnosis output from Claude.

    Per CONTEXT.md:
    - Clinical/technical tone (SRE runbook style)
    - Nuanced confidence via natural language
    - Differential diagnosis with alternatives
    - Explicit severity levels
    """

    # Timeline and context (per CONTEXT.md structured sections)
    timeline: str = Field(
        description="Chronological sequence of events leading to violation"
    )
    affected_components: list[str] = Field(
        description="List of affected stores/regions/services"
    )
    metric_readings: dict[str, str] = Field(
        description="Key metric values at violation time"
    )

    # Primary diagnosis (nuanced confidence via natural language)
    primary_diagnosis: str = Field(
        description="Most likely root cause based on evidence"
    )
    confidence: str = Field(description="Confidence assessment in natural language")
    supporting_evidence: list[str] = Field(
        description="Evidence supporting primary diagnosis"
    )

    # Differential diagnosis (top 2-3 alternative hypotheses)
    alternatives_considered: list[Alternative] = Field(
        description="Top 2-3 alternative hypotheses with analysis"
    )

    # Recommended action (explicit severity, conceptual + commands)
    recommended_action: str = Field(description="What to do next (conceptual)")
    action_commands: list[str] = Field(
        description="Copy-paste ready CLI commands where applicable"
    )
    severity: str = Field(description="Critical / Warning / Info")
    risks: list[str] = Field(description="Potential risks of recommended action")


def format_diagnosis_markdown(diagnosis: DiagnosisOutput) -> str:
    """Convert DiagnosisOutput to human-readable markdown.

    Per CONTEXT.md: Store as markdown - human-readable first, render in CLI.
    Clinical/technical tone, SRE runbook style.
    """
    lines = []

    # Severity banner
    severity_icon = {
        "Critical": "[CRITICAL]",
        "Warning": "[WARNING]",
        "Info": "[INFO]",
    }.get(diagnosis.severity, f"[{diagnosis.severity.upper()}]")
    lines.append(f"## {severity_icon} Diagnosis")
    lines.append("")

    # Timeline
    lines.append("### Timeline")
    lines.append(diagnosis.timeline)
    lines.append("")

    # Affected components
    lines.append("### Affected Components")
    for component in diagnosis.affected_components:
        lines.append(f"- {component}")
    lines.append("")

    # Metric readings
    lines.append("### Metric Readings")
    for metric, value in diagnosis.metric_readings.items():
        lines.append(f"- **{metric}:** {value}")
    lines.append("")

    # Primary diagnosis
    lines.append("### Primary Diagnosis")
    lines.append(diagnosis.primary_diagnosis)
    lines.append("")
    lines.append(f"**Confidence:** {diagnosis.confidence}")
    lines.append("")
    lines.append("**Supporting Evidence:**")
    for evidence in diagnosis.supporting_evidence:
        lines.append(f"- {evidence}")
    lines.append("")

    # Alternatives considered (the core value per CONTEXT.md)
    lines.append("### Alternatives Considered")
    for i, alt in enumerate(diagnosis.alternatives_considered, 1):
        lines.append(f"**{i}. {alt.hypothesis}**")
        lines.append(f"- Supporting: {alt.supporting}")
        lines.append(f"- Contradicting: {alt.contradicting}")
        lines.append(f"- Conclusion: {alt.conclusion}")
        lines.append("")

    # Recommended action
    lines.append("### Recommended Action")
    lines.append(diagnosis.recommended_action)
    lines.append("")

    if diagnosis.action_commands:
        lines.append("**Commands:**")
        lines.append("```bash")
        for cmd in diagnosis.action_commands:
            lines.append(cmd)
        lines.append("```")
        lines.append("")

    # Risks
    if diagnosis.risks:
        lines.append("**Risks:**")
        for risk in diagnosis.risks:
            lines.append(f"- {risk}")
        lines.append("")

    return "\n".join(lines)
