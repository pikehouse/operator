# Phase 5: AI Diagnosis - Research

**Researched:** 2026-01-24
**Domain:** Anthropic SDK for Python + Agent Runner + Structured Diagnosis Output
**Confidence:** HIGH

## Summary

This phase implements Claude-powered diagnosis of monitoring tickets. When invariant violations occur, an agent runner picks up undiagnosed tickets, gathers relevant context (metrics, logs, topology, ticket history), invokes Claude with a structured prompt, and stores the diagnosis as markdown. The diagnosis follows a differential diagnosis pattern: primary conclusion with supporting evidence, alternatives considered with reasons for rejection, and actionable recommendations with risks.

The implementation uses the Anthropic Python SDK with structured outputs (beta feature) to guarantee valid JSON responses from Claude. The agent runner follows the same asyncio patterns established in Phase 4's monitor loop: a background daemon that polls for undiagnosed tickets and processes them sequentially. Per CONTEXT.md decisions, diagnoses are stored as human-readable markdown and output includes explicit severity levels, copy-paste ready CLI commands, and risk warnings.

**Primary recommendation:** Use `anthropic` Python SDK with `client.beta.messages.parse()` for structured output extraction. Define diagnosis schema using Pydantic models. Agent runner polls for tickets in `status='open'` and transitions them to `status='diagnosed'` after Claude analysis.

## Standard Stack

The established libraries/tools for this domain:

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| anthropic | latest | Claude API client | Official Anthropic Python SDK; async support, structured outputs, Pydantic integration |
| pydantic | 2.0+ | Schema definitions | Already in project; SDK uses for structured output parsing |
| aiosqlite | 0.20+ | Async ticket DB | Already in project; agent runner updates tickets |
| asyncio | stdlib | Event loop | Already in project; same daemon pattern as monitor loop |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| httpx | 0.27+ | HTTP client | Already in project; fetch log tails from containers |
| json | stdlib | JSON serialization | Metrics snapshot parsing, context assembly |
| textwrap | stdlib | Text formatting | Markdown formatting for diagnosis output |
| datetime | stdlib | Timestamps | Diagnosis timestamps, timing calculations |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| anthropic SDK | LangChain | Adds unnecessary abstraction layer; direct SDK is simpler and more explicit |
| Pydantic structured output | Raw JSON schema | Pydantic provides type safety and validation; SDK directly supports Pydantic models |
| Polling agent | Event-driven | Polling is simpler, consistent with monitor loop pattern; event-driven would require message queue |

**Installation:**
```bash
pip install anthropic
# Other deps (pydantic, aiosqlite) already present
```

## Architecture Patterns

### Recommended Project Structure
```
packages/operator-core/src/operator_core/
    agent/
        __init__.py
        runner.py           # AgentRunner class: poll & process tickets
        context.py          # Context gathering: metrics, logs, history
        diagnosis.py        # DiagnosisSchema Pydantic models
        prompt.py           # System prompt and template construction
    cli/
        agent.py            # agent command (daemon or single-run)
```

### Pattern 1: Structured Output with Pydantic
**What:** Define diagnosis schema as Pydantic model, use SDK's parse() method
**When to use:** All Claude API calls that require structured responses
**Example:**
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
from pydantic import BaseModel, Field
from anthropic import AsyncAnthropic

class DiagnosisOutput(BaseModel):
    """Structured diagnosis from Claude."""

    timeline: str = Field(description="Chronological sequence of events")
    affected_components: list[str] = Field(description="List of affected stores/regions")
    metric_readings: dict[str, str] = Field(description="Key metric values at violation time")

    primary_diagnosis: str = Field(description="Most likely root cause")
    confidence: str = Field(description="Confidence assessment in natural language")
    supporting_evidence: list[str] = Field(description="Evidence supporting primary diagnosis")

    alternatives_considered: list[dict] = Field(
        description="Other hypotheses with supporting/contradicting evidence"
    )

    recommended_action: str = Field(description="What to do next")
    action_commands: list[str] = Field(description="Copy-paste ready CLI commands")
    severity: str = Field(description="Critical / Warning / Info")
    risks: list[str] = Field(description="Potential risks of recommended action")

client = AsyncAnthropic()

