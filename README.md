# AutoNovelClaw 📖🦞

## **Tell me your idea. Pick a storyline. I'll write, review, enhance, and publish it.**

*From a vague idea to a KDP-ready novel — fully autonomous.*

[![MIT License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)](https://python.org)
[![Tests Passing](https://img.shields.io/badge/Tests-passing-brightgreen?logo=pytest&logoColor=white)](#testing)
[![OpenClaw Compatible](https://img.shields.io/badge/OpenClaw-Compatible-ff4444)](#openclaw-integration)

> **⚠️ Alpha Release (v0.1.0):** This is a working pipeline with a complete architecture, passing tests, and validated imports. It has not yet been battle-tested with hundreds of end-to-end runs. Expect to iterate. The writing quality depends heavily on your LLM provider, model choice, and the prompts — which you can customise.

> **💰 Cost Warning:** A full novel run makes hundreds of LLM API calls (ideation, world-building, outlining, writing 8–12 chapters, reviewing each chapter twice, enhancing, compiling, formatting). With Claude Sonnet on Anthropic's API, expect **$30–$150+ per novel** depending on chapter count, enhancement loops, and word count targets. Start with a short test run (2–3 chapters, low word count) to gauge your costs before committing to a full novel.

> **⏱️ Runtime Estimate:** A full 10-chapter novel with review loops takes **2–6 hours** depending on model speed, rate limits, and how many enhancement iterations each chapter needs. The pipeline is resumable — you can stop and restart without losing progress.

---

## 🤔 What Is This?

AutoNovelClaw is an autonomous novel-writing pipeline that takes a raw story idea and produces a publication-ready manuscript. It is not a single prompt that asks an AI to "write a book." It is a **30-stage, 10-phase pipeline** with four distinct AI agents, independent review cycles, iterative quality enhancement, continuity checking, and KDP-ready export.

The pipeline:

1. Takes your idea (even something as vague as *"something with time travel and the ocean"*)
2. Generates **10 distinct storylines** for you to choose from
3. Asks if you want a standalone novel or a multi-book series
4. Builds a complete world (codex, characters, magic/technology system)
5. Creates a chapter-by-chapter outline with detailed beat sheets
6. Writes each chapter using the **Echoes of the Abyss** writing methodology
7. Sends each chapter to **two independent AI reviewers** who have zero knowledge of the planning documents
8. Based on reviewer ratings, either approves the chapter, enhances it surgically, or rewrites it
9. Checks the full manuscript for continuity errors (character names, timeline, world rules)
10. Formats the manuscript as a **Kindle-ready EPUB** and a **KDP Print-ready paperback PDF**
11. Generates Amazon metadata (description, keywords, categories)

You can run the entire pipeline with one command, or pause at human gates to review and approve each step.

---

## 📦 What You Get

When the pipeline completes, it creates an artifact directory with this structure:

```
artifacts/nc-20260318-143022-my-novel/
├── pipeline_state.json            # Full pipeline state (for resume)
├── parsed_concept.json            # Your idea, parsed into structured elements
├── storylines.md                  # All 10 generated storylines
├── selected_storyline.md          # The one you picked
├── series_arc.md                  # Multi-book arc (if series)
├── book_outline.md                # Chapter-by-chapter outline
├── beat_sheets.md                 # Detailed scene beats per chapter
├── world/
│   ├── world_codex.md             # Geography, history, cultures, religion
│   ├── character_profiles.md      # All major characters with depth
│   └── magic_system.md            # Or technology_system.md
├── chapters/
│   ├── chapter_01_scene_plan.md   # Scene plan for chapter 1
│   ├── chapter_01_draft.md        # First draft
│   ├── chapter_01_enhanced.md     # After sensory enhancement pass
│   ├── chapter_01_voice_checked.md
│   ├── chapter_01_polished.md     # Ready for review
│   ├── chapter_01_Phase_1.md      # After enhancement loop
│   ├── chapter_01_APPROVED.md     # Final approved version
│   └── ... (same for each chapter)
├── reviews/
│   ├── chapter_01_review_1.md     # Literary critic review
│   ├── chapter_01_review_2.md     # Beta reader review
│   ├── chapter_01_review_analysis.md
│   ├── chapter_01_decision.md     # PROCEED / REFINE / REWRITE
│   ├── chapter_01_convergence.md  # Quality convergence report
│   ├── chapter_01_continuity_report.md
│   └── ... (same for each chapter)
├── deliverables/
│   ├── manuscript_complete.md     # Full novel in Markdown
│   ├── Your_Title.epub            # Kindle-ready EPUB
│   ├── Your_Title_interior.pdf    # KDP Print-ready paperback interior
│   ├── metadata.json              # Book metadata
│   ├── book_description.html      # Amazon product page description
│   ├── keywords.txt               # 7 KDP search keywords
│   └── README.md                  # Summary of deliverables with stats
└── evolution/                     # Self-learning lessons (future runs)
```

---

## 🧬 The Writing DNA

AutoNovelClaw's writing engine is built on the **Echoes of the Abyss methodology** — a writing system developed across 100+ hours of real human-AI collaborative novel writing on two book series ("The Silent Empire," an epic fantasy tetralogy, and "Phantom Drift," a techno-thriller series). That collaborative process produced manuscripts independently rated 9.3/10 by AI reviewers. The specific techniques that got them to that level are hardcoded into this pipeline's Writer Agent.

### The Five-Sense Immersion Model

Most AI-generated prose over-indexes on visual description and neglects the other senses. The Writer Agent targets a specific sensory distribution in every chapter:

```
Visual      ████████████████████  40%   (light, shadow, colour, movement)
Kinesthetic █████████████         25%   (texture, temperature, pressure, weight)
Olfactory   ██████████            20%   (the most neglected sense — and the most grounding)
Auditory    █████                 10%   (sound, silence, rhythm, vibration)
Gustatory   ███                    5%   (taste as emotional anchor)
```

The sensory enhancement stage (Stage 13) specifically audits and boosts sensory density to meet these targets.

### The Escalation Ladder

Action and emotional scenes build in six mandatory stages. The Writer Agent never jumps from calm to climax:

```
1. Initial sensation (first signal something is wrong)
2. Visual shift (the world changes)
3. Physical escalation (the body responds)
4. Full immersion (the character is consumed)
5. Breaking point (peak intensity)
6. Aftermath (shaking hands, residual effects, the silence after)
```

### The Character Lens

Every description is filtered through the POV character's expertise. A pilot sees thunderheads at 40,000 feet. A scientist sees electromagnetic anomalies. A diver reads current patterns. A blacksmith notices metal grain. Characters never observe things their background wouldn't notice.

### Anti-AI Voice

The Writer Agent is explicitly instructed to avoid AI-typical phrasing: "It's worth noting," "Moreover," "Furthermore," "a tapestry of," "a symphony of," "palpable tension," and dozens of other patterns that make AI-generated prose feel generic. The voice consistency stage (Stage 14) audits for these and removes them.

---

## 🔬 Pipeline: 30 Stages, 10 Phases

```
Phase 0: Ideation                    Phase F: Critical Review
  0. IDEA_INTAKE                       17. INDEPENDENT_REVIEW    ← Reviewer 1
  1. STORYLINE_GENERATION (×10)        18. REVIEW_ANALYSIS       ← Multi-critic debate
  2. SELECTION_AND_SCOPE  [gate]       19. ENHANCEMENT_DECISION  ← PROCEED/REFINE/REWRITE
  3. SERIES_ARC_DESIGN

Phase A: World-Building              Phase G: Enhancement Loop
  4. CODEX_GENERATION                  20. SURGICAL_ENHANCEMENT  ← Phase 1.X
  5. CHARACTER_CREATION                21. RE_REVIEW             ← Reviewer 2
  6. SYSTEM_DESIGN                     22. QUALITY_CONVERGENCE   ← Target ≥ 9.0/10
  7. WORLD_VALIDATION     [gate]

Phase B: Story Architecture          Phase H: Manuscript Assembly
  8. BOOK_OUTLINE                      23. CHAPTER_APPROVAL      [gate]
  9. CHAPTER_BEAT_SHEETS               24. MANUSCRIPT_COMPILE
 10. OUTLINE_REVIEW       [gate]       25. CONTINUITY_VERIFY     ← Sentinel
                                       26. STYLE_CONSISTENCY
Phase C: Chapter Writing
 11. SCENE_PLANNING                  Phase I: Publishing Pipeline
 12. CHAPTER_DRAFT        ← Writer     27. EPUB_GENERATION       ← KDP Kindle
 13. SENSORY_ENHANCEMENT               28. PAPERBACK_FORMATTING  ← KDP Print
                                       29. PUBLISHING_PACKAGE    ← Final export
Phase D: Style Verification
 14. VOICE_CONSISTENCY

Phase E: Continuity Gate
 15. CHAPTER_CONTINUITY   ← Sentinel
 16. PRE_REVIEW_POLISH
```

**Gate stages** (2, 7, 10, 23) pause and ask for human approval. Use `--auto-approve` to skip all gates and run fully autonomously.

**The chapter loop** (Phases C–G) repeats for every chapter. Each chapter goes through: write → sensory enhance → voice check → continuity check → polish → review → decide → (enhance/rewrite if needed) → approve.

**Decision logic** after review:
- Rating ≥ 9.0/10 → **PROCEED** (chapter approved)
- Rating 7.5–8.9/10 → **REFINE** (surgical enhancement, then re-review, max 3 loops)
- Rating < 7.5/10 → **REWRITE** (full chapter rewrite, max 2 attempts)
- All loops exhausted → **HUMAN ESCALATION** (pipeline pauses for manual intervention)

---

## 🤖 Four Distinct Agents

The key innovation: **the writer never reviews its own work.** Each agent has a different system prompt, a different temperature, and deliberately restricted context access.

```
┌─────────────────────────────────────────────────┐
│                 ORCHESTRATOR                      │
│        (pipeline/runner.py — drives all stages)    │
└────┬──────────┬──────────┬──────────┬───────────┘
     │          │          │          │
┌────▼────┐ ┌──▼──────┐ ┌─▼────────┐ ┌▼──────────┐
│ WRITER  │ │REVIEWER │ │REVIEWER  │ │  EDITOR   │
│ (0.85)  │ │ #1(0.3) │ │ #2(0.3)  │ │  (0.1)    │
│         │ │         │ │          │ │           │
│ Sees:   │ │ Sees:   │ │ Sees:    │ │ Sees:     │
│ ✅ Codex │ │ ❌ Codex │ │ ❌ Codex  │ │ ✅ Final  │
│ ✅ Chars │ │ ❌ Chars │ │ ❌ Chars  │ │   text    │
│ ✅ Beats │ │ ❌ Beats │ │ ❌ Beats  │ │ ✅ KDP    │
│ ✅ Prior │ │ ❌ Prior │ │ ❌ Prior  │ │   specs   │
│  chaps   │ │ reviews │ │ reviews  │ │           │
│ ✅ Style │ │ ❌ Style │ │ ❌ Style  │ │           │
│  guide   │ │  guide  │ │  guide   │ │           │
└─────────┘ └─────────┘ └──────────┘ └───────────┘
  Temp 0.85   Temp 0.3    Temp 0.3    Temp 0.1
  (creative)  (analytic)  (analytic)  (precise)
```

- **Writer Agent** — Master novelist with the full Echoes of the Abyss methodology (25 stage prompts + 9 reusable blocks in `prompts.py`), world codex, character profiles, beat sheets, and rolling chapter summaries for continuity. Temperature 0.85 for creativity.
- **Reviewer #1** — Harsh literary critic. Receives ONLY the chapter text and the genre classification. Rates on a /10 scale, identifies 3–5 strengths, 3–5 weaknesses, and 3–5 concrete improvement suggestions. Temperature 0.3 for analytical precision.
- **Reviewer #2** — Genre-savvy beta reader. Receives ONLY the enhanced chapter text (after Phase 1.X). Has zero knowledge of Reviewer #1's feedback. Evaluates engagement, drag points, confusion points, and memorability. Temperature 0.3.
- **Editor Agent** — KDP publishing specialist. Handles EPUB generation, paperback PDF formatting, metadata, and Amazon description. Temperature 0.1 for rule-following precision.

---

## 🚀 Installation

### Requirements

- **Python 3.11 or newer** (tested on 3.11 and 3.12)
- **Operating System:** Linux or macOS. Windows works for the pipeline itself but the `sentinel.sh` watchdog script requires bash (use WSL on Windows, or skip the sentinel — the pipeline works fine without it).
- **API Key:** Anthropic (recommended) or any OpenAI-compatible API provider.
- **Disk space:** ~50–200 MB per novel run (manuscripts, reviews, deliverables).
- **Internet connection:** Required for LLM API calls during the run.

### Step-by-Step Install

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/AutoNovelClaw.git
cd AutoNovelClaw

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate    # Linux/macOS
# .venv\Scripts\activate     # Windows

# Install AutoNovelClaw and all dependencies
pip install -e .

# Verify the installation
novelclaw --version
# → novelclaw, version 0.1.0
```

### Set Your API Key

AutoNovelClaw reads the API key from an environment variable (default: `ANTHROPIC_API_KEY`).

```bash
# Anthropic (recommended)
export ANTHROPIC_API_KEY="sk-ant-api03-..."

# Or add to your shell profile for persistence:
echo 'export ANTHROPIC_API_KEY="sk-ant-api03-..."' >> ~/.bashrc
source ~/.bashrc
```

If you use OpenAI or another provider, see [Using Other LLM Providers](#-using-other-llm-providers) below.

---

## 🎯 Usage — All Variations

### 1. Interactive Mode (Recommended for First Run)

The simplest way. The pipeline asks for your idea, generates storylines, and guides you through each decision.

```bash
novelclaw run
```

This will:
1. Ask for your story idea
2. Generate 10 storylines and present them
3. Ask you to pick one
4. Ask if standalone or series
5. Build the world and pause for your approval
6. Create the outline and pause for your approval
7. Write each chapter, review it, and pause for your approval
8. Generate the final EPUB and paperback PDF

### 2. One-Command Autonomous Mode

Skip all human gates. The pipeline runs start-to-finish without stopping.

```bash
novelclaw run --topic "A pilot discovers ancient pyramids underwater" --auto-approve
```

In auto-approve mode:
- Storyline #1 is automatically selected
- The novel is treated as standalone (not a series)
- World, outline, and chapters are auto-approved
- The pipeline runs until deliverables are produced or it fails

### 3. With a Config File

For full control over every setting:

```bash
# Create a config file from the example
novelclaw init
# → Creates config.novelclaw.yaml in the current directory

# Or copy manually:
cp configs/config.novelclaw.example.yaml config.novelclaw.yaml

# Edit it — at minimum, set your author name
# The API key is read from the environment variable by default

# Run with your config
novelclaw run --config config.novelclaw.yaml --topic "Your idea"
```

### 4. With Config + Auto-Approve

```bash
novelclaw run -c config.novelclaw.yaml -t "Your idea" --auto-approve
```

### 5. Verbose Mode (for Debugging)

See detailed logs of every stage execution:

```bash
novelclaw run --topic "Your idea" --auto-approve --verbose
```

### 6. Check Status of a Run

```bash
novelclaw status --run-dir artifacts/nc-20260318-143022-my-novel/
```

Shows: start time, current stage, chapters completed, total stages, and the last 5 decisions made by the pipeline.

### 7. Resume an Interrupted Run

If the pipeline is interrupted (Ctrl+C, crash, rate limit), simply run the same command again. The pipeline reads `pipeline_state.json` from the artifact directory and resumes from the last completed stage.

```bash
# Same command as before — it picks up where it left off
novelclaw run --topic "Your idea" --auto-approve
```

> **Note on resuming:** The pipeline creates a timestamped artifact directory (e.g., `nc-20260318-143022-my-novel`). On re-run, a NEW directory is created. To resume an existing run, the pipeline would need to find the previous directory. Currently, resume works within the same process — if rate-limited, the retry logic handles it automatically. For cross-session resume, manually point to the existing directory by setting `runtime.output_dir` in your config to the existing artifact path.

### 8. Using the Python API

```python
from autonovelclaw.config import load_config, NovelClawConfig
from autonovelclaw.pipeline import PipelineRunner

# Option A: Load from YAML
config = load_config("config.novelclaw.yaml")

# Option B: Create programmatically with defaults
config = NovelClawConfig()
config.novel.author = "Jane Author"
config.novel.genre.primary = "epic_fantasy"
config.review.min_rating_proceed = 8.5  # Lower the quality bar

# Run the pipeline
runner = PipelineRunner(config, auto_approve=True, topic="Your idea here")
deliverables_path = runner.run()

print(f"Novel at: {deliverables_path}")
# → Novel at: artifacts/nc-20260318-.../deliverables
```

### 9. Quick Cost Test (Recommended Before Full Run)

To test the pipeline without committing to a full novel:

```yaml
# In config.novelclaw.yaml — reduce everything
novel:
  target:
    chapter_count_min: 2
    chapter_count_max: 2
    words_per_chapter_min: 2000
    words_per_chapter_max: 3000
review:
  min_rating_proceed: 8.0      # Lower bar = fewer enhancement loops
  max_enhancement_loops: 1
```

```bash
novelclaw run -c config.novelclaw.yaml -t "Quick test story" --auto-approve
```

This runs the full pipeline with 2 short chapters — enough to verify everything works and estimate costs for a full run.

### 10. Running the Background Sentinel (Linux/macOS only)

The sentinel monitors a running pipeline for stalled stages, empty chapters, and disk space:

```bash
chmod +x sentinel.sh
./sentinel.sh artifacts/nc-20260318-143022-my-novel/ &

# Check sentinel logs:
tail -f artifacts/nc-20260318-143022-my-novel/sentinel.log
```

The sentinel is optional. The pipeline works without it.

---

## 🔌 Using Other LLM Providers

### OpenAI

```yaml
llm:
  provider: "openai-compatible"
  base_url: "https://api.openai.com/v1"
  api_key_env: "OPENAI_API_KEY"
  models:
    writer: "gpt-4o"
    reviewer_1: "gpt-4o"
    reviewer_2: "gpt-4o-mini"    # Cheaper model for second reviewer
    editor: "gpt-4o-mini"        # Formatting doesn't need frontier model
    ideation: "gpt-4o"
```

```bash
export OPENAI_API_KEY="sk-..."
novelclaw run --topic "Your idea"
```

### Any OpenAI-Compatible API (Ollama, Together, Groq, etc.)

```yaml
llm:
  provider: "openai-compatible"
  base_url: "http://localhost:11434/v1"   # Ollama example
  api_key_env: "OLLAMA_API_KEY"
  models:
    writer: "llama3.1:70b"
    reviewer_1: "llama3.1:70b"
    reviewer_2: "llama3.1:8b"
    editor: "llama3.1:8b"
    ideation: "llama3.1:70b"
```

> **Note:** Writing quality depends heavily on model capability. Smaller models (< 30B parameters) will produce noticeably weaker prose. The Echoes of the Abyss prompts were developed with Claude Sonnet and work best with frontier-class models.

---

## 📚 Bringing Existing Materials

If you already have a world codex, character profiles, or outlines from previous work, pre-populate the knowledge base before running:

```bash
# Create the KB directories
mkdir -p novel_kb/world_codex novel_kb/characters novel_kb/approved_chapters

# Place your files (Markdown format)
cp my_world_codex.md novel_kb/world_codex/codex.md
cp my_hero_profile.md novel_kb/characters/hero.md
cp my_villain_profile.md novel_kb/characters/villain.md
```

The Writer Agent loads context from the knowledge base at `novel_kb/` (configurable via `knowledge_base.root`). Pre-populated files are used as context for world-building, character creation, and chapter writing. The pipeline may still run its generation stages, but the Writer Agent will see your existing materials when composing chapters.

---

## ⚙️ Configuration Reference

All settings live in `config.novelclaw.yaml`. Create one with `novelclaw init` or copy from `configs/config.novelclaw.example.yaml`. Every field has a sensible default — you only need to set what you want to change.

<details>
<summary>Click to expand full settings table</summary>

| Setting | Default | Description |
|---------|---------|-------------|
| `mode` | `semi-auto` | `full-auto` (only gates) / `semi-auto` (gates + prompts) / `supervised` (pause every stage) |
| `ideation.storyline_count` | `10` | How many storylines to generate (1–10) |
| `novel.author` | `""` | Your name — appears on title page and copyright |
| `novel.genre.primary` | `""` | Genre for overlay. Options: `epic_fantasy`, `techno_thriller`, `sci_fi`, `dark_fantasy`, `horror`, `romance`, `literary_fiction`, `mystery`. Leave blank for auto-detect. |
| `novel.scope` | `standalone` | `standalone` or `series` |
| `novel.target.word_count_min` | `55000` | Minimum total word count |
| `novel.target.word_count_max` | `85000` | Maximum total word count |
| `novel.target.chapter_count_min` | `8` | Minimum chapters |
| `novel.target.chapter_count_max` | `12` | Maximum chapters |
| `novel.target.words_per_chapter_min` | `5500` | Minimum words per chapter |
| `novel.target.words_per_chapter_max` | `8800` | Maximum words per chapter |
| `writing.sensory_targets.visual` | `0.40` | Visual sensory ratio target |
| `writing.sensory_targets.kinesthetic` | `0.25` | Kinesthetic ratio target |
| `writing.sensory_targets.olfactory` | `0.20` | Olfactory ratio target |
| `writing.sensory_targets.auditory` | `0.10` | Auditory ratio target |
| `writing.sensory_targets.gustatory` | `0.05` | Gustatory ratio target |
| `writing.pov` | `third-person-limited` | Narrative perspective |
| `writing.tense` | `past` | Narrative tense |
| `review.min_rating_proceed` | `9.0` | Minimum composite rating to approve a chapter |
| `review.min_rating_refine` | `7.5` | Minimum rating before rewrite is triggered |
| `review.max_enhancement_loops` | `3` | Max Phase 1.X iterations per chapter |
| `review.max_rewrite_attempts` | `2` | Max full rewrites per chapter |
| `review.critic_weight` | `0.6` | Weight for Reviewer #1 in composite score |
| `review.reader_weight` | `0.4` | Weight for Reviewer #2 in composite score |
| `review.diminishing_returns_threshold` | `0.2` | Stop enhancing if improvement < this |
| `publishing.paperback.trim_size` | `6x9` | Options: `5x8`, `5.25x8`, `5.5x8.5`, `6x9` |
| `publishing.paperback.paper_color` | `cream` | `white` or `cream` |
| `publishing.paperback.font` | `Palatino` | Interior body font |
| `publishing.paperback.font_size` | `11` | Body text size in points |
| `llm.provider` | `anthropic` | `anthropic` or `openai-compatible` |
| `llm.base_url` | `https://api.anthropic.com/v1` | API endpoint |
| `llm.api_key_env` | `ANTHROPIC_API_KEY` | Environment variable name for the key |
| `llm.temperature.writer` | `0.85` | Higher = more creative |
| `llm.temperature.reviewer` | `0.3` | Lower = more analytical |
| `llm.temperature.editor` | `0.1` | Lowest = most precise |
| `llm.temperature.ideation` | `0.95` | Highest = maximum divergence |
| `llm.max_tokens` | `8192` | Max tokens per LLM response |

</details>

---

## 📊 Genre Support

The core writing engine is genre-agnostic. Genre overlays in `prompts.py` adjust sensory emphasis and pacing:

| Genre | Key Overlay | Sensory Boost | Pacing Profile |
|-------|-------------|--------------|----------------|
| Epic Fantasy | World's wound, mythic beats, cultural idioms | Olfactory +5%, Gustatory +3% | Epic (longer reflection) |
| Techno-Thriller | Technical expertise, procedural detail, ticking clocks | Kinesthetic +5%, Auditory +3% | Propulsive (shorter scenes) |
| Sci-Fi | Technology shapes society, alien perspectives, scale | Visual +5%, Kinesthetic +3% | Discovery rhythms |
| Dark Fantasy | Beauty corrupted, cosmic indifference, body horror | Olfactory +8%, Auditory +5% | Slow dread build |
| Horror | The ordinary becoming wrong, withholding, isolation | Auditory +10%, Olfactory +8% | Slow suffocation |
| Romance | Physical awareness, proximity tension, slow-burn | Kinesthetic +10%, Olfactory +5% | Push-pull |
| Literary Fiction | Interior life, metaphor as structure, silence | Gustatory +5%, Kinesthetic +3% | Contemplative |
| Mystery | Clues in description, every character a suspect | Visual +5%, Olfactory +3% | Accelerating |

---

## 🧪 Testing

```bash
pip install -e ".[dev]"
pytest tests/ -v
# → 65 passed in ~1s
```

The test suite validates: configuration defaults and YAML loading, sensory target ranges, review threshold ordering, API key resolution, knowledge base CRUD, all agent prompt content (sensory model, escalation ladder, anti-AI phrasing, genre overlays, reviewer criteria, debate critics), pipeline state persistence, and token utilities.

---

## 🛠️ Customising the Writing Style

The Writer Agent's prompts are in `autonovelclaw/prompts.py` with 25 stage prompts, 9 reusable blocks, and 8 genre overlays. All prompts can be overridden via YAML (copy `prompts.default.yaml`). To customise:

1. **Sensory targets:** Change percentages in `config.novelclaw.yaml` under `writing.sensory_targets`
2. **Anti-cliché list:** Edit the `anti_ai_voice` block in `prompts.py`, or the blacklist in `quality.py`
3. **Genre techniques:** Edit or add entries in `_GENRE_OVERLAY_PROMPTS` in `prompts.py`
4. **Chapter metrics:** Modify word count, dialogue ratio, and beat frequency in the `chapter_metrics` block
5. **Reviewer harshness:** Edit the `independent_review` stage prompt to change evaluation weights
6. **Add a new genre:** Add a new key to `_GENRE_OVERLAY_PROMPTS` with your overlay text

---

## 🦞 OpenClaw Integration

AutoNovelClaw includes `CLAUDE.md` (for Claude Code CLI) and `.claude/skills/novelclaw/SKILL.md` (for OpenClaw skill discovery).

```
1️⃣  Share the GitHub repo URL with OpenClaw
2️⃣  OpenClaw reads NOVELCLAW_AGENTS.md → understands the pipeline
3️⃣  Say: "Write a novel about [your idea]"
4️⃣  OpenClaw clones, installs, configures, runs, and returns the deliverables
```

Also works with **Claude Code** (reads `NOVELCLAW_CLAUDE.md`) and any AI coding agent that can read Markdown context files.

---

## ❓ Troubleshooting

| Problem | Solution |
|---------|----------|
| `ValueError: No API key` | Set the env var: `export ANTHROPIC_API_KEY="sk-ant-..."` or add `api_key: "..."` in config under `llm:` |
| Rate limiting (429 errors) | Built-in retry (3 attempts, 2/5/15s backoff). If persistent, reduce `llm.max_tokens` or use a higher-tier API plan. Pipeline is resumable. |
| Chapters too short | Increase `novel.target.words_per_chapter_min` and ensure `llm.max_tokens` ≥ 8192 |
| "ebooklib not installed" | Run `pip install ebooklib` (should auto-install but some environments need it manual) |
| "reportlab not installed" | Run `pip install reportlab` |
| Pipeline stalls at gate | In semi-auto mode, type `approve` or `reject` in the terminal. Use `--auto-approve` to skip. |
| `sentinel.sh` fails on Windows | The sentinel is bash-only. Skip it on Windows (pipeline works without it) or use WSL. |
| Enhancement loops never converge | Lower `review.min_rating_proceed` (e.g., 8.5) or reduce `review.max_enhancement_loops` |

---

## 📐 Project Structure

```
AutoNovelClaw/
├── autonovelclaw/                     # Main package (~12,000 lines of Python)
│   ├── __init__.py
│   ├── cli.py                         # CLI: run, status, init, doctor
│   ├── config.py                      # Pydantic configuration with validation
│   ├── prompts.py                     # PromptManager: 25 stage prompts, 9 blocks, 8 genres, YAML overrides
│   ├── knowledge_base.py              # File-backed KB for cross-chapter persistence
│   ├── evolution.py                   # Self-learning: JSONL store, time-decay, per-stage overlays
│   ├── health.py                      # Pre-flight doctor (11 checks with fix suggestions)
│   ├── quality.py                     # AI cliché detection, sensory analysis, quality scoring
│   ├── pipeline/                      # State machine + orchestration
│   │   ├── stages.py                  # 30-stage IntEnum, transitions, gates, rollback
│   │   ├── contracts.py               # I/O contracts per stage (inputs, outputs, DoD, error codes)
│   │   ├── runner.py                  # Checkpoint/resume, chapter-loop orchestration
│   │   └── executor.py               # All 30 stage implementations
│   ├── llm/                           # Multi-provider LLM clients
│   │   ├── client.py                  # Abstract base with retry, token tracking
│   │   ├── anthropic.py               # Native Anthropic Messages API
│   │   └── openai_compat.py           # OpenAI-compatible (GPT, Ollama, Together, Groq)
│   ├── continuity/                    # Cross-chapter consistency
│   │   ├── tracker.py                 # Entity database (characters, locations, objects)
│   │   ├── timeline.py                # Timeline validator + foreshadowing tracker
│   │   └── verify.py                  # Full-manuscript verification
│   ├── chapter/                       # Chapter generation support
│   │   ├── context.py                 # Context window budgeting + smart excerpt selection
│   │   ├── sensory_auditor.py         # Paragraph-level sensory analysis with gap targeting
│   │   └── validator.py               # Structure validation (hooks, breaks, dialogue ratio)
│   ├── reviewers/                     # Review processing
│   │   ├── parser.py                  # Structured extraction from reviewer output
│   │   └── planner.py                 # Enhancement planner + convergence tracker
│   ├── publishing/                    # KDP-ready output
│   │   ├── epub_builder.py            # EPUB 3.0 with CSS, navigation, cover
│   │   ├── pdf_builder.py             # KDP Print interior (trim sizes, gutters, typography)
│   │   └── validator.py               # KDP content guidelines validation
│   ├── data/
│   │   └── genre_conventions.yaml     # 8 genres, cliché blacklist, KDP specs
│   └── utils/                         # Token estimation, chunking, word count
├── tests/                             # pytest suite
├── configs/                           # Example YAML config
├── docs/                              # Integration guide
├── .claude/skills/novelclaw/          # Claude Code / OpenClaw skill
├── CLAUDE.md                          # Claude Code project instructions
├── prompts.default.yaml               # User prompt override template
├── sentinel.sh                        # Background watchdog
├── pyproject.toml
├── LICENSE (MIT)
└── .gitignore
```

---

## 💡 Tips for Best Results

1. **Be specific with your idea.** "A story about a pilot" works, but "A disgraced Navy pilot discovers ancient pyramids underwater in the Bermuda Triangle" gives the ideation engine much better raw material.

2. **Start with a short test run.** Set `chapter_count_max: 2` and `words_per_chapter_max: 3000` to test the pipeline cheaply before a full novel.

3. **Use semi-auto mode first.** Review the world codex and outline before writing starts. Catching issues early saves API tokens and prevents wasted chapters.

4. **Lower `min_rating_proceed` to save money.** 8.5 instead of 9.0 means fewer enhancement loops per chapter. The quality difference is marginal but the cost savings are significant.

5. **Use frontier models for the writer, cheaper models for the editor.** The writer needs maximum capability. The editor just formats — a smaller model works fine.

6. **Review the deliverables before uploading to KDP.** The EPUB and PDF are structurally correct but may need manual polish (cover placement, final proofread, ISBN insertion). This is an alpha release, not a replacement for a human final pass.

---

## 🙏 Acknowledgements

Inspired by:

- 🔬 [AutoResearchClaw](https://github.com/aiming-lab/AutoResearchClaw) — The 23-stage autonomous research pipeline whose architecture was adapted for novel writing
- 📖 The **Echoes of the Abyss** writing methodology — 100+ hours of collaborative novel writing across "The Silent Empire" (epic fantasy) and "Phantom Drift" (techno-thriller)
- 🦞 [OpenClaw](https://github.com/openclaw/openclaw) — AI agent platform integration

---

## 📄 License

MIT — see [LICENSE](LICENSE) for details.
