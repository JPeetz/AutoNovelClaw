"""Tests for Phase 2 components: evolution, health, quality, LLM factory."""

import json
from pathlib import Path
import pytest

from autonovelclaw.config import NovelClawConfig


# ============================================================================
# Evolution tests
# ============================================================================

class TestEvolutionStore:

    def test_append_and_load(self, tmp_path: Path):
        from autonovelclaw.evolution import EvolutionStore, LessonEntry
        store = EvolutionStore(tmp_path / "evo")

        lesson = LessonEntry(
            stage_name="chapter_draft",
            stage_num=12,
            category="prose",
            severity="warning",
            description="Weak sensory immersion in chapter 3",
            timestamp="2026-03-18T12:00:00+00:00",
        )
        store.append(lesson)
        loaded = store.load_all()
        assert len(loaded) == 1
        assert loaded[0].stage_name == "chapter_draft"
        assert loaded[0].category == "prose"

    def test_append_many(self, tmp_path: Path):
        from autonovelclaw.evolution import EvolutionStore, LessonEntry
        store = EvolutionStore(tmp_path / "evo")

        lessons = [
            LessonEntry("s1", 1, "prose", "info", "test1", "2026-03-18T12:00:00+00:00"),
            LessonEntry("s2", 2, "pacing", "warning", "test2", "2026-03-18T12:00:00+00:00"),
            LessonEntry("s3", 3, "character", "error", "test3", "2026-03-18T12:00:00+00:00"),
        ]
        store.append_many(lessons)
        assert store.count() == 3

    def test_query_for_stage_prioritises_direct_match(self, tmp_path: Path):
        from autonovelclaw.evolution import EvolutionStore, LessonEntry
        store = EvolutionStore(tmp_path / "evo")

        store.append_many([
            LessonEntry("chapter_draft", 12, "prose", "warning", "direct match",
                        "2026-03-18T12:00:00+00:00"),
            LessonEntry("other_stage", 5, "prose", "error", "indirect match",
                        "2026-03-18T12:00:00+00:00"),
        ])

        results = store.query_for_stage("chapter_draft", max_lessons=1)
        assert len(results) == 1
        assert results[0].description == "direct match"

    def test_empty_store_returns_empty(self, tmp_path: Path):
        from autonovelclaw.evolution import EvolutionStore
        store = EvolutionStore(tmp_path / "evo_empty")
        assert store.load_all() == []
        assert store.count() == 0
        assert store.build_overlay("any_stage") == ""

    def test_build_overlay_formats_lessons(self, tmp_path: Path):
        from autonovelclaw.evolution import EvolutionStore, LessonEntry
        store = EvolutionStore(tmp_path / "evo")
        store.append(LessonEntry(
            "chapter_draft", 12, "prose", "error",
            "Chapter 3 had weak olfactory content",
            "2026-03-18T12:00:00+00:00",
        ))
        overlay = store.build_overlay("chapter_draft")
        assert "Lessons from Prior" in overlay
        assert "olfactory" in overlay


class TestLessonExtraction:

    def test_extract_from_decisions(self):
        from autonovelclaw.evolution import extract_lessons_from_decisions
        decisions = [
            {"stage": "ed_ch3", "decision": "rewrite", "rationale": "Rating 6.5", "chapter": 3},
            {"stage": "ed_ch5", "decision": "refine", "rationale": "Pacing dragged", "chapter": 5},
            {"stage": "ed_ch7", "decision": "proceed", "rationale": "Rating 9.2", "chapter": 7},
        ]
        lessons = extract_lessons_from_decisions(decisions, run_id="test")
        # proceed doesn't generate a lesson, rewrite and refine do
        assert len(lessons) == 2
        assert any("REWRITE" in l.description for l in lessons)
        assert any("REFINE" in l.description for l in lessons)

    def test_extract_from_reviews(self):
        from autonovelclaw.evolution import extract_lessons_from_reviews
        review = "The sensory immersion is thin in the middle section. Dialogue felt flat and generic."
        lessons = extract_lessons_from_reviews(review, chapter=4, rating=7.8)
        assert len(lessons) >= 1  # Should catch "sensory thin" and/or "dialogue flat"

    def test_extract_from_enhancement(self):
        from autonovelclaw.evolution import extract_lessons_from_enhancement
        lessons = extract_lessons_from_enhancement(
            chapter=2, phase_name="Phase 1", rating_before=7.5,
            rating_after=8.3, change_log="Added olfactory anchors",
        )
        assert len(lessons) == 1
        assert lessons[0].category == "enhancement"
        assert lessons[0].rating_before == 7.5
        assert lessons[0].rating_after == 8.3