response = await client.beta.messages.parse(
    model="claude-sonnet-4-5",
    max_tokens=4096,
    betas=["structured-outputs-2025-11-13"],
    messages=[
        {"role": "user", "content": diagnosis_prompt}
    ],
    output_format=DiagnosisOutput,
)

diagnosis = response.parsed_output  # Type: DiagnosisOutput
```

### Pattern 2: Agent Runner Daemon Loop
**What:** Background daemon that polls for undiagnosed tickets and processes them
**When to use:** The `operator agent` command
**Example:**
```python
# Source: Based on Phase 4 MonitorLoop pattern
import asyncio
import functools
import signal

class AgentRunner:
    """Daemon that processes tickets through Claude diagnosis."""

    def __init__(
        self,
        db_path: Path,
        anthropic_client: AsyncAnthropic,
        context_gatherer: ContextGatherer,
        poll_interval: float = 10.0,
    ):
        self.db_path = db_path
        self.client = anthropic_client
        self.context = context_gatherer
        self.poll_interval = poll_interval
        self._shutdown = asyncio.Event()

    async def run(self) -> None:
        """Run agent loop until shutdown signal."""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(
                sig,
                functools.partial(self._handle_signal, sig)
            )

        print(f"Agent runner starting (poll interval: {self.poll_interval}s)")

        async with TicketDB(self.db_path) as db:
            while not self._shutdown.is_set():
                await self._process_cycle(db)

                try:
                    await asyncio.wait_for(
                        self._shutdown.wait(),
                        timeout=self.poll_interval,
                    )
                except asyncio.TimeoutError:
                    pass

        print("Agent runner stopped")

    async def _process_cycle(self, db: TicketDB) -> None:
        """Process one batch of undiagnosed tickets."""
        tickets = await db.list_tickets(status=TicketStatus.OPEN)

        for ticket in tickets:
            if self._shutdown.is_set():
                break
            await self._diagnose_ticket(db, ticket)
```

### Pattern 3: Context Assembly
**What:** Gather all relevant information before invoking Claude
**When to use:** Before every diagnosis API call
**Example:**
```python
# Per CONTEXT.md decisions: snapshot + logs + history + topology
class ContextGatherer:
    """Assembles diagnosis context from multiple sources."""

    def __init__(self, subject: TiKVSubject, db: TicketDB):
        self.subject = subject
        self.db = db

    async def gather(self, ticket: Ticket) -> DiagnosisContext:
        """Gather all context for diagnosing a ticket."""

        # Metric snapshot at violation time (from ticket)
        metric_snapshot = ticket.metric_snapshot or {}

        # Current cluster topology
        stores = await self.subject.get_stores()
        cluster_metrics = await self.subject.get_cluster_metrics()

        # Raw log tail (last N lines from affected component)
        log_tail = await self._fetch_log_tail(ticket.store_id)

        # Similar ticket history (past diagnoses for same invariant)
        similar_tickets = await self._find_similar_tickets(ticket)

        return DiagnosisContext(
            ticket=ticket,
            metric_snapshot=metric_snapshot,
            stores=stores,
            cluster_metrics=cluster_metrics,
            log_tail=log_tail,
            similar_tickets=similar_tickets,
        )
