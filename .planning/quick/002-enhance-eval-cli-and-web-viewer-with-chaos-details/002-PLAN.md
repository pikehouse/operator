---
phase: quick-002
wave: 1
autonomous: true
files_modified:
  - eval/src/eval/cli.py
  - eval/src/eval/viewer/routes.py
  - eval/src/eval/viewer/templates/campaign.html
  - eval/src/eval/viewer/templates/trial.html
---

# Quick Task 002: Enhance eval CLI and web viewer with chaos details

## Objective

Add detailed chaos/failure information to both CLI and web viewer outputs so users can understand:
- What type of failure was injected
- When it was injected
- What the monitor detected (violated invariant)
- What the agent did in response

## Tasks

<task id="1">
<title>Enhance CLI `show` command with chaos details</title>
<description>
Update the `eval show` command to display chaos metadata when showing campaigns and trials.

For campaigns:
- Show chaos_type with a human-readable description

For trials:
- Parse and display chaos_metadata JSON (target container, signal, latency params, etc.)
- Show time between chaos injection and ticket creation
- Show time between ticket creation and resolution

Example output for trial:
```
Trial 3 (Campaign 3)
----------------------------------------
Chaos Injected:
  Type: node_kill
  Target: tikv1
  Signal: SIGKILL

Timing:
  Started:        2026-01-30T14:28:39
  Chaos injected: 2026-01-30T14:28:39
  Ticket created: 2026-01-30T14:29:00 (+21s after chaos)
  Resolved:       2026-01-30T14:30:20 (+80s to resolve)
  Ended:          2026-01-30T14:30:20

Commands: (14)
  1. docker ps
  ...
```
</description>
<verification>
- `eval show 3` displays chaos metadata section
- `eval show --trial 3` displays chaos details with timing deltas
</verification>
</task>

<task id="2">
<title>Enhance web viewer trial page with chaos and monitor details</title>
<description>
Update trial.html template and routes.py to show:
1. A "Chaos Injection" section showing the parsed chaos_metadata
2. The monitor's violated invariant from operator.db tickets table

For the violated invariant:
- Query operator.db tickets table for the ticket matching this trial's time window
- Extract the violation_type and violation_details fields
- Display in a "Monitor Detection" section

Add to routes.py:
- Query tickets table from operator.db to get violation info
</description>
<verification>
- Trial page shows "Chaos Injection" section with target, type, params
- Trial page shows "Monitor Detection" section with what invariant was violated
</verification>
</task>

<task id="3">
<title>Enhance web viewer campaign page with chaos summary</title>
<description>
Update campaign.html template to show:
1. A brief chaos description in the campaign details section
2. For each trial in the table, show a status indicator (success/failure/timeout)

Add chaos type descriptions:
- node_kill: "Container killed with SIGKILL"
- latency: "Network latency injected (X-Yms)"
- disk_pressure: "Disk filled to X%"
- network_partition: "Network partition from peers"
</description>
<verification>
- Campaign page shows human-readable chaos description
- Trial table shows outcome status column
</verification>
</task>

## must_haves

- [ ] CLI `eval show <campaign>` displays chaos_type description
- [ ] CLI `eval show --trial <id>` displays parsed chaos_metadata and timing deltas
- [ ] Web trial page shows "Chaos Injection" section with metadata
- [ ] Web trial page shows "Monitor Detection" section with violated invariant
- [ ] Web campaign page shows chaos description and trial outcomes
