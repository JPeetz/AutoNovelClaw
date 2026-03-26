# CLAUDE.md — AutoNovelClaw

## What This Is
Autonomous novel-writing pipeline. Takes a story idea, generates a complete novel with world-building, chapter-by-chapter writing with five-sense immersion, independent AI review, surgical enhancement loops, continuity tracking, and KDP-ready EPUB/PDF output.

## Quick Start
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Default: uses your Claude subscription via Claude Code CLI (no API key needed)
novelclaw doctor           # pre-flight checks
novelclaw run --topic "A lighthouse keeper discovers messages from the future" --auto-approve --verbose

# Alternative: use Anthropic API directly (billed per token)
# export ANTHROPIC_API_KEY="sk-ant-..."
# Edit config.novelclaw.yaml → llm.provider: "anthropic"
```

## Project Layout
- `autonovelclaw/pipeline/` — 30-stage state machine, executor, runner with checkpoint/resume
- `autonovelclaw/llm/` — Anthropic + OpenAI-compatible clients with retry and token tracking
- `autonovelclaw/prompts.py` — All stage prompts with YAML override support
- `autonovelclaw/continuity/` — Entity tracker, timeline validator, foreshadowing tracker
- `autonovelclaw/chapter/` — Context window budgeting, sensory auditor, structure validator
- `autonovelclaw/reviewers/` — Review parser, enhancement planner, convergence tracker
- `autonovelclaw/publishing/` — EPUB 3.0, KDP Print PDF, KDP validator
- `autonovelclaw/evolution.py` — Self-learning from prior chapters/runs
- `autonovelclaw/health.py` — Pre-flight doctor (11 checks)
- `autonovelclaw/quality.py` — AI cliché detection, sensory analysis
- `autonovelclaw/config.py` — Pydantic config
- `autonovelclaw/knowledge_base.py` — File-backed KB for cross-chapter persistence
- `tests/` — pytest suite
- `configs/config.novelclaw.example.yaml` — Example configuration

## Architecture
30 stages, 10 phases. Chapters 11-23 loop per-chapter with review/enhance sub-loops.
- 4 gate stages require human approval (or --auto-approve)
- Enhancement decision: ≥9.0 PROCEED, 7.5-8.9 REFINE (max 3 loops), <7.5 REWRITE (max 2)
- Two independent reviewers: Critic (literary, temp 0.3) and Reader (engagement, temp 0.3)
- Writer agent (temp 0.85) with full Echoes of the Abyss writing methodology

## Current Status
Steps 1-3 of 8 complete (unified LLM, wired all subsystems, deleted old code).
**Next: Step 4 — first real end-to-end run.**

Known areas that will need debugging during first run:
- Prompt length may exceed context window for early models
- JSON parsing from LLM output needs robustness
- Chapter word count may undershoot targets
- Rating extraction from non-standard review formats

## Testing
```bash
pytest tests/ -v
```

## Key Files to Edit
- `prompts.py` — All LLM prompts (blocks, stages, genres)
- `prompts.default.yaml` — User prompt overrides
- `configs/config.novelclaw.example.yaml` — Configuration
- `pipeline/executor.py` — Stage implementations
- `pipeline/runner.py` — Pipeline orchestration