```

### Pattern 4: Differential Diagnosis Prompt
**What:** Prompt structure that elicits reasoned, evidence-based diagnosis
**When to use:** System prompt for all diagnoses
**Example:**
```python
SYSTEM_PROMPT = """You are an expert SRE diagnosing issues in a TiKV distributed database cluster.

When analyzing a ticket violation, provide a differential diagnosis:

1. TIMELINE: What happened, in chronological order
2. AFFECTED COMPONENTS: Which stores, regions, or cluster-wide
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
Reference specific metric values and thresholds. Show your reasoning.
"""
```

### Pattern 5: Diagnosis Storage as Markdown
**What:** Convert structured output to human-readable markdown for storage
**When to use:** After receiving Claude response, before updating ticket
**Example:**
```python
def format_diagnosis_markdown(d: DiagnosisOutput) -> str:
    """Convert structured diagnosis to markdown for storage."""

    lines = [
        f"# Diagnosis",
        f"",
        f"**Severity:** {d.severity}",
        f"**Confidence:** {d.confidence}",
        f"",
        f"## Timeline",
        f"",
        d.timeline,
        f"",
        f"## Affected Components",
        f"",
    ]

    for component in d.affected_components:
        lines.append(f"- {component}")

    lines.extend([
        f"",
        f"## Metric Readings",
        f"",
    ])

    for metric, value in d.metric_readings.items():
        lines.append(f"- **{metric}:** {value}")

    lines.extend([
        f"",
        f"## Primary Diagnosis",
        f"",
        d.primary_diagnosis,
        f"",
        f"### Supporting Evidence",
        f"",
    ])

    for evidence in d.supporting_evidence:
        lines.append(f"- {evidence}")

    lines.extend([
        f"",
        f"## Alternatives Considered",
        f"",
    ])

    for alt in d.alternatives_considered:
        lines.append(f"### {alt.get('hypothesis', 'Unknown')}")
        lines.append(f"")
        lines.append(f"**Supports:** {alt.get('supporting', 'None')}")
        lines.append(f"")
        lines.append(f"**Contradicts:** {alt.get('contradicting', 'None')}")
        lines.append(f"")
        lines.append(f"**Conclusion:** {alt.get('conclusion', 'Ruled out')}")
        lines.append(f"")

    lines.extend([
        f"## Recommended Action",
        f"",
        d.recommended_action,
        f"",
    ])

    if d.action_commands:
        lines.append(f"### Commands")
        lines.append(f"")
        lines.append(f"```bash")
        for cmd in d.action_commands:
            lines.append(cmd)
        lines.append(f"```")
        lines.append(f"")

    lines.extend([
        f"### Risks",
        f"",
    ])

    for risk in d.risks:
        lines.append(f"- {risk}")

    return "\n".join(lines)
```

### Anti-Patterns to Avoid
- **Blocking API calls:** Always use AsyncAnthropic, never sync client in async code
- **Missing timeout:** Set reasonable max_tokens and consider request timeout for stuck calls
- **No error handling:** Claude may refuse or hit token limits; handle stop_reason appropriately
- **Hardcoded model:** Make model configurable; avoid coupling to specific version
- **Processing all tickets at once:** Process one at a time to avoid rate limits and allow interruption

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JSON schema validation | Manual dict checking | Pydantic with SDK parse() | SDK handles validation, type conversion |
| API client | Raw httpx to Claude | anthropic SDK | Handles auth, headers, retries, beta features |
| Structured output parsing | Regex on text | SDK structured outputs | Guaranteed valid JSON, type-safe |
| Prompt engineering | Ad-hoc string building | Template with clear sections | Consistent, maintainable, testable |
| Rate limiting | Manual sleep | SDK built-in retry | Handles 429s correctly |

**Key insight:** The Anthropic SDK's structured output feature (beta) eliminates the need for manual JSON parsing and validation. Using Pydantic models ensures type safety and makes the diagnosis schema explicit in code.

## Common Pitfalls

### Pitfall 1: Ignoring stop_reason
**What goes wrong:** Code assumes Claude always completes successfully
**Why it happens:** Happy path testing only
**How to avoid:** Check `response.stop_reason` for "refusal" or "max_tokens"
**Warning signs:** Partial diagnoses, schema validation failures

### Pitfall 2: Context Too Large for Context Window
**What goes wrong:** Token limit exceeded, diagnosis fails
**Why it happens:** Gathering too much log history or metric data
**How to avoid:** Limit log tail to ~100 lines; limit similar tickets to 3-5; summarize metrics
**Warning signs:** 400 errors, truncated responses

### Pitfall 3: Synchronous Anthropic Client in Async Code
**What goes wrong:** Blocks event loop during API call
**Why it happens:** Using `Anthropic()` instead of `AsyncAnthropic()`
**How to avoid:** Always use `AsyncAnthropic` in async code; lint for sync imports
**Warning signs:** Heartbeats stop during diagnosis, unresponsive shutdown

### Pitfall 4: No Graceful Degradation for API Failures
**What goes wrong:** Single API error crashes entire agent loop
**Why it happens:** Missing try/except around Claude calls
**How to avoid:** Catch API errors, log, skip ticket, continue loop
**Warning signs:** Agent dies on transient network issues

### Pitfall 5: Grammar Compilation Latency
**What goes wrong:** First request with new schema is slow
**Why it happens:** Structured outputs compile grammar on first use (cached 24h)
**How to avoid:** Expect ~1-2s additional latency on first call; don't treat as timeout
**Warning signs:** First diagnosis much slower than subsequent ones

### Pitfall 6: API Key in Code
**What goes wrong:** Key exposed in repo
**Why it happens:** Hardcoding for testing
**How to avoid:** Use `ANTHROPIC_API_KEY` environment variable; SDK reads it automatically
**Warning signs:** Key in git history

### Pitfall 7: Over-Complicated Alternatives Analysis
**What goes wrong:** Claude lists 10+ alternatives, diagnosis becomes unwieldy
**Why it happens:** Prompt doesn't constrain alternatives count
**How to avoid:** Explicitly request "top 2-3 alternatives" in prompt
**Warning signs:** Diagnoses taking too long, excessive token usage

## Code Examples

Verified patterns from official sources:

### AsyncAnthropic with Structured Output
```python
# Source: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
import os
from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

