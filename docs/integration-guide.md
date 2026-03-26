# AutoNovelClaw — Integration Guide

## Architecture Overview

AutoNovelClaw is a 30-stage pipeline organised into 10 phases that transforms a raw story idea into a publication-ready novel. The pipeline is resumable, state is persisted to disk, and human gates can be auto-approved for fully autonomous operation.

## Agent Architecture

### Four Distinct Agents

The system uses four AI agents with **deliberately separated contexts** to prevent the writer from being blind to its own weaknesses:

| Agent | Role | Sees | Temperature |
|-------|------|------|-------------|
| Writer | Writes chapters | Codex, characters, beats, prior chapters | 0.85 |
| Reviewer #1 | Harsh literary critic | Chapter text only + genre | 0.3 |
| Reviewer #2 | Beta reader | Enhanced chapter only | 0.3 |
| Editor | KDP formatting | Final manuscript + format specs | 0.1 |

### Why Separation Matters

The Writer Agent has full context (world codex, character profiles, beat sheets). This helps it write well but creates blind spots — it "knows" what it intended even if the text doesn't convey it.

The Reviewers have **zero context** beyond the chapter text. They judge only what's on the page, exactly like a real reader would. This separation is what pushes quality from 8/10 to 9.5/10.

## The Enhancement Loop

When a chapter scores below the target (default 9.0/10), the pipeline enters the Phase 1.X surgical enhancement loop:

```
Chapter Draft → Review → Decision
                           ├── PROCEED (≥ 9.0) → Approve
                           ├── REFINE (7.5–8.9) → Surgical Enhancement → Re-Review → Converge?
                           └── REWRITE (< 7.5) → Full Rewrite → Back to Review
```

Each enhancement pass:
- Adds ≤5% word count
- Targets the highest-impact issues first
- Preserves identified strengths
- Tracks diminishing returns (stops if improvement < 0.2)
- Maximum 3 loops before escalation

## OpenClaw Bridge

AutoNovelClaw supports six optional bridge capabilities when running inside OpenClaw:

| Capability | Config Flag | Description |
|-----------|-------------|-------------|
| Cron | `use_cron` | Scheduled writing sessions |
| Message | `use_message` | Progress notifications |
| Memory | `use_memory` | Cross-session knowledge persistence |
| Sessions | `use_sessions_spawn` | Parallel sub-sessions |
| Web Fetch | `use_web_fetch` | Genre research during ideation |
| Browser | `use_browser` | Reference material collection |

## Python API

```python
from autonovelclaw.config import load_config
from autonovelclaw.pipeline import PipelineRunner

config = load_config("config.novelclaw.yaml")
runner = PipelineRunner(config, auto_approve=True, topic="Your idea")
deliverables = runner.run()
print(f"Novel at: {deliverables}")
```

## Pipeline State

The pipeline persists state to `pipeline_state.json` in the artifact directory. This enables:

- **Resumability**: Interrupt and resume without losing progress
- **Monitoring**: Check status with `novelclaw status --run-dir path/`
- **Debugging**: Inspect decisions, ratings, and enhancement history

## Knowledge Base

The file-backed knowledge base stores:

| Category | Contents |
|----------|----------|
| `world_codex` | World codex, series arc, system design |
| `characters` | Character profiles |
| `approved_chapters` | Final approved chapter text |
| `chapter_summaries` | 200-300 word continuity summaries |
| `reviews` | All reviewer feedback |
| `lessons_learned` | Self-learning insights |

## Self-Learning

After each chapter, the system extracts lessons:
- Which enhancement techniques improved ratings most
- Common reviewer complaints to preemptively address
- Voice drift patterns to correct
- Pacing calibration data
- Sensory balance actual vs targets

Lessons have a 90-day time decay (creative insights age slower than technical ones).
