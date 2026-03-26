"""Tests for prompt system, pipeline state, and utility functions."""

import json
from pathlib import Path
import pytest

from autonovelclaw.prompts import PromptManager


class TestWriterPrompt:

    def setup_method(self):
        self.pm = PromptManager()
        self.vars = dict(
            genre_overlay="", codex_excerpt="", characters_excerpt="",
            previous_summary="", lessons_overlay="",
            chapter_num="1", chapter_title="Test", scene_plan="",
            sensory_visual="40%", sensory_kinesthetic="25%",
            sensory_olfactory="20%", sensory_auditory="10%",
            sensory_gustatory="5%", wpc_min="6000", wpc_max="8800",
            pov="third-person", tense="past",
        )

    def test_contains_sensory_model(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        assert "VISUAL" in rp.system or "visual" in rp.system.lower()

    def test_contains_escalation_ladder(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        combined = rp.system + rp.user
        assert "escalation" in combined.lower() or "breaking point" in combined.lower()

    def test_contains_character_lens(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        assert "POV" in rp.system or "character" in rp.system.lower()

    def test_contains_anti_ai_phrasing(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        assert "palpable" in rp.system.lower() or "tapestry" in rp.system.lower()

    def test_contains_target_metrics(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        combined = rp.system + rp.user
        assert "6000" in combined or "word" in combined.lower()

    def test_no_empty_prompt(self):
        rp = self.pm.for_stage("chapter_draft", **self.vars)
        assert len(rp.system) > 100
        assert len(rp.user) > 50


class TestReviewerPrompts:

    def setup_method(self):
        self.pm = PromptManager()

    def test_reviewer_1_rates_on_10(self):
        rp = self.pm.for_stage("independent_review", genre="epic fantasy",
                               total_word_count="80,000", chapter_num="1", chapter_text="Test")
        assert "/10" in rp.system or "10" in rp.system

    def test_reviewer_1_has_evaluation_criteria(self):
        rp = self.pm.for_stage("independent_review", genre="epic fantasy",
                               total_word_count="80,000", chapter_num="1", chapter_text="Test")
        assert "prose" in rp.system.lower() or "character" in rp.system.lower()

    def test_reviewer_2_is_reader_perspective(self):
        rp = self.pm.for_stage("re_review", genre="epic fantasy", chapter_num="1", chapter_text="Test")
        assert "reader" in rp.system.lower() or "engagement" in rp.system.lower()

    def test_reviewer_2_has_no_prior_reviews(self):
        rp = self.pm.for_stage("re_review", genre="epic fantasy", chapter_num="1", chapter_text="Test")
        assert "fresh" in rp.system.lower() or "no knowledge" in rp.system.lower()

    def test_reviewers_are_different(self):
        r1 = self.pm.for_stage("independent_review", genre="fantasy",
                               total_word_count="80,000", chapter_num="1", chapter_text="Test")
        r2 = self.pm.for_stage("re_review", genre="fantasy", chapter_num="1", chapter_text="Test")
        assert r1.system != r2.system


class TestGenreOverlays:

    def setup_method(self):
        self.pm = PromptManager()

    def test_all_genres_present(self):
        for genre in ["epic_fantasy", "techno_thriller", "dark_fantasy", "sci_fi",
                       "horror", "romance", "literary_fiction", "mystery"]:
            assert self.pm.get_genre_overlay(genre), f"Missing: {genre}"

    def test_overlays_are_nonempty(self):
        for genre in ["epic_fantasy", "techno_thriller", "dark_fantasy"]:
            assert len(self.pm.get_genre_overlay(genre)) > 50

    def test_epic_fantasy_has_world_wound(self):
        assert "wound" in self.pm.get_genre_overlay("epic_fantasy").lower()

    def test_techno_thriller_has_expertise(self):
        overlay = self.pm.get_genre_overlay("techno_thriller")
        assert "technical" in overlay.lower() or "expertise" in overlay.lower()


class TestDebateCritics:

    def setup_method(self):
        self.pm = PromptManager()

    def test_all_critics_present(self):
        for name in ["pacing_critic", "character_critic", "prose_critic", "continuity_critic"]:
            critic = self.pm.get_critic_prompt(name)
            assert "system" in critic or "focus" in critic

    def test_prose_critic_checks_sensory(self):
        assert "sensory" in self.pm.get_critic_prompt("prose_critic").get("focus", "").lower()

    def test_continuity_critic_checks_names(self):
        focus = self.pm.get_critic_prompt("continuity_critic").get("focus", "").lower()
        assert "name" in focus or "consistent" in focus


class TestPromptManager:

    def test_list_stages(self):
        pm = PromptManager()
        stages = pm.list_stages()
        assert "chapter_draft" in stages
        assert "independent_review" in stages
        assert len(stages) >= 20

    def test_list_blocks(self):
        pm = PromptManager()
        blocks = pm.list_blocks()
        assert "sensory_model" in blocks
        assert "anti_ai_voice" in blocks

    def test_genre_overlay_unknown_returns_empty(self):
        assert PromptManager().get_genre_overlay("nonexistent_genre") == ""

    def test_template_rendering(self):
        rp = PromptManager().for_stage("idea_intake", topic="Dragons in space")
        assert "Dragons in space" in rp.user
        assert rp.json_mode is True

    def test_phase_focus(self):
        pm = PromptManager()
        assert "Phase 1" in pm.get_phase_focus(0) or "FOUNDATION" in pm.get_phase_focus(0)
        assert "1.5" in pm.get_phase_focus(1) or "THEMATIC" in pm.get_phase_focus(1)


class TestPipelineState:

    def test_state_creation(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        ckpt = Checkpoint(tmp_path)
        ckpt.run_id = "test-run"
        ckpt.current_chapter = 3
        ckpt.save()
        assert ckpt.run_id == "test-run"
        assert ckpt.current_chapter == 3

    def test_state_persistence(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        ckpt = Checkpoint(tmp_path)
        ckpt.store_artifact("test_key", {"data": 42})
        ckpt.save()
        ckpt2 = Checkpoint(tmp_path)
        assert ckpt2.get_artifact("test_key") == {"data": 42}

    def test_state_decision_recording(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        ckpt = Checkpoint(tmp_path)
        ckpt.record_decision("stage_1", "proceed", "Rating 9.2")
        assert len(ckpt.decisions) == 1
        assert ckpt.decisions[0]["decision"] == "proceed"


class TestTokenUtils:

    def test_estimate_tokens(self):
        from autonovelclaw.utils import estimate_tokens
        assert estimate_tokens("hello world") > 0

    def test_truncate_short_text(self):
        from autonovelclaw.utils import truncate_to_tokens
        assert truncate_to_tokens("Short text", 1000) == "Short text"

    def test_truncate_long_text(self):
        from autonovelclaw.utils import truncate_to_tokens
        text = "word " * 10000
        assert len(truncate_to_tokens(text, 100)) < len(text)

    def test_word_count(self):
        from autonovelclaw.utils import word_count
        assert word_count("one two three") == 3

    def test_chunk_for_context_short(self):
        from autonovelclaw.utils import chunk_for_context
        assert len(chunk_for_context("Short text", max_tokens=1000)) == 1

    def test_chunk_for_context_long(self):
        from autonovelclaw.utils import chunk_for_context
        assert len(chunk_for_context("word " * 10000, max_tokens=100)) > 1


class TestEditorPrompt:

    def test_editor_knows_kdp(self):
        rp = PromptManager().for_stage("book_description", title="Test", genre="fantasy",
                                       author="Author", total_chapters="25",
                                       total_words="80,000", series_info="", themes="fantasy")
        assert "amazon" in rp.system.lower() or "description" in rp.system.lower()

    def test_editor_knows_epub(self):
        from autonovelclaw.publishing.epub_builder import EPUB_CSS
        assert "font-family" in EPUB_CSS

    def test_editor_knows_typography(self):
        from autonovelclaw.publishing.pdf_builder import TRIM_SIZES
        assert "6x9" in TRIM_SIZES


class TestIdeationPrompt:

    def test_ideation_generates_multiple(self):
        rp = PromptManager().for_stage("storyline_generation", storyline_count="10",
                                       parsed_concept='{"core": "test"}')
        assert "10" in rp.user or "distinct" in rp.user.lower()

    def test_ideation_requires_diversity(self):
        rp = PromptManager().for_stage("storyline_generation", storyline_count="10",
                                       parsed_concept='{"core": "test"}')
        assert "different" in rp.system.lower() or "diversity" in rp.system.lower() or "distinct" in rp.system.lower()