class DiagnosisOutput(BaseModel):
    primary_diagnosis: str
    confidence: str
    supporting_evidence: list[str]
    alternatives_considered: list[dict]
    recommended_action: str
    severity: str
    risks: list[str]

async def diagnose_ticket(ticket: Ticket, context: str) -> DiagnosisOutput:
    client = AsyncAnthropic()  # Uses ANTHROPIC_API_KEY env var

    response = await client.beta.messages.parse(
        model="claude-sonnet-4-5",
        max_tokens=4096,
        betas=["structured-outputs-2025-11-13"],
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": f"Diagnose this ticket:\n\n{ticket.message}\n\nContext:\n{context}"
            }
        ],
        output_format=DiagnosisOutput,
    )

    # Check for refusal or truncation
    if response.stop_reason == "refusal":
        raise DiagnosisRefusedError("Claude refused to diagnose this ticket")
    if response.stop_reason == "max_tokens":
        raise DiagnosisTruncatedError("Diagnosis was truncated")

    return response.parsed_output
```

### Ticket Update with Diagnosis
```python
# Extension to existing TicketDB
async def update_ticket_diagnosis(
    self,
    ticket_id: int,
    diagnosis: str,
) -> None:
    """
    Update ticket with AI diagnosis and transition status.

    Args:
        ticket_id: The ticket to update
        diagnosis: Markdown-formatted diagnosis text
    """
    await self._conn.execute(
        """
        UPDATE tickets SET
            diagnosis = ?,
            status = 'diagnosed'
        WHERE id = ?
        """,
        (diagnosis, ticket_id),
    )
    await self._conn.commit()
```

### Context Assembly for Prompt
```python
def build_diagnosis_prompt(context: DiagnosisContext) -> str:
    """Build the full diagnosis prompt from context."""

    sections = []

    # Ticket information
    sections.append(f"""## Ticket
- **Invariant:** {context.ticket.invariant_name}
- **Store:** {context.ticket.store_id or "cluster-wide"}
- **Message:** {context.ticket.message}
- **First seen:** {context.ticket.first_seen_at}
- **Occurrences:** {context.ticket.occurrence_count}
""")

    # Metric snapshot
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

    for store in context.stores:
        sections.append(f"- Store {store.id} ({store.address}): {store.state}")
    sections.append("")

    # Log tail
    if context.log_tail:
        sections.append(f"## Recent Logs ({len(context.log_tail.splitlines())} lines)\n")
        sections.append("```")
        sections.append(context.log_tail)
        sections.append("```")
        sections.append("")

    # Similar tickets
    if context.similar_tickets:
        sections.append("## Similar Past Tickets\n")
        for t in context.similar_tickets[:3]:  # Limit to 3
            sections.append(f"### Ticket {t.id} ({t.resolved_at or 'unresolved'})")
            sections.append(f"- **Diagnosis:** {t.diagnosis[:200] if t.diagnosis else 'None'}...")
            sections.append("")

    return "\n".join(sections)
