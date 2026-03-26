"""Prompt externalisation for the AutoNovelClaw pipeline.

All 30 stage prompts are defined here as defaults and can be overridden
via a user-provided YAML file.  Users customise prompts without touching
Python source code.

Architecture
------------
* ``_DEFAULT_STAGES`` — every LLM-facing prompt, keyed by stage name.
* ``_DEFAULT_BLOCKS`` — reusable prompt fragments (sensory model, etc.).
* ``_DEFAULT_SUB_PROMPTS`` — secondary prompts (summary generation, etc.).
* ``PromptManager`` — loads defaults → merges user overrides → renders templates.
* ``_render()`` — safe ``{variable}`` substitution that leaves unmatched
  patterns (JSON schemas, curly-brace literals) untouched.

Usage
-----
::

    from autonovelclaw.prompts import PromptManager

    pm = PromptManager()                           # defaults only
    pm = PromptManager("my_prompts.yaml")          # with user overrides

    sp = pm.for_stage("chapter_draft", chapter_num="3", chapter_title="The Hunt")
    resp = llm.chat(system=sp.system, user=sp.user, max_tokens=sp.max_tokens)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

def _render(template: str, variables: dict[str, str]) -> str:
    """Replace ``{var_name}`` placeholders with *variables* values.

    Only bare ``{word_chars}`` tokens are substituted — JSON schema
    examples or nested braces are left untouched because the regex
    requires the closing ``}`` immediately after the identifier.
    """
    def _replacer(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(variables[key]) if key in variables else match.group(0)

    return re.sub(r"\{(\w+)\}", _replacer, template)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RenderedPrompt:
    """Fully rendered prompt ready for ``llm.complete()``."""

    system: str
    user: str
    json_mode: bool = False
    max_tokens: int | None = None


# ---------------------------------------------------------------------------
# Reusable prompt blocks
# ---------------------------------------------------------------------------

_DEFAULT_BLOCKS: dict[str, str] = {

    "sensory_model": """\
## THE FIVE-SENSE IMMERSION MODEL

Every significant paragraph engages a minimum of 2-3 senses simultaneously.
Target distribution across each chapter:

- VISUAL ({sensory_visual}): light, shadow, colour, movement, distance
- KINESTHETIC ({sensory_kinesthetic}): texture, temperature, pressure, weight, movement
- OLFACTORY ({sensory_olfactory}): the most neglected sense — and the most grounding
- AUDITORY ({sensory_auditory}): sound, silence, rhythm, vibration
- GUSTATORY ({sensory_gustatory}): taste as emotional anchor

Ground every scene in multiple sensory anchors. Every location needs at least
one hyper-specific detail that could not exist anywhere else in the world.
""",

    "escalation_ladder": """\
## THE ESCALATION LADDER

For emotional or action scenes, build in six mandatory stages:
1. Initial sensation (first signal something is wrong)
2. Visual shift (the world changes)
3. Physical escalation (the body responds)
4. Full immersion (the character is consumed)
5. Breaking point (peak intensity)
6. Aftermath (shaking hands, residual effects, the silence after)

Never skip steps. Never jump from 1 to 5.
""",

    "character_lens": """\
## THE CHARACTER LENS

Filter ALL descriptions through the POV character's expertise. A pilot sees
thunderheads at 40,000 feet. A scientist sees electromagnetic anomalies. A diver
reads current patterns. Characters should never observe things their background
would not notice.
""",

    "anti_ai_voice": """\
## ANTI-AI VOICE RULES

NEVER use these phrases or patterns:
- "It's worth noting", "Moreover", "Furthermore", "In conclusion"
- "A symphony of", "A tapestry of", "A dance of"
- "Palpable tension", "painting the sky"
- "It is important to note", "Needless to say"
- Any phrase that sounds like an AI assistant, not a novelist
- Generic descriptors: "beautiful", "amazing", "incredible"
- The word "palpable" in any context
""",

    "chapter_metrics": """\
## TARGET METRICS

- Word Count: {wpc_min}-{wpc_max} words
- Sensory Engagement: 60-70% of paragraphs include 2+ senses
- Dialogue Ratio: 25-30% (balanced with action/description)
- Action Beats: Every 800-1,200 words
- Emotional Beats: Every 1,500-2,000 words
- Opening: Sensory grounding in first 2 paragraphs
- Ending: Physical or emotional hook pulling into next chapter
""",

    "show_dont_tell": """\
## SHOW, DON'T TELL

BAD: "He was angry."
GOOD: "His jaw worked silently, muscles bunching beneath scarred skin. The leather
grip of his sword creaked in his whitening fist."

BAD: "It was hot."
GOOD: "Humidity so thick it clung to his skin like a second shirt."

BAD: "She felt afraid."
GOOD: "Her pulse hammered against her ribs, copper flooding the back of her throat."
""",

    "dialogue_mastery": """\
## DIALOGUE MASTERY

- Subtext is king — characters rarely say what they mean directly.
- Power dynamics in every exchange.
- Interruptions, incomplete thoughts, the things that cannot be said.
- Distinctive cadence for each voice.
- Silence as punctuation — the pause before a lie, the beat after revelation.
- Dialogue reveals character AND advances plot simultaneously.
""",

    "world_building_rules": """\
## WORLD-BUILDING THROUGH DESCRIPTION (NOT EXPOSITION)

