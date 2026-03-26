"""Tests for configuration loading and validation."""

from pathlib import Path
import pytest
import yaml

from autonovelclaw.config import (
    NovelClawConfig,
    load_config,
    ProjectMode,
    NovelScope,
    TrimSize,
)


class TestConfigDefaults:
    """Ensure all defaults are sensible."""

    def test_default_config_creates(self):
        config = NovelClawConfig()
        assert config.project_name == "my-novel"
        assert config.mode == ProjectMode.SEMI_AUTO

    def test_sensory_targets_sum_to_one(self):
        config = NovelClawConfig()
        s = config.writing.sensory_targets
        total = s.visual + s.kinesthetic + s.olfactory + s.auditory + s.gustatory
        assert abs(total - 1.0) < 0.01

    def test_review_thresholds_ordered(self):
        config = NovelClawConfig()
        assert config.review.min_rating_refine < config.review.min_rating_proceed

    def test_critic_reader_weights_sum_to_one(self):
        config = NovelClawConfig()
        total = config.review.critic_weight + config.review.reader_weight
        assert abs(total - 1.0) < 0.01

    def test_default_models_set(self):
        config = NovelClawConfig()
        assert config.llm.models.writer != ""
        assert config.llm.models.reviewer_1 != ""
        assert config.llm.models.editor != ""

    def test_temperature_ranges(self):
        config = NovelClawConfig()
        assert 0 < config.llm.temperature.writer <= 1.0
        assert 0 < config.llm.temperature.reviewer <= 1.0
        assert 0 <= config.llm.temperature.editor <= 1.0
        assert 0 < config.llm.temperature.ideation <= 1.0

    def test_knowledge_base_categories(self):
        config = NovelClawConfig()
        assert "world_codex" in config.knowledge_base.categories
        assert "approved_chapters" in config.knowledge_base.categories
        assert "reviews" in config.knowledge_base.categories
        assert "lessons_learned" in config.knowledge_base.categories

    def test_default_chapter_targets(self):
        config = NovelClawConfig()
        t = config.novel.target
        assert t.words_per_chapter_min > 0
        assert t.words_per_chapter_max > t.words_per_chapter_min
        assert t.chapter_count_min > 0
        assert t.chapter_count_max >= t.chapter_count_min


class TestConfigLoading:
    """Test loading from YAML."""

    def test_load_from_dict(self):
        config = NovelClawConfig(
            project_name="test-novel",
            mode="full-auto",
        )
        assert config.project_name == "test-novel"
        assert config.mode == ProjectMode.FULL_AUTO

    def test_load_nonexistent_returns_defaults(self):
        config = load_config("/nonexistent/path.yaml")
        assert config.project_name == "my-novel"

    def test_load_from_yaml_file(self, tmp_path: Path):
        yaml_content = {
            "project_name": "yaml-test",
            "mode": "supervised",
            "novel": {"title": "Test Novel", "author": "Test Author"},
        }
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))

        config = load_config(config_file)
        assert config.project_name == "yaml-test"
        assert config.mode == ProjectMode.SUPERVISED
        assert config.novel.title == "Test Novel"
        assert config.novel.author == "Test Author"

    def test_partial_yaml_uses_defaults(self, tmp_path: Path):
        yaml_content = {"project_name": "partial"}
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump(yaml_content))

        config = load_config(config_file)
        assert config.project_name == "partial"
        assert config.writing.sensory_targets.visual == 0.40  # default preserved

    def test_enum_validation(self):
        config = NovelClawConfig(mode="full-auto")
        assert config.mode == ProjectMode.FULL_AUTO

        with pytest.raises(ValueError):
            NovelClawConfig(mode="invalid-mode")


class TestConfigSensoryTargets:
    """Sensory target validation."""

    def test_clamp_to_range(self):
        config = NovelClawConfig()
        config.writing.sensory_targets.visual = 1.5  # should be clamped
        # Pydantic validators run on creation, not mutation.
        # Test via construction:
        from autonovelclaw.config import SensoryTargets
        s = SensoryTargets(visual=1.5)
        assert s.visual == 1.0

        s2 = SensoryTargets(visual=-0.5)
        assert s2.visual == 0.0


class TestConfigAPIKey:
    """API key resolution."""

    def test_api_key_from_config(self):
        config = NovelClawConfig()
        config.llm.api_key = "direct-key"
        assert config.llm.resolve_api_key() == "direct-key"

    def test_api_key_missing_raises(self):
        config = NovelClawConfig()
        config.llm.api_key = ""
        config.llm.api_key_env = "NONEXISTENT_KEY_VAR_FOR_TESTING"
        with pytest.raises(ValueError, match="No API key"):
            config.llm.resolve_api_key()