# ============================================================================
# Health tests
# ============================================================================

class TestHealthChecks:

    def test_python_version_passes(self):
        from autonovelclaw.health import check_python_version
        result = check_python_version()
        assert result.status == "pass"  # We're running on 3.11+

    def test_config_valid_with_defaults(self):
        from autonovelclaw.health import check_config_valid
        config = NovelClawConfig()
        result = check_config_valid(config)
        assert result.status == "pass"

    def test_config_valid_catches_bad_thresholds(self):
        from autonovelclaw.health import check_config_valid
        config = NovelClawConfig()
        config.review.min_rating_refine = 9.5  # Higher than proceed!
        config.review.min_rating_proceed = 9.0
        result = check_config_valid(config)
        assert result.status == "warn"
        assert "min_rating_refine" in result.detail

    def test_required_packages_present(self):
        from autonovelclaw.health import check_required_packages
        result = check_required_packages()
        # All required packages should be installed in our test env
        assert result.status in ("pass", "warn")

    def test_disk_space_check(self):
        from autonovelclaw.health import check_disk_space
        config = NovelClawConfig()
        config.runtime.output_dir = "/tmp"
        result = check_disk_space(config)
        assert result.status in ("pass", "warn")

    def test_output_writable(self, tmp_path: Path):
        from autonovelclaw.health import check_output_dir_writable
        config = NovelClawConfig()
        config.runtime.output_dir = str(tmp_path / "test_output")
        result = check_output_dir_writable(config)
        assert result.status == "pass"

    def test_api_key_missing_fails(self):
        from autonovelclaw.health import check_api_key
        config = NovelClawConfig()
        config.llm.api_key = ""
        config.llm.api_key_env = "NONEXISTENT_KEY_12345"
        result = check_api_key(config)
        assert result.status == "fail"
        assert result.fix  # Should have a fix suggestion

    def test_cover_image_not_specified(self):
        from autonovelclaw.health import check_cover_image
        config = NovelClawConfig()
        result = check_cover_image(config)
        assert result.status == "pass"

    def test_cover_image_missing_warns(self):
        from autonovelclaw.health import check_cover_image
        config = NovelClawConfig()
        config.inputs.cover_image = "/nonexistent/cover.jpg"
        result = check_cover_image(config)
        assert result.status == "warn"

    def test_run_doctor_returns_report(self, tmp_path: Path):
        from autonovelclaw.health import run_doctor
        config = NovelClawConfig()
        config.runtime.output_dir = str(tmp_path)
        config.llm.api_key = "test-key"  # Prevent fail
        report = run_doctor(config)
        assert report.passed > 0
        assert report.overall in ("pass", "warn", "fail")
        assert report.to_markdown()  # Should produce valid markdown

    def test_doctor_report_to_dict(self, tmp_path: Path):
        from autonovelclaw.health import run_doctor
        config = NovelClawConfig()
        config.runtime.output_dir = str(tmp_path)
        config.llm.api_key = "test-key"
        report = run_doctor(config)
        d = report.to_dict()
        assert "checks" in d
        assert "overall" in d
        assert isinstance(d["checks"], list)


# ============================================================================
# Quality tests
# ============================================================================