```

### Error Handling in Agent Loop
```python
async def _diagnose_ticket(self, db: TicketDB, ticket: Ticket) -> None:
    """Diagnose a single ticket with error handling."""

    print(f"Diagnosing ticket {ticket.id}: {ticket.invariant_name}")

    try:
        # Gather context
        context = await self.context.gather(ticket)
        prompt = build_diagnosis_prompt(context)

        # Invoke Claude
        diagnosis_output = await diagnose_ticket(ticket, prompt)

        # Format and store
        diagnosis_md = format_diagnosis_markdown(diagnosis_output)
        await db.update_ticket_diagnosis(ticket.id, diagnosis_md)

        print(f"Ticket {ticket.id} diagnosed (severity: {diagnosis_output.severity})")

    except anthropic.APIConnectionError as e:
        print(f"API connection error for ticket {ticket.id}: {e}")
        # Don't update ticket, will retry next cycle

    except anthropic.RateLimitError as e:
        print(f"Rate limited, backing off: {e}")
        await asyncio.sleep(60)  # Back off before continuing

    except (DiagnosisRefusedError, DiagnosisTruncatedError) as e:
        print(f"Diagnosis incomplete for ticket {ticket.id}: {e}")
        # Store partial result or mark as needing manual review
        await db.update_ticket_diagnosis(
            ticket.id,
            f"# Diagnosis Error\n\n{e}"
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON parsing | SDK structured outputs (beta) | Nov 2025 | Guaranteed valid JSON, type safety |
| Prompt-only JSON | Constrained decoding | Nov 2025 | No more parsing errors |
| OpenAI compatibility layer | Native Anthropic SDK | Ongoing | Better feature support, async |
| Static prompts | Dynamic context assembly | 2024+ | Better diagnosis quality |

**Deprecated/outdated:**
- `json_mode` parameter: Use `output_format` with `json_schema` type instead
- `client.messages` for structured output: Use `client.beta.messages.parse()` for automatic validation
- Synchronous client in async code: Always use `AsyncAnthropic`

## Open Questions

Things that couldn't be fully resolved:

1. **Optimal log tail length**
   - What we know: CONTEXT.md says "last N lines"
   - What's unclear: What should N be? Too few loses context, too many hits token limits
   - Recommendation: Start with 50 lines, make configurable, adjust based on token usage

2. **Similar ticket definition**
   - What we know: Same invariant/store combination
   - What's unclear: Time window? How to rank similarity?
   - Recommendation: Same invariant_name within last 7 days, ordered by resolved_at DESC

3. **Rate limiting strategy**
   - What we know: SDK handles 429 with retries
   - What's unclear: Should we self-limit to avoid bursts?
   - Recommendation: Process tickets sequentially; add configurable delay between tickets if needed

4. **Model selection**
   - What we know: claude-sonnet-4-5 supports structured outputs
   - What's unclear: Opus vs Sonnet tradeoff for diagnosis quality
   - Recommendation: Default to Sonnet for cost efficiency, make model configurable

5. **Token budget per diagnosis**
   - What we know: max_tokens controls output length
   - What's unclear: What's reasonable for a diagnosis?
   - Recommendation: 4096 tokens output, track actual usage, adjust if consistently truncating

## Sources

### Primary (HIGH confidence)
- [Anthropic Python SDK GitHub](https://github.com/anthropics/anthropic-sdk-python) - Installation, async client, basic usage
- [Anthropic Structured Outputs Docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) - Beta feature, Pydantic integration, parse() method

### Secondary (MEDIUM confidence)
- [Python asyncio Event Loop documentation](https://docs.python.org/3/library/asyncio-eventloop.html) - Signal handling for daemon
- Existing Phase 4 MonitorLoop code - Agent runner follows same pattern

### Tertiary (LOW confidence)
- Web search on AI SRE patterns - Confirms differential diagnosis approach is industry standard
- Web search on agentic workflows - Confirms polling pattern is common for agent runners

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - Official Anthropic SDK with documented beta feature
- Architecture: HIGH - Follows established patterns from Phase 4; SDK examples verified
- Pitfalls: MEDIUM - Based on SDK docs warnings and common async patterns
- Diagnosis schema: MEDIUM - Based on CONTEXT.md decisions, may need refinement

**Research date:** 2026-01-24
**Valid until:** 2026-02-07 (14 days - SDK is stable but structured outputs is beta)
