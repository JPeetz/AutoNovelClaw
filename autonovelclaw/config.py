"""Configuration system for AutoNovelClaw.

All settings are defined as Pydantic models for validation, defaults, and
type safety.  Configuration is loaded from YAML and environment variables.
"""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ProjectMode(str, Enum):
    FULL_AUTO = "full-auto"
    SEMI_AUTO = "semi-auto"
    SUPERVISED = "supervised"


class NovelScope(str, Enum):
    STANDALONE = "standalone"
    SERIES = "series"


class PaperColor(str, Enum):
    WHITE = "white"
    CREAM = "cream"


class TrimSize(str, Enum):
    SIZE_5X8 = "5x8"
    SIZE_525X8 = "5.25x8"
    SIZE_55X85 = "5.5x8.5"
    SIZE_6X9 = "6x9"


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------

class IdeationConfig(BaseModel):
    storyline_count: int = Field(default=10, ge=1, le=10)
    clarifying_questions: bool = True
    diversity_enforcement: bool = True


class GenreConfig(BaseModel):
    primary: str = ""
    subgenres: list[str] = Field(default_factory=list)


class SeriesConfig(BaseModel):
    name: str = ""
    book_number: int = 1
    total_books: int = 1


class TargetConfig(BaseModel):
    word_count_min: int = 55_000
    word_count_max: int = 85_000
    chapter_count_min: int = 8
    chapter_count_max: int = 12
    words_per_chapter_min: int = 5_500
    words_per_chapter_max: int = 8_800


class NovelConfig(BaseModel):
    title: str = ""
    subtitle: str = ""
    author: str = ""
    genre: GenreConfig = Field(default_factory=GenreConfig)
    scope: NovelScope = NovelScope.STANDALONE
    series: SeriesConfig = Field(default_factory=SeriesConfig)
    target: TargetConfig = Field(default_factory=TargetConfig)


class SensoryTargets(BaseModel):
    visual: float = 0.40
    kinesthetic: float = 0.25
    olfactory: float = 0.20
    auditory: float = 0.10
    gustatory: float = 0.05

    @field_validator("visual", "kinesthetic", "olfactory", "auditory", "gustatory")
    @classmethod
    def _clamp(cls, v: float) -> float:
        return max(0.0, min(1.0, v))


class VoiceConfig(BaseModel):
    sentence_variation: str = "high"
    raw_edges: bool = True
    poetic_unpredictability: bool = True
    cliche_policy: str = "subvert-or-avoid"


class WritingConfig(BaseModel):
    style_profile: str = "echoes-of-the-abyss"
    sensory_targets: SensoryTargets = Field(default_factory=SensoryTargets)
    genre_overlay: str = "auto"
    pov: str = "third-person-limited"
    tense: str = "past"
    voice: VoiceConfig = Field(default_factory=VoiceConfig)


class ReviewConfig(BaseModel):
    reviewer_count: int = 2
    min_rating_proceed: float = 9.0
    min_rating_refine: float = 7.5
    max_enhancement_loops: int = 3
    max_rewrite_attempts: int = 2
    critic_weight: float = 0.6
    reader_weight: float = 0.4
    debate_critics: list[str] = Field(
        default_factory=lambda: [
            "pacing_critic",
            "character_critic",
            "prose_critic",
            "continuity_critic",
        ]
    )
    diminishing_returns_threshold: float = 0.2


class KindleConfig(BaseModel):
    cover_dimensions: str = "2560x1600"


class PaperbackConfig(BaseModel):
    trim_size: TrimSize = TrimSize.SIZE_6X9
    paper_color: PaperColor = PaperColor.CREAM
    font: str = "Palatino"
    font_size: int = 11


class PublishingConfig(BaseModel):
    formats: list[str] = Field(default_factory=lambda: ["kindle_epub", "kdp_paperback"])
    kindle: KindleConfig = Field(default_factory=KindleConfig)
    paperback: PaperbackConfig = Field(default_factory=PaperbackConfig)


class ModelConfig(BaseModel):
    writer: str = "claude-sonnet-4-20250514"
    reviewer_1: str = "claude-sonnet-4-20250514"
    reviewer_2: str = "claude-sonnet-4-20250514"
    editor: str = "claude-sonnet-4-20250514"
    ideation: str = "claude-sonnet-4-20250514"


class TemperatureConfig(BaseModel):
    writer: float = 0.85
    reviewer: float = 0.3
    editor: float = 0.1
    ideation: float = 0.95