class TestQualityAssessment:

    def test_clean_text_scores_high(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = (
            "The morning light filtered through gaps in the corrugated metal roof, "
            "each beam catching particles of dust that swirled like restless memories. "
            "Outside, salt air carried the green-rot scent of seaweed drying on pilings. " * 50
        )
        report = assess_chapter_quality(text, min_words=100)
        assert report.overall_score >= 70
        assert report.total_words > 100

    def test_ai_cliches_detected(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = (
            "It's worth noting that the tapestry of fate wove a symphony of "
            "emotions. Moreover, the palpable tension filled the room. "
            "Furthermore, time stood still as she painted the sky with her gaze. " * 20
        )
        report = assess_chapter_quality(text, min_words=50)
        cliche_issues = [i for i in report.issues if i.category == "ai_cliche"]
        assert len(cliche_issues) >= 3

    def test_placeholders_detected(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = (
            "The hero walked toward [INSERT LOCATION]. [TODO: add description] "
            "Lorem ipsum dolor sit amet. [PLACEHOLDER: battle scene] " * 20
        )
        report = assess_chapter_quality(text, min_words=50)
        placeholder_issues = [i for i in report.issues if i.category == "placeholder"]
        assert len(placeholder_issues) >= 2

    def test_generic_descriptors_detected(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = (
            "It was beautiful. She felt afraid. He was angry. "
            "It was very amazing and incredibly wonderful. " * 30
        )
        report = assess_chapter_quality(text, min_words=50)
        generic_issues = [i for i in report.issues if i.category == "generic"]
        assert len(generic_issues) >= 2

    def test_sensory_analysis(self):
        from autonovelclaw.quality import assess_chapter_quality
        # Text heavy on visual, light on olfactory
        text = (
            "The bright light gleamed off the silver surface. Shadows danced "
            "across the gleaming walls. The vivid colours shimmered. " * 30
        )
        report = assess_chapter_quality(text, min_words=50)
        assert report.sensory_distribution["visual"] > 0.3
        # Should flag low olfactory
        sensory_issues = [i for i in report.issues if i.category == "sensory"]
        assert len(sensory_issues) >= 1  # At least olfactory should be flagged

    def test_short_text_flagged(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = "This is too short."
        report = assess_chapter_quality(text, min_words=3000)
        assert any(i.category == "structure" and "below minimum" in i.description
                   for i in report.issues)

    def test_quality_report_to_markdown(self):
        from autonovelclaw.quality import assess_chapter_quality
        text = "Some text here. " * 100
        report = assess_chapter_quality(text, min_words=50)
        md = report.to_markdown()
        assert "Quality Report" in md
        assert "Score:" in md


# ============================================================================
# LLM factory tests
# ============================================================================

class TestLLMFactory:

    def test_create_anthropic_client(self):
        from autonovelclaw.llm import create_llm_client
        from autonovelclaw.llm.anthropic import AnthropicClient
        config = NovelClawConfig()
        config.llm.provider = "anthropic"
        config.llm.api_key = "test-key"
        client = create_llm_client(config.llm)
        assert isinstance(client, AnthropicClient)
        client.close()

    def test_create_openai_client(self):
        from autonovelclaw.llm import create_llm_client
        from autonovelclaw.llm.openai_compat import OpenAICompatClient
        config = NovelClawConfig()
        config.llm.provider = "openai-compatible"
        config.llm.api_key = "test-key"
        client = create_llm_client(config.llm)
        assert isinstance(client, OpenAICompatClient)
        client.close()

    def test_unknown_provider_raises(self):
        from autonovelclaw.llm import create_llm_client
        config = NovelClawConfig()
        config.llm.provider = "unknown-provider"
        config.llm.api_key = "test-key"
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_llm_client(config.llm)

    def test_agent_role_enum(self):
        from autonovelclaw.llm.client import AgentRole
        assert AgentRole.WRITER == "writer"
        assert AgentRole.REVIEWER_1 == "reviewer_1"
        assert len(AgentRole) == 6

    def test_llm_response_dataclass(self):
        from autonovelclaw.llm.client import LLMResponse
        resp = LLMResponse(text="hello", model="test", input_tokens=10, output_tokens=5)
        assert resp.text == "hello"
        assert resp.input_tokens == 10


# ============================================================================
# Pipeline state machine tests (Phase 1 — additional)
# ============================================================================

class TestStateMachine:

    def test_all_stages_have_contracts(self):
        from autonovelclaw.pipeline.stages import Stage
        from autonovelclaw.pipeline.contracts import CONTRACTS
        for stage in Stage:
            assert stage in CONTRACTS, f"Missing contract for {stage.name}"

    def test_gate_stages_defined(self):
        from autonovelclaw.pipeline.stages import GATE_STAGES, Stage
        assert Stage.SELECTION_AND_SCOPE in GATE_STAGES
        assert Stage.WORLD_VALIDATION in GATE_STAGES
        assert Stage.OUTLINE_REVIEW in GATE_STAGES
        assert Stage.CHAPTER_APPROVAL in GATE_STAGES
        assert Stage.CHAPTER_DRAFT not in GATE_STAGES

    def test_transition_start(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.IDEA_INTAKE, StageStatus.PENDING, TransitionEvent.START)
        assert outcome.status == StageStatus.RUNNING

    def test_transition_succeed_non_gate(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.CODEX_GENERATION, StageStatus.RUNNING, TransitionEvent.SUCCEED)
        assert outcome.status == StageStatus.DONE
        assert outcome.next_stage is not None

    def test_transition_succeed_gate_blocks(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.WORLD_VALIDATION, StageStatus.RUNNING, TransitionEvent.SUCCEED)
        assert outcome.status == StageStatus.BLOCKED_APPROVAL

    def test_transition_approve_gate(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.WORLD_VALIDATION, StageStatus.BLOCKED_APPROVAL, TransitionEvent.APPROVE)
        assert outcome.status == StageStatus.DONE

    def test_transition_reject_rolls_back(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance, GATE_ROLLBACK
        outcome = advance(Stage.WORLD_VALIDATION, StageStatus.BLOCKED_APPROVAL, TransitionEvent.REJECT)
        assert outcome.status == StageStatus.PENDING
        assert outcome.rollback_stage == GATE_ROLLBACK[Stage.WORLD_VALIDATION]

    def test_transition_fail(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.CHAPTER_DRAFT, StageStatus.RUNNING, TransitionEvent.FAIL)
        assert outcome.status == StageStatus.FAILED

    def test_invalid_transition_raises(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        with pytest.raises(ValueError):
            advance(Stage.IDEA_INTAKE, StageStatus.DONE, TransitionEvent.START)

    def test_skip_transition(self):
        from autonovelclaw.pipeline.stages import Stage, StageStatus, TransitionEvent, advance
        outcome = advance(Stage.SERIES_ARC_DESIGN, StageStatus.PENDING, TransitionEvent.SKIP)
        assert outcome.status == StageStatus.SKIPPED

    def test_phase_map_covers_all_stages(self):
        from autonovelclaw.pipeline.stages import Stage, PHASE_MAP
        all_in_phases = set()
        for stages in PHASE_MAP.values():
            all_in_phases.update(stages)
        for stage in Stage:
            assert stage in all_in_phases, f"{stage.name} not in any phase"

    def test_chapter_loop_stages_correct(self):
        from autonovelclaw.pipeline.stages import (
            CHAPTER_LOOP_STAGES, Stage, CHAPTER_LOOP_START, CHAPTER_LOOP_END,
        )
        assert Stage.SCENE_PLANNING in CHAPTER_LOOP_STAGES
        assert Stage.CHAPTER_DRAFT in CHAPTER_LOOP_STAGES
        assert Stage.CHAPTER_APPROVAL in CHAPTER_LOOP_STAGES
        assert Stage.IDEA_INTAKE not in CHAPTER_LOOP_STAGES
        assert Stage.MANUSCRIPT_COMPILE not in CHAPTER_LOOP_STAGES


class TestCheckpoint:

    def test_checkpoint_create_and_save(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        ckpt = Checkpoint(tmp_path)
        ckpt.run_id = "test-run"
        ckpt.current_chapter = 5
        ckpt.store_artifact("key1", "value1")
        ckpt.save()

        # Reload
        ckpt2 = Checkpoint(tmp_path)
        assert ckpt2.run_id == "test-run"
        assert ckpt2.current_chapter == 5
        assert ckpt2.get_artifact("key1") == "value1"

    def test_checkpoint_stage_status(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        from autonovelclaw.pipeline.stages import StageStatus
        ckpt = Checkpoint(tmp_path)
        ckpt.set_stage_status("test_stage", StageStatus.DONE)
        assert ckpt.is_done("test_stage")
        assert not ckpt.is_done("other_stage")

    def test_checkpoint_decisions(self, tmp_path: Path):
        from autonovelclaw.pipeline.runner import Checkpoint
        ckpt = Checkpoint(tmp_path)
        ckpt.record_decision("stage_1", "proceed", "Rating 9.2")
        assert len(ckpt.decisions) == 1
        assert ckpt.decisions[0]["decision"] == "proceed"
