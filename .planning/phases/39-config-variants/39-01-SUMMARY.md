---
phase: 39
plan: 01
subsystem: eval-harness
tags: [configuration, variants, pydantic, yaml, cli]
requires: [38-02]
provides:
  - VariantConfig Pydantic model for agent configuration
  - Variant loading and discovery system (YAML-based)
  - Default variant with current agent configuration
  - list-variants CLI command
affects: [39-02]
tech-stack:
  added: []
  patterns:
    - Pydantic BaseModel for YAML validation
    - Variant directory convention (eval/variants/)
    - CLI table formatting with Rich
decisions:
  - Use Pydantic for variant validation with no runtime model checking
  - Store variants as individual YAML files in eval/variants/
  - tools_config structure: tool_choice and enabled_tools fields
  - Variant discovery via glob pattern matching
key-files:
  created:
    - eval/src/eval/types.py: VariantConfig model
    - eval/src/eval/variants.py: Variant loading/discovery module
    - eval/variants/default.yaml: Default variant configuration
  modified:
    - eval/src/eval/cli.py: Added list-variants command
duration: 185s
completed: 2026-01-30
---

# Phase 39 Plan 01: Config Variants Summary

**One-liner:** Pydantic-validated YAML variant system with discovery and CLI listing for agent A/B testing.

## What Was Built

Created a complete variant configuration system for A/B testing different agent configurations:

1. **VariantConfig Pydantic Model** (`eval/src/eval/types.py`)
   - Fields: name, model, system_prompt, tools_config
   - No runtime model validation - allows testing with new models
   - Validates structure only, not model availability

2. **Variant Loading Module** (`eval/src/eval/variants.py`)
   - `load_variant_config()` - Load single variant from YAML
   - `load_all_variants()` - Discover all variants in directory
   - `get_variant()` - Get specific variant by name
   - VARIANTS_DIR auto-detection relative to eval package

3. **Default Variant** (`eval/variants/default.yaml`)
   - Uses claude-opus-4-20250514 model
   - Current SRE operator system prompt from prompts.py
   - tool_choice: auto with shell tool enabled

4. **list-variants CLI Command** (`eval/src/eval/cli.py`)
   - Rich table display with name, model, prompt preview, tools
   - JSON output mode with --json flag
   - Custom variants directory support via --dir flag
   - Shows variant count and "No variants found" handling

## Architecture

```
eval/
├── variants/               # YAML variant files
│   └── default.yaml       # Current agent config
└── src/eval/
    ├── types.py           # VariantConfig Pydantic model
    ├── variants.py        # Loading/discovery functions
    └── cli.py             # list-variants command
```

**Key patterns:**
- Pydantic BaseModel for YAML schema validation
- Glob-based variant discovery (*.yaml files)
- Rich library for formatted table output
- Convention: variant name must match YAML filename

## Decisions Made

### Technical Decisions

1. **No model validation in Pydantic**
   - Rationale: Allows testing with new models without code changes
   - Impact: Runtime errors if invalid model used (acceptable for eval harness)

2. **Inline system prompts in YAML**
   - Alternative: File path references
   - Rationale: Self-contained variant files, easier version control
   - Used YAML block scalar syntax (|) for multi-line prompts

3. **tools_config structure**
   - Fields: `tool_choice` (string), `enabled_tools` (list)
   - Maps to Anthropic API parameters
   - Extensible for future tool configuration options

4. **Variant discovery via VARIANTS_DIR**
   - Path: `eval/variants/` (relative to eval package)
   - Convention: One YAML file per variant
   - Skips invalid files silently (graceful degradation)

5. **Rich Table vs plain text**
   - Used Rich for consistency with existing CLI commands
   - Provides better visual hierarchy and readability
   - JSON mode for programmatic access

## Deviations from Plan

None - plan executed exactly as written.

## Test Evidence

All verification checks passed:

1. ✅ VariantConfig imports and validates successfully
2. ✅ load_all_variants() returns ['default']
3. ✅ list-variants displays formatted table with default variant
4. ✅ list-variants --json outputs structured JSON

**Example CLI output:**
```
Available Variants
┏━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Name    ┃ Model                  ┃ System Prompt Preview       ┃ Tools ┃
┡━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ default │ claude-opus-4-20250514 │ You are an SRE operator...  │ shell │
└─────────┴────────────────────────┴─────────────────────────────┴───────┘
```

## Next Phase Readiness

**Blockers:** None

**For 39-02 (Campaign Variant Integration):**
- VariantConfig model ready for campaign YAML schema extension
- load_variant_config() can be called during campaign setup
- Default variant ensures backward compatibility

**Integration Points:**
- Campaign YAML will add `variant: <name>` field
- Campaign runner will call `get_variant()` before trials
- Trial records will store variant_name for comparison queries

**Open Questions:**
- How to pass variant config to agent loop? (env vars, function params, or global config)
- Should campaign validation fail if variant not found, or fall back to default?

## Performance Notes

- Duration: 185 seconds (3m 5s)
- All tasks completed in sequence with atomic commits
- No performance concerns - YAML loading is negligible overhead

## Knowledge for Future Phases

1. **Variant path calculation:**
   - `Path(__file__).parent.parent.parent / "variants"` from variants.py
   - Points to `eval/variants/` directory

2. **Default variant matching:**
   - Campaign YAML can omit `variant` field
   - Falls back to variant named "default"
   - default.yaml must exist for backward compatibility

3. **tools_config extensibility:**
   - Currently: tool_choice and enabled_tools
   - Future: Could add per-tool parameters, timeouts, etc.
   - Schema is flexible dict[str, Any]

4. **CLI patterns:**
   - Rich Table for human-readable output
   - JSON mode for scripting/automation
   - Optional path overrides with sensible defaults

---

**Phase:** 39-config-variants
**Plan:** 01
**Status:** ✅ COMPLETE
**Completed:** 2026-01-30
