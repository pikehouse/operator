# Quick Task 002: Enhance eval CLI and web viewer with chaos details

**Status:** Complete
**Commits:** 0aa256b, d6467aa, a650a17

## What was done

### CLI Enhancements (`eval/src/eval/cli.py`)

1. **Campaign show** now displays:
   - Human-readable chaos description (e.g., "Container killed with SIGKILL")
   - Trial status column (Success/Timeout)

2. **Trial show** now displays:
   - **Chaos Injection section**: type, target container, signal, latency params, disk fill %, blocked IPs
   - **Timing with deltas**: "+21s after chaos" for detection, "+80s to resolve" for resolution
   - **Commands extracted properly** from nested tool_params JSON

3. Added `get_chaos_description()` helper for human-readable chaos names

### Web Viewer Enhancements

**Campaign page** (`campaign.html`):
- Added chaos description in details section
- Added Status column (Success/Timeout badges) to trial table

**Trial page** (`trial.html`):
- Added "Chaos Injection" section (orange theme) with type, target, params
- Added "Monitor Detection" section (purple theme) showing violated invariant from operator.db
- Added timing deltas in timing section
- Commands now extracted from tool_params JSON

**Routes** (`routes.py`):
- Added `get_chaos_description()` helper
- Added `timing` dict with detect_seconds, resolve_seconds
- Added `chaos_meta` dict passed to template
- Added `monitor_detection` from querying tickets table in operator.db
- Preprocesses commands to extract from nested tool_params

## Files Modified

- `eval/src/eval/cli.py` — CLI enhancements, command extraction
- `eval/src/eval/viewer/routes.py` — Route enhancements, monitor detection query
- `eval/src/eval/viewer/templates/campaign.html` — Chaos description, status badges
- `eval/src/eval/viewer/templates/trial.html` — Chaos injection and monitor sections

## Example Output

```
Trial 4 (Campaign 4)
----------------------------------------
Chaos Injection:
  Type:   node_kill
  Target: tikv1
  Signal: SIGKILL

Timing:
  Started:        2026-01-30T14:47:51
  Chaos injected: 2026-01-30T14:47:51
  Ticket created: 2026-01-30T06:48:11 (+21s after chaos)
  Resolved:       2026-01-30T06:49:24 (+73s to resolve)
  Ended:          2026-01-30T14:49:25

Commands (11):
  1. docker ps | grep -E "pd|tikv"
  2. docker ps -a | grep tikv1
  ...
```