class ClaudeCLIConfig(BaseModel):
    """Configuration for the Claude CLI (subscription) provider."""
    command: str = "claude"
    model: str = "sonnet"   # "sonnet", "opus", "haiku"
    timeout_sec: int = 600  # 10 min default — large stages need time


class LLMConfig(BaseModel):
    provider: str = "claude-cli"  # "claude-cli" (subscription), "anthropic" (API), "openai-compatible"
    base_url: str = "https://api.anthropic.com/v1"
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_key: str = ""
    models: ModelConfig = Field(default_factory=ModelConfig)
    temperature: TemperatureConfig = Field(default_factory=TemperatureConfig)
    fallback_models: list[str] = Field(default_factory=lambda: ["gpt-4o"])
    max_tokens: int = 8192
    claude_cli: ClaudeCLIConfig = Field(default_factory=ClaudeCLIConfig)

    def resolve_api_key(self) -> str:
        """Resolve API key. Not required for claude-cli provider."""
        if self.provider.lower().replace("-", "_") in ("claude_cli", "cli", "claude_code", "subscription"):
            return ""  # CLI uses subscription, no key needed
        if self.api_key:
            return self.api_key
        key = os.environ.get(self.api_key_env, "")
        if not key:
            raise ValueError(
                f"No API key: set '{self.api_key_env}' env var or 'llm.api_key' in config"
            )
        return key


class KnowledgeBaseConfig(BaseModel):
    backend: str = "markdown"
    root: str = "novel_kb/"
    categories: list[str] = Field(
        default_factory=lambda: [
            "world_codex",
            "characters",
            "approved_chapters",
            "chapter_summaries",
            "style_guide",
            "reviews",
            "lessons_learned",
        ]
    )


class SelfLearningConfig(BaseModel):
    enabled: bool = True
    time_decay_days: int = 90
    track: list[str] = Field(
        default_factory=lambda: [
            "technique_effectiveness",
            "reviewer_patterns",
            "voice_drift",
            "pacing_calibration",
            "sensory_balance",
        ]
    )


class SentinelConfig(BaseModel):
    enabled: bool = True
    checks: list[str] = Field(
        default_factory=lambda: [
            "character_name_consistency",
            "world_rule_adherence",
            "timeline_integrity",
            "magic_system_rules",
            "foreshadowing_tracking",
            "dead_end_detection",
            "voice_drift_detection",
            "cliche_detection",
            "sensory_distribution_audit",
        ]
    )


class InputsConfig(BaseModel):
    world_codex: str = ""
    character_profiles: str = ""
    series_outline: str = ""
    cover_image: str = ""
    existing_chapters: str = ""
    style_reference: str = ""


class RuntimeConfig(BaseModel):
    timezone: str = "UTC"
    max_parallel_tasks: int = 1
    approval_timeout_hours: int = 48
    output_dir: str = "artifacts/"


class OpenClawBridgeConfig(BaseModel):
    use_cron: bool = False
    use_message: bool = True
    use_memory: bool = True
    use_sessions_spawn: bool = False
    use_web_fetch: bool = True
    use_browser: bool = False


# ---------------------------------------------------------------------------
# Top-level config
# ---------------------------------------------------------------------------

class NovelClawConfig(BaseModel):
    """Root configuration for AutoNovelClaw."""

    project_name: str = "my-novel"
    mode: ProjectMode = ProjectMode.SEMI_AUTO

    ideation: IdeationConfig = Field(default_factory=IdeationConfig)
    novel: NovelConfig = Field(default_factory=NovelConfig)
    writing: WritingConfig = Field(default_factory=WritingConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)
    publishing: PublishingConfig = Field(default_factory=PublishingConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    self_learning: SelfLearningConfig = Field(default_factory=SelfLearningConfig)
    sentinel: SentinelConfig = Field(default_factory=SentinelConfig)
    inputs: InputsConfig = Field(default_factory=InputsConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    openclaw_bridge: OpenClawBridgeConfig = Field(default_factory=OpenClawBridgeConfig)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def load_config(path: str | Path | None = None) -> NovelClawConfig:
    """Load configuration from a YAML file, falling back to defaults."""
    if path is None:
        for candidate in ("config.novelclaw.yaml", "config.yaml"):
            if Path(candidate).exists():
                path = candidate
                break
    if path and Path(path).exists():
        with open(path) as f:
            raw: dict[str, Any] = yaml.safe_load(f) or {}
        return NovelClawConfig(**raw)
    return NovelClawConfig()