- Render settings as living characters — weather, terrain, architecture evoke emotion.
- Weave in customs, beliefs, hierarchies through character interaction.
- Let ruins, heirlooms, and old wounds hint at backstory.
- NEVER info-dump. Reveal through action and dialogue.
- Include living world details: slang, food, crafts, holidays, superstitions.

BAD: "The shard, which had been embedded eight years ago during the vortex
incident that trapped his team..."
GOOD: Reveal through character memory triggered by pain, through another
character's question, through physical evidence noticed in a mirror.
""",

    "pacing_rhythm": """\
## PACING RHYTHM

Action scenes: Short. Punchy. Fragments for impact. The shriek of steel, the wet
sound of blade in flesh. Slow-motion for crucial moments: the arc of a falling
axe, the widening of eyes in final realization. The silence after — ringing ears,
trembling hands.

Reflective passages: Longer, flowing sentences that spiral through memory and
meaning. Philosophical weight without pedantry. The drift of thought in solitary
moments. Lyrical description of beauty amid brutality.
""",
}


# ---------------------------------------------------------------------------
# Default stage prompts — system + user for each stage
# ---------------------------------------------------------------------------

_DEFAULT_STAGES: dict[str, dict[str, Any]] = {

    # === Phase 0: Ideation ===

    "idea_intake": {
        "system": (
            "You are a story concept analyst. Parse the user's raw idea into "
            "structured elements: core concepts, implied genre, tone, scale, "
            "thematic seeds, setting hints, character seeds, and missing dimensions "
            "(opportunities the user didn't specify)."
        ),
        "user": (
            "Analyse this raw story concept and extract structured elements.\n\n"
            "RAW CONCEPT:\n{topic}\n\n"
            "Respond in JSON with these fields:\n"
            '{{\n'
            '  "core_elements": ["list of nouns, settings, objects"],\n'
            '  "implied_genre": "best-fit genre",\n'
            '  "implied_subgenres": ["list"],\n'
            '  "implied_tone": "dark / light / adventurous / literary",\n'
            '  "implied_scale": "intimate / regional / epic / cosmic",\n'
            '  "thematic_seeds": ["potential themes"],\n'
            '  "setting_hints": ["time period, geography, tech level"],\n'
            '  "character_seeds": ["any characters implied"],\n'
            '  "missing_dimensions": ["opportunities for expansion"]\n'
            '}}\n\n'
            "Return ONLY valid JSON, no markdown fences."
        ),
        "json_mode": True,
        "max_tokens": 2048,
    },

    "storyline_generation": {
        "system": (
            "You are a master story architect. You generate compelling, original "
            "storylines that are genuinely DIFFERENT from each other — not "
            "variations on a theme, but distinct narrative architectures.\n\n"
            "DIVERSITY REQUIREMENTS:\n"
            "- At least 2 must subvert the obvious genre choice\n"
            "- At least 1 genre hybrid\n"
            "- At least 1 unexpected direction\n"
            "- At least 1 intimate/small-scale\n"
            "- At least 1 epic/large-scale\n"
            "- No two share the same antagonist type\n"
            "- No two share the same thematic core\n"
            "- Each must have a 'what no other story has' element"
        ),
        "user": (
            "Based on this parsed concept, generate exactly {storyline_count} "
            "distinct storylines.\n\n"
            "PARSED CONCEPT:\n{parsed_concept}\n\n"
            "For EACH storyline provide:\n\n"
            "## STORYLINE [N]\n\n"
            "**TITLE:** [compelling working title]\n"
            "**LOGLINE:** [one sentence]\n"
            "**GENRE:** [primary] / [subgenre 1], [subgenre 2]\n\n"
            "**PREMISE:**\n[3-4 vivid paragraphs — PITCH, not outline]\n\n"
            "**PROTAGONIST:**\n"
            "- Name: [name]\n- Archetype: [type]\n"
            "- Core wound: [what drives them]\n"
            "- Arc: [start → end]\n\n"
            "**ANTAGONIST:**\n"
            "- Nature: [human / systemic / cosmic / internal]\n"
            "- Description: [what opposes and why]\n\n"
            "**WORLD CONCEPT:**\n"
            "- Setting: [where and when]\n"
            "- Unique element: [what no other story has]\n"
            "- World's wound: [the ancient mistake]\n\n"
            "**THEMATIC CORE:**\n"
            "- Primary theme: [theme]\n"
            "- Question posed: [what this asks the reader]\n\n"
            "**STAKES:**\n"
            "- Personal: [protagonist's loss]\n"
            "- Global: [world's loss]\n\n"
            "**TONE & FEEL:** [comparable works]\n\n"
            "**SERIES POTENTIAL:**\n"
            "- Standalone viability: [HIGH/MEDIUM/LOW]\n"
            "- If series: [expansion concept]\n"
            "- Book 2 hook: [seed planted in Book 1]\n\n"
            "**ESTIMATED SCOPE:** [word count range, chapter count]\n\n"
            "---"
        ),
        "max_tokens": 8192,
    },

    "series_arc_design": {
        "system": (
            "You are a series architect who designs multi-book arcs with "
            "escalating scope, red-line mysteries, and cross-book foreshadowing."
        ),
        "user": (
            "Design a complete {book_count}-book series arc.\n\n"
            "SELECTED STORYLINE:\n{selected_storyline}\n\n"
            "Include:\n"
            "1. Series title and overarching theme\n"
            "2. The red-line mystery connecting all books\n"
            "3. Per-book: title, focus, mystery revealed (%), ending hook\n"
            "4. Character evolution across the full arc\n"
            "5. World expansion (local → regional → continental → cosmic)\n"
            "6. Foreshadowing map (planted where, blooms where)\n"
            "7. The final-book revelation that reframes everything\n\n"
            "Be specific with names, places, events."
        ),
        "max_tokens": 8192,
    },

    # === Phase A: World-Building ===

    "codex_generation": {
        "system": (
            "You are a world-builder creating a comprehensive codex for an "
            "epic narrative. Every detail must provide texture for a novelist "
            "to ground scenes in authentic, specific detail.\n\n"
            "{sensory_model}\n{world_building_rules}"
        ),
        "user": (
            "Create a comprehensive WORLD CODEX.\n\n"
            "STORYLINE:\n{selected_storyline}\n\n"
            "{series_context}\n\n"
            "Include ALL sections:\n"
            "1. GEOGRAPHY & LANDSCAPE — regions, climates, narrative significance\n"
            "2. HISTORY & MYTHOLOGY — world's wound, timeline, contradictory accounts\n"
            "3. CULTURES & SOCIETIES — idioms, customs, food, superstitions per culture\n"
            "4. POLITICAL LANDSCAPE — factions, power dynamics, conflicts\n"
            "5. FLORA & FAUNA — unique species, ecological roles, cultural meaning\n"
            "6. ECONOMY & DAILY LIFE — trade, class structure, ordinary experience\n"
            "7. RELIGION & BELIEF — spiritual systems, sacred places, prophecy\n\n"
            "Target: 8,000-15,000 words. Vivid detail throughout."
        ),
        "max_tokens": 8192,
    },

    "character_creation": {
        "system": (
            "You are a character psychologist creating deep, contradictory, "
            "memorable characters. No cardboard cutouts.\n\n"
            "{character_lens}\n{dialogue_mastery}"
        ),
        "user": (
            "Create detailed CHARACTER PROFILES.\n\n"
            "STORYLINE:\n{selected_storyline}\n\n"
            "WORLD CODEX (excerpt):\n{codex_excerpt}\n\n"
            "For protagonist, antagonist, and 3-5 supporting characters:\n\n"
            "## [NAME]\n\n"
            "### Physical Presence\n"
            "- Distinctive details, clothing, mannerisms, movement\n\n"
            "### Psychology\n"
            "- Core wound, burning desire, greatest fear\n"
            "- Private mythology, meaningful contradictions\n\n"
            "### Voice\n"
            "- Speech patterns, what they never say, how they argue/lie/comfort\n\n"
            "### Relationships\n"
            "- How they relate to each other character\n\n"
            "### Arc\n"
            "- Start → crisis → end, what they sacrifice\n\n"
            "### Role\n"
            "- Skills, why the story needs them, thematic function"
        ),
        "max_tokens": 8192,
    },

    "system_design": {
        "system": (
            "You are designing a {system_type} system that arises naturally from "
            "the world's culture and history, creates opportunities for conflict "
            "and cost, and logically shapes society."
        ),
        "user": (
            "Design the {system_type} system.\n\n"
            "STORYLINE:\n{selected_storyline}\n\n"
            "CODEX (excerpt):\n{codex_excerpt}\n\n"
            "Include:\n"
            "1. CORE MECHANICS — how it works, source, limitations, costs\n"
            "2. RULES — hard rules (inviolable), soft rules (exceptions)\n"
            "3. CULTURAL IMPACT — society, law, economy, warfare, medicine\n"
            "4. NARRATIVE FUNCTION — creates conflict, enables arcs\n"
            "5. AESTHETIC — what it looks/sounds/smells/feels like when active"
        ),
        "max_tokens": 4096,
    },

    # === Phase B: Story Architecture ===

    "book_outline": {
        "system": (
            "You are a master plot architect. Create outlines that follow "
            "human rhythm: quiet reflection, rising tension, release. "
            "Layer intimate moments with world-shaking conflict.\n\n"
            "{pacing_rhythm}"
        ),
        "user": (
            "Create a chapter-by-chapter OUTLINE.\n\n"
            "STORYLINE:\n{selected_storyline}\n\n"
            "{series_context}\n\n"
            "CODEX (excerpt):\n{codex_excerpt}\n\n"
            "CHARACTERS (excerpt):\n{characters_excerpt}\n\n"
            "TARGET: {ch_min}-{ch_max} chapters, {wpc_min}-{wpc_max} words each.\n\n"
            "For EACH chapter:\n\n"
            "## Chapter [N]: [Title]\n\n"
            "**POV Character:** [who]\n"
            "**Location:** [where]\n"
            "**Time:** [when, relative to previous]\n"
            "**Word Count Target:** [specific]\n\n"
            "**Summary:** [3-5 sentences]\n\n"
            "**Key Events:** [list]\n"
            "**Character Development:** [what changes]\n"
            "**Emotional Trajectory:** [opens → peak → closes]\n"
            "**Pacing:** [action-heavy / balanced / reflective / building]\n"
            "**Foreshadowing:** [seeds planted]\n"
            "**Thematic Connection:** [serves the book's theme how]"
        ),
        "max_tokens": 8192,
    },

    "chapter_beat_sheets": {
        "system": (
            "You are a scene architect creating detailed beat sheets that "
            "a writer can execute without ambiguity.\n\n"
            "{sensory_model}\n{escalation_ladder}"
        ),
        "user": (
            "Create detailed BEAT SHEETS for all {total_chapters} chapters.\n\n"
            "OUTLINE:\n{outline_excerpt}\n\n"
            "CODEX (excerpt):\n{codex_excerpt}\n\n"
            "For EACH chapter, provide 3-5 scenes:\n\n"
            "## Chapter [N] Beat Sheet\n\n"
            "### Scene 1: [Title]\n"
            "- **Setting:** [specific location with sensory anchors]\n"
            "- **Characters:** [who is present]\n"
            "- **Opening hook:** [first image]\n"
            "- **Beats:** [numbered sequence of events]\n"
            "- **Sensory anchors:** [sights, smells, sounds, textures, tastes]\n"
            "- **Emotional core:** [what the reader should feel]\n"
            "- **Transition:** [how we move to next scene]\n\n"
            "### Chapter Closing\n"
            "- **Final image:** [last thing reader sees]\n"
            "- **Hook:** [compels turning the page]\n"
            "- **Emotional state:** [how reader feels]"
        ),
        "max_tokens": 8192,
    },

    # === Phase C: Chapter Writing ===

    "scene_planning": {
        "system": (
            "You are expanding a beat sheet into a prose-ready scene plan. "
            "Be specific enough for execution but flexible for creative discovery.\n\n"
            "{sensory_model}"
        ),
        "user": (
            "Expand this beat sheet into a detailed SCENE PLAN.\n\n"
            "CHAPTER {chapter_num} BEATS:\n{chapter_beats}\n\n"
            "CHAPTER {chapter_num} OUTLINE:\n{chapter_outline}\n\n"
            "For each scene:\n"
            "- Opening hook (exact first line or image)\n"
            "- Sensory distribution plan (3-4 visual, 2-3 kinesthetic, "
            "2-3 olfactory, 1-2 auditory, 0-1 gustatory anchors)\n"
            "- Dialogue beats (who speaks to whom, key lines, subtext)\n"
            "- Emotional escalation (entry → trigger → peak → resolution)\n"
            "- POV filter (character notices/misses based on expertise)\n"
            "- Transition to next scene\n"
            "- Target word count for this scene"
        ),
        "max_tokens": 4096,
    },

    "chapter_draft": {
        "system": (
            "You are a master novelist. Your writing is gritty yet beautiful, "
            "visceral yet poetic. Every sentence carries weight.\n\n"
            "{sensory_model}\n{escalation_ladder}\n{character_lens}\n"
            "{anti_ai_voice}\n{show_dont_tell}\n{dialogue_mastery}\n"
            "{pacing_rhythm}\n{world_building_rules}\n{chapter_metrics}\n\n"
            "{genre_overlay}\n\n"
            "## WORLD CONTEXT\n{codex_excerpt}\n\n"
            "## ACTIVE CHARACTERS\n{characters_excerpt}\n\n"
            "## PREVIOUS CHAPTER SUMMARY\n{previous_summary}\n\n"
            "{lessons_overlay}"
        ),
        "user": (
            "Write Chapter {chapter_num}: \"{chapter_title}\"\n\n"
            "SCENE PLAN:\n{scene_plan}\n\n"
            "TARGET: {wpc_min}-{wpc_max} words.\n"
            "POV: {pov}\n"
            "TENSE: {tense}\n\n"
            "REQUIREMENTS:\n"
            "- Sensory grounding in the first 2 paragraphs\n"
            "- Minimum 2 senses per significant paragraph\n"
            "- Dialogue ratio 25-30%\n"
            "- Action beats every 800-1,200 words\n"
            "- Emotional beats every 1,500-2,000 words\n"
            "- End with a hook that compels reading the next chapter\n"
            "- Every paragraph earns its place\n\n"
            "Write the COMPLETE chapter now. Make it alive."
        ),
        "max_tokens": 8192,
    },

    "sensory_enhancement": {
        "system": (
            "You are a sensory immersion specialist. Enhance the chapter's "
            "sensory density to meet targets. Do NOT change plot, dialogue, "
            "or character actions. ENHANCE descriptions and ADD sensory layers.\n\n"
            "{sensory_model}"
        ),
        "user": (
            "Enhance this chapter's sensory density.\n\n"
            "TARGETS: Visual {sensory_visual}, Kinesthetic {sensory_kinesthetic}, "
            "Olfactory {sensory_olfactory}, Auditory {sensory_auditory}, "
            "Gustatory {sensory_gustatory}\n\n"
            "RULES:\n"
            "1. 60-70% of paragraphs should engage 2+ senses\n"
            "2. Olfactory details are CRITICAL — add smell where missing\n"
            "3. Every location needs one unique hyper-specific detail\n"
            "4. Do NOT add gratuitous description — serve the scene\n"
            "5. Word count may increase by up to 5%\n\n"
            "FIX THESE PATTERNS:\n"
            "- 'He entered the room' → what does it look/smell/sound like?\n"
            "- 'She felt afraid' → physical: tight chest, cold hands, copper taste\n"
            "- 'The landscape was barren' → what colour, texture, sound of wind?\n\n"
            "CHAPTER:\n{chapter_text}\n\n"
            "Return the COMPLETE enhanced chapter."
        ),
        "max_tokens": 8192,
    },

    # === Phase D: Style Verification ===

    "voice_consistency": {
        "system": (
            "You are a style consistency auditor. Check for AI-typical phrasing, "
            "voice drift, POV breaks, clichés, and prose quality issues.\n\n"
            "{anti_ai_voice}"
        ),
        "user": (
            "Audit this chapter for voice consistency.\n\n"
            "{style_reference_block}\n\n"
            "CHECK FOR:\n"
            "1. AI-typical phrasing (list above)\n"
            "2. Character voice distinctiveness in dialogue\n"
            "3. Sentence rhythm variation (short for action, long for reflection)\n"
            "4. POV breaks (character knowing others' thoughts)\n"
            "5. Clichés used without subversion\n"
            "6. Generic descriptors ('beautiful', 'amazing')\n"
            "7. Repeated words/phrases within 50-word proximity\n"
            "8. Purple prose (overwrought description slowing pacing)\n"
            "9. Rushed important scenes\n\n"
            "If issues found: fix them, return COMPLETE corrected chapter.\n"
            "If clean: return unchanged with 'VOICE CHECK: CLEAN' at the end.\n\n"
            "CHAPTER:\n{chapter_text}"
        ),
        "max_tokens": 8192,
    },

    # === Phase E: Continuity ===

    "chapter_continuity": {
        "system": (
            "You are a continuity sentinel. Miss nothing. Check every name, "
            "every timeline reference, every world rule, every established fact."
        ),
        "user": (
            "Check this chapter for continuity issues.\n\n"
            "WORLD CODEX (excerpt):\n{codex_excerpt}\n\n"
            "CHARACTERS (excerpt):\n{characters_excerpt}\n\n"
            "PREVIOUS CHAPTERS:\n{previous_summaries}\n\n"
            "CHECK:\n"
            "1. Character name/description consistency\n"
            "2. Timeline integrity (time of day, days elapsed)\n"
            "3. Geography consistency (distances, directions)\n"
            "4. World-rule adherence ({system_type} rules)\n"
            "5. Previously established facts not contradicted\n"
            "6. Characters not knowing things they shouldn't\n"
            "7. Dead-end plot threads\n"
            "8. Foreshadowing consistency\n\n"
            "CHAPTER:\n{chapter_text}\n\n"
            "Report format:\n"
            "## CONTINUITY REPORT — Chapter {chapter_num}\n"
            "### ISSUES FOUND: [count]\n"
            "**Issue N:** [description]\n"
            "- Location: [where]\n- Conflict: [what vs what]\n"
            "- Fix: [how to resolve]\n\n"
            "If no issues: 'CONTINUITY CHECK: CLEAN — 0 issues found.'"
        ),
        "max_tokens": 4096,
    },

    "pre_review_polish": {
        "system": (
            "You are a fiction copyeditor. Fix ONLY errors. Do NOT rewrite "
            "for style, add/remove content, or change voice."
        ),
        "user": (
            "Polish this chapter. Fix ONLY:\n"
            "- Typos and spelling\n"
            "- Grammar\n"
            "- Punctuation (especially dialogue)\n"
            "- Awkward phrasing disrupting flow\n"
            "- Repeated words within 50-word proximity\n\n"
            "Do NOT change character voice, plot, dialogue meaning, or style.\n\n"
            "CHAPTER:\n{chapter_text}\n\n"
            "Return the COMPLETE polished chapter."
        ),
        "max_tokens": 8192,
    },

    # === Phase F: Critical Review ===

    "independent_review": {
        "system": (
            "You are an independent literary critic who has reviewed hundreds of "
            "published novels. You rate on a /10 scale with decimals. You do NOT "
            "grade on a curve. An 8 is genuinely good. A 9 is exceptional.\n\n"
            "You have NO knowledge of the author's planning documents, beat sheets, "
            "or world codex. You judge ONLY what is on the page.\n\n"
            "EVALUATION CRITERIA (weighted):\n"
            "- Prose quality (25%): Rhythm, imagery, word choice, sensory density\n"
            "- Character authenticity (20%): Voice, motivation, emotional truth\n"
            "- Pacing (20%): Tension, release, momentum\n"
            "- Sensory immersion (15%): Environmental grounding, five-sense engagement\n"
            "- Emotional impact (10%): Reader engagement, stakes\n"
            "- Dialogue quality (10%): Natural, revealing, distinctive\n\n"
            "RULES:\n"
            "- Never be lenient because the writing is 'pretty good for AI'\n"
            "- Judge as you would a debut novel submitted to a major publisher\n"
            "- Call out clichés by name\n"
            "- If dialogue sounds generic, say so\n"
            "- If sensory detail is thin, identify exactly where\n"
            "- If pacing drags, point to the exact passage"
        ),
        "user": (
            "Review this chapter from a {genre} novel (~{total_word_count} words total).\n"
            "This is Chapter {chapter_num}.\n\n"
            "Provide:\n"
            "1. OVERALL RATING: X.X/10\n"
            "2. WHAT WORKS (3-5 specific elements with references)\n"
            "3. WHAT DOESN'T WORK (3-5 specific elements with references)\n"
            "4. SPECIFIC SUGGESTIONS (3-5, each with WHAT/WHERE/HOW)\n"
            "5. PATH TO IMPROVEMENT: 'With these changes → X.X/10'\n\n"
            "CHAPTER TEXT:\n\n{chapter_text}"
        ),
        "max_tokens": 4096,
    },

    "review_analysis_critic": {
        "system": "You are a {critic_type} specialist analysing reviewer feedback.",
        "user": (
            "Analyse the review and chapter focusing on {focus_area}.\n\n"
            "REVIEW:\n{review_text}\n\n"
            "CHAPTER (excerpt):\n{chapter_excerpt}\n\n"
            "{extra_context}\n\n"
            "Propose 1-3 specific {focus_area} adjustments with exact locations."
        ),
        "max_tokens": 2048,
    },

    "enhancement_decision": {
        "system": (
            "You are a quality director deciding whether a chapter is ready "
            "for publication. You are analytical and data-driven."
        ),
        "user": (
            "REVIEW 1 (Literary Critic):\n"
            "Rating: {review_1_rating}/10\n{review_1_summary}\n\n"
            "MULTI-CRITIC ANALYSIS:\n{analysis_summary}\n\n"
            "Enhancement loops completed: {loop_count}/{max_loops}\n"
            "Rewrite attempts: {rewrite_count}/{max_rewrites}\n\n"
            "THRESHOLDS:\n"
            "- PROCEED: >= {min_proceed}\n"
            "- REFINE: >= {min_refine}\n"
            "- REWRITE: < {min_refine}\n\n"
            "DECIDE and provide rationale.\n"
            "Response format: DECISION: [PROCEED/REFINE/REWRITE/HUMAN_ESCALATION]\n"
            "RATIONALE: [explanation]"
        ),
        "max_tokens": 1024,
    },

    # === Phase G: Enhancement Loop ===

    "surgical_enhancement": {
        "system": (
            "You are a surgical editor applying Phase 1.X enhancements. "
            "Change ONLY what is needed. Preserve all strengths.\n\n"
            "{anti_ai_voice}"
        ),
        "user": (
            "Apply {phase_name} surgical enhancements.\n\n"
            "REVIEWER FEEDBACK:\n{review_text}\n\n"
            "CRITIC ANALYSIS:\n{analysis_text}\n\n"
            "RULES:\n"
            "1. Word count increase <=5%\n"
            "2. TARGETED changes only — not a rewrite\n"
            "3. Highest-impact issues first\n"
            "4. Preserve all identified strengths\n"
            "5. Every change serves a specific purpose\n"
            "6. No new plot elements or character arcs\n\n"
            "PHASE FOCUS:\n{phase_focus}\n\n"
            "CHAPTER:\n{chapter_text}\n\n"
            "Return COMPLETE enhanced chapter.\n"
            "After '---' separator, list each change made."
        ),
        "max_tokens": 8192,
    },

    "re_review": {
        "system": (
            "You are a reader who has consumed 500+ books in {genre}. You are NOT "
            "a critic — you are a READER. You evaluate from the perspective of "
            "someone who paid money for this book on a Saturday night.\n\n"
            "You have NO knowledge of prior reviews. FRESH EYES.\n\n"
            "RULES:\n"
            "- Be honest. If you got bored, say where.\n"
            "- If a character felt flat, name them.\n"
            "- If dialogue sounded like two AIs talking, say so.\n"
            "- Trust your gut."
        ),
        "user": (
            "Read Chapter {chapter_num} of a {genre} novel.\n\n"
            "Provide:\n"
            "1. ENGAGEMENT RATING: X.X/10\n"
            "2. PAGE-TURNER MOMENTS (2-4)\n"
            "3. DRAG POINTS (2-4)\n"
            "4. CONFUSION POINTS (1-3)\n"
            "5. EMOTIONAL PEAKS (1-3)\n"
            "6. CHARACTER INVESTMENT: who you care about and why\n"
            "7. MEMORABILITY: what you'll remember tomorrow\n"
            "8. SUGGESTIONS (3-5)\n\n"
            "CHAPTER TEXT:\n\n{chapter_text}"
        ),
        "max_tokens": 4096,
    },

    # === Phase H: Assembly ===

    "chapter_summary": {
        "system": "You are a precise summariser. Be concise and accurate.",
        "user": (
            "Summarise this chapter in 200-300 words for continuity reference.\n"
            "Include: key events, character emotional states at end, world "
            "revelations, foreshadowing seeds planted, closing situation.\n\n"
            "CHAPTER:\n{chapter_text}"
        ),
        "max_tokens": 512,
    },

    "continuity_verify_section": {
        "system": "You are a continuity checker. Be thorough.",
        "user": (
            "Check this manuscript section for continuity issues.\n\n"
            "CODEX (excerpt):\n{codex_excerpt}\n"
            "CHARACTERS (excerpt):\n{characters_excerpt}\n\n"
            "SECTION {section_num}/{total_sections}:\n{section_text}\n\n"
            "Report: ISSUE: [desc] | LOCATION: [where] | SEVERITY: [high/med/low]\n"
            "If no issues: 'SECTION CLEAN'"
        ),
        "max_tokens": 1024,
    },

    "style_consistency_check": {
        "system": "You are a prose style analyst. Detect voice drift.",
        "user": (
            "Compare these excerpts from the same novel for STYLE CONSISTENCY.\n\n"
            "OPENING:\n{opening_sample}\n\n"
            "MIDDLE:\n{middle_sample}\n\n"
            "ENDING:\n{ending_sample}\n\n"
            "Check: voice drift, sensory density consistency, sentence rhythm, "
            "character voice consistency, narrative distance.\n"
            "If consistent: 'STYLE CONSISTENCY: MAINTAINED'"
        ),
        "max_tokens": 2048,
    },

    # === Phase I: Publishing ===

    "book_description": {
        "system": (
            "You are an Amazon book marketing specialist. Write descriptions "
            "that convert browsers into buyers."
        ),
        "user": (
            "Write an Amazon book description.\n"
            "Title: {title}\nGenre: {genre}\nAuthor: {author}\n"
            "Chapters: {total_chapters}, Words: {total_words}\n"
            "{series_info}\n\n"
            "Write in HTML. Include hook, premise (no spoilers), call to action.\n"
            "Maximum 4000 characters."
        ),
        "max_tokens": 1024,
    },

    "keywords_generation": {
        "system": "You are a KDP metadata specialist.",
        "user": (
            "Generate 7 Amazon KDP keywords for:\n"
            "Title: {title}\nGenre: {genre}\n"
            "Themes: {themes}\n\n"
            "One keyword per line. Use reader search terms, not industry jargon."
        ),
        "max_tokens": 256,
    },

    "continuity_fix": {
        "system": (
            "Fix continuity issues. Change ONLY what is necessary. "
            "Do NOT rewrite sections that are not flagged."
        ),
        "user": (
            "CONTINUITY REPORT:\n{report}\n\n"
            "CHAPTER:\n{chapter_text}\n\n"
            "Return the COMPLETE fixed chapter."
        ),
        "max_tokens": 8192,
    },
}


# ---------------------------------------------------------------------------
# Secondary / sub-prompts
# ---------------------------------------------------------------------------

_DEFAULT_SUB_PROMPTS: dict[str, dict[str, str]] = {
    "pacing_critic": {
        "system": (
            "You are a pacing specialist. Analyse rhythm and momentum."
        ),
        "focus": (
            "Where does tension build? Where does it sag? Are scene lengths "
            "appropriate? Is the chapter-ending hook strong? Action vs reflection ratio?"
        ),
    },
    "character_critic": {
        "system": "You are a character specialist. Analyse authenticity.",
        "focus": (
            "Does each character sound distinct? Physical mannerisms consistent? "
            "Emotional reactions earned? POV expertise filter correct? Any generic characters?"
        ),
    },
    "prose_critic": {
        "system": "You are a prose specialist. Analyse language quality.",
        "focus": (
            "Sensory immersion maintained (60-70% with 2+ senses)? Five senses balanced? "
            "Clichés or AI phrases? Rhythm varied? Any dead paragraphs?"
        ),
    },
    "continuity_critic": {
        "system": "You are a continuity specialist. Check consistency.",
        "focus": (
            "Names consistent? Timeline makes sense? World rules hold? "
            "Foreshadowing seeds planted/harvested? Any contradictions?"
        ),
    },
}


# ---------------------------------------------------------------------------
# Genre overlay prompts
# ---------------------------------------------------------------------------

_GENRE_OVERLAY_PROMPTS: dict[str, str] = {
    "epic_fantasy": (
        "## GENRE: EPIC FANTASY\n"
        "- Start with the world's wound\n"
        "- Magic from culture, environment, spiritual worldview\n"
        "- Mythic beats: omens, symbols, ancestral echoes\n"
        "- Unique idioms, proverbs, rituals per culture\n"
        "- Landscapes hold grudges, rivers remember\n"
        "- Creatures with ecological roles and cultural meaning\n"
        "- Boost olfactory +5%, gustatory +3%"
    ),
    "techno_thriller": (
        "## GENRE: TECHNO-THRILLER\n"
        "- Filter through technical expertise (aviation, diving, military)\n"
        "- Ground the fantastic in physical reality\n"
        "- Authentic vocabulary, never showing off\n"
        "- Relentless pacing — every scene justified\n"
        "- The clock is always ticking\n"
        "- Boost kinesthetic +5%, auditory +3%"
    ),
    "dark_fantasy": (
        "## GENRE: DARK FANTASY\n"
        "- Horror from beauty corrupted, not shock\n"
        "- Supernatural follows rules — terror in learning them\n"
        "- Cosmic indifference > active malice\n"
        "- Physical transformation mirrors psychological decay\n"
        "- Boost olfactory +8%, auditory +5%"
    ),
    "sci_fi": (
        "## GENRE: SCI-FI\n"
        "- Technology shapes society — show ripple effects\n"
        "- Science internally consistent even if speculative\n"
        "- Alien perspectives genuinely alien\n"
        "- Scale creates awe — convey vastness\n"
        "- Boost visual +5%, kinesthetic +3%"
    ),
    "horror": (
        "## GENRE: HORROR\n"
        "- Ordinary becoming wrong > monsters\n"
        "- Withhold more than reveal\n"
        "- Isolation is a character\n"
        "- Time distortion amplifies dread\n"
        "- Boost auditory +10%, olfactory +8%"
    ),
    "romance": (
        "## GENRE: ROMANCE\n"
        "- Physical awareness precedes emotional\n"
        "- Tension from proximity and restraint\n"
        "- Body notices before mind admits\n"
        "- Slow-burn: hand → arm → face → more\n"
        "- Boost kinesthetic +10%, olfactory +5%"
    ),
    "literary_fiction": (
        "## GENRE: LITERARY FICTION\n"
        "- Interior life is primary landscape\n"
        "- Metaphor carries thematic weight\n"
        "- Structure itself is narrative device\n"
        "- Silence and absence matter\n"
        "- Boost gustatory +5%, kinesthetic +3%"
    ),
    "mystery": (
        "## GENRE: MYSTERY\n"
        "- Clues hidden in description\n"
        "- Every character is a suspect\n"
        "- Red herrings as satisfying as real clues\n"
        "- Atmosphere is evidence\n"
        "- Boost visual +5%, olfactory +3%"
    ),
}


# ---------------------------------------------------------------------------
# Enhancement phase focus descriptions
# ---------------------------------------------------------------------------

_PHASE_FOCUS: dict[int, str] = {
    0: (
        "Phase 1 — FOUNDATION:\n"
        "- Character gestures and mannerisms (add distinctive habits)\n"
        "- Named secondary characters (replace 'the guard' with a name)\n"
        "- Pacing adjustments (compress or expand scenes)\n"
        "- Sensory gaps (fill missing sense channels)"
    ),
    1: (
        "Phase 1.5 — THEMATIC UNITY:\n"
        "- Cultural layering (idioms, proverbs, customs woven in)\n"
        "- Motif threading (recurring symbols connected across scenes)\n"
        "- Magic/tech system grounding (show societal impact)\n"
        "- Auditory/sensory metaphor consistency"
    ),
    2: (
        "Phase 1.75 — GENRE OPTIMIZATION:\n"
        "- Genre-specific elements strengthened\n"
        "- Subgenre elements balanced\n"
        "- Foreshadowing density checked\n"
        "- Emotional escalation calibrated"
    ),
}


# ---------------------------------------------------------------------------
# Prompt Manager
# ---------------------------------------------------------------------------

class PromptManager:
    """Load, merge, and render stage prompts.

    Parameters
    ----------
    custom_file : str or Path, optional
        Path to a user-provided YAML file that overrides default prompts.
        Structure mirrors ``_DEFAULT_STAGES`` / ``_DEFAULT_BLOCKS``.
    """

    def __init__(self, custom_file: str | Path | None = None) -> None:
        self._stages = dict(_DEFAULT_STAGES)
        self._blocks = dict(_DEFAULT_BLOCKS)
        self._sub_prompts = dict(_DEFAULT_SUB_PROMPTS)
        self._genre_overlays = dict(_GENRE_OVERLAY_PROMPTS)
        self._phase_focus = dict(_PHASE_FOCUS)

        if custom_file:
            self._merge_overrides(Path(custom_file))

    def _merge_overrides(self, path: Path) -> None:
        """Merge user-provided YAML overrides on top of defaults."""
        if not path.exists():
            logger.warning("Custom prompts file not found: %s", path)
            return

        with open(path) as f:
            data = yaml.safe_load(f) or {}

        # Merge blocks
        if "blocks" in data and isinstance(data["blocks"], dict):
            self._blocks.update(data["blocks"])

        # Merge stages
        if "stages" in data and isinstance(data["stages"], dict):
            for stage_name, overrides in data["stages"].items():
                if stage_name in self._stages:
                    self._stages[stage_name].update(overrides)
                else:
                    self._stages[stage_name] = overrides

        # Merge genre overlays
        if "genre_overlays" in data and isinstance(data["genre_overlays"], dict):
            self._genre_overlays.update(data["genre_overlays"])

        logger.info("Merged prompt overrides from %s", path)

    def for_stage(self, stage_name: str, **variables: str) -> RenderedPrompt:
        """Render the prompt for a given stage.

        Parameters
        ----------
        stage_name : str
            The stage key (e.g., "chapter_draft", "independent_review").
        **variables :
            Template variables to substitute (e.g., chapter_num="3").

        Returns
        -------
        RenderedPrompt
            Ready for ``llm.complete()``.
        """
        stage_def = self._stages.get(stage_name)
        if stage_def is None:
            raise KeyError(f"No prompt defined for stage '{stage_name}'")

        # First: resolve block references in system and user prompts
        system_raw = stage_def.get("system", "")
        user_raw = stage_def.get("user", "")

        # Expand block references like {sensory_model}, {anti_ai_voice}
        system_with_blocks = _render(system_raw, self._blocks)
        user_with_blocks = _render(user_raw, self._blocks)

        # Then: expand variables
        system_final = _render(system_with_blocks, variables)
        user_final = _render(user_with_blocks, variables)

        return RenderedPrompt(
            system=system_final,
            user=user_final,
            json_mode=stage_def.get("json_mode", False),
            max_tokens=stage_def.get("max_tokens"),
        )

    def get_genre_overlay(self, genre: str) -> str:
        """Get the genre overlay prompt text."""
        key = genre.lower().replace("-", "_").replace(" ", "_")
        return self._genre_overlays.get(key, "")

    def get_phase_focus(self, loop_index: int) -> str:
        """Get the enhancement phase focus description."""
        return self._phase_focus.get(loop_index, f"Phase 1.{loop_index} — reviewer-specific fixes")

    def get_critic_prompt(self, critic_name: str) -> dict[str, str]:
        """Get a debate critic's system prompt and focus area."""
        return self._sub_prompts.get(critic_name, {
            "system": f"You are a {critic_name.replace('_', ' ')}.",
            "focus": "Analyse and provide suggestions.",
        })

    def list_stages(self) -> list[str]:
        """Return all available stage prompt names."""
        return sorted(self._stages.keys())

    def list_blocks(self) -> list[str]:
        """Return all available block names."""
        return sorted(self._blocks.keys())
