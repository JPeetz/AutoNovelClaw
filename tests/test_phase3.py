"""Tests for Phase 3 components: continuity, chapter, reviewers."""

from pathlib import Path
import pytest


# ============================================================================
# Continuity: Entity Tracker
# ============================================================================

class TestEntityTracker:

    def test_register_and_track(self):
        from autonovelclaw.continuity.tracker import EntityTracker
        tracker = EntityTracker()
        entity = tracker.register_entity("Kael", "character", aliases=["The Smith"])
        assert entity.name == "Kael"
        assert "The Smith" in entity.aliases

    def test_process_chapter_finds_mentions(self):
        from autonovelclaw.continuity.tracker import EntityTracker
        tracker = EntityTracker()
        tracker.register_entity("Marcus", "character")
        tracker.register_entity("Elena", "character")

        text = "Marcus stood on the dock. Elena called from the shore. Marcus turned."
        issues = tracker.process_chapter(1, text)
        assert tracker.entities["Marcus"].mention_count >= 2
        assert tracker.entities["Elena"].mention_count >= 1

    def test_character_gap_detection(self):
        from autonovelclaw.continuity.tracker import EntityTracker
        tracker = EntityTracker()
        tracker.register_entity("Rico", "character")

        # Rico appears in ch1, disappears, reappears in ch5
        tracker.process_chapter(1, "Rico laughed loudly.")
        tracker.process_chapter(2, "The wind blew.")
        tracker.process_chapter(3, "Nothing happened.")
        tracker.process_chapter(4, "Still nothing.")
        tracker.process_chapter(5, "Rico appeared again.")

        issues = tracker.check_consistency()
        gap_issues = [i for i in issues if i.issue_type == "character_gap"]
        assert len(gap_issues) >= 1

    def test_register_from_profiles(self):
        from autonovelclaw.continuity.tracker import EntityTracker
        tracker = EntityTracker()
        profiles = "## Nyxis\n\nA hunter.\n\n## Kael\n\nA blacksmith.\n\n## Physical Presence\n\nTall."
        count = tracker.register_characters_from_profiles(profiles)
        assert count >= 2
        assert "Nyxis" in tracker.entities
        assert "Kael" in tracker.entities

    def test_save_and_load(self, tmp_path: Path):
        from autonovelclaw.continuity.tracker import EntityTracker
        tracker = EntityTracker()
        tracker.register_entity("Test", "character", aliases=["Testy"])
        tracker.process_chapter(1, "Test walked down the road.")

        path = tmp_path / "entities.json"
        tracker.save(path)

        tracker2 = EntityTracker()
        tracker2.load(path)
        assert "Test" in tracker2.entities
        assert "Testy" in tracker2.entities["Test"].aliases


# ============================================================================
# Continuity: Timeline
# ============================================================================

class TestTimelineValidator:

    def test_detects_time_markers(self):
        from autonovelclaw.continuity.timeline import TimelineValidator
        tv = TimelineValidator()
        text = "The morning light filtered in. By dusk, they had arrived."
        issues = tv.process_chapter(1, text)
        assert len(tv.timepoints) >= 2

    def test_detects_elapsed_time(self):
        from autonovelclaw.continuity.timeline import TimelineValidator
        tv = TimelineValidator()
        text = "Three hours later, they reached the fortress."
        tv.process_chapter(1, text)
        relative = [tp for tp in tv.timepoints if tp.time_type == "relative"]
        assert len(relative) >= 1

    def test_time_reversal_warning(self):
        from autonovelclaw.continuity.timeline import TimelineValidator
        tv = TimelineValidator()
        # Evening then morning without a scene break
        text = "The evening air was thick with smoke.\n\nThe morning dew glistened on leaves."
        issues = tv.process_chapter(1, text)
        reversals = [i for i in issues if i.issue_type == "time_reversal"]
        assert len(reversals) >= 1


# ============================================================================
# Continuity: Foreshadowing
# ============================================================================

class TestForeshadowTracker:

    def test_register_and_resolve(self):
        from autonovelclaw.continuity.timeline import ForeshadowTracker
        ft = ForeshadowTracker()
        ft.register_seed("s1", "The cracked ring", 1)
        assert not ft.seeds["s1"].resolved
        ft.resolve_seed("s1", 8, "Ring revealed as key")
        assert ft.seeds["s1"].resolved
        assert ft.seeds["s1"].resolved_chapter == 8

    def test_unresolved_seeds_flagged(self):
        from autonovelclaw.continuity.timeline import ForeshadowTracker
        ft = ForeshadowTracker()
        ft.register_seed("s1", "Mysterious light in the cave", 2)
        ft.register_seed("s2", "The old woman's warning", 3)
        ft.resolve_seed("s2", 7, "Warning fulfilled")

        issues = ft.check_resolution(total_chapters=10)
        unresolved = [i for i in issues if i.issue_type == "unresolved"]
        assert len(unresolved) == 1
        assert "Mysterious light" in unresolved[0].description

    def test_extract_from_outline(self):
        from autonovelclaw.continuity.timeline import ForeshadowTracker
        ft = ForeshadowTracker()
        outline = """
        ## Chapter 1: The Beginning
        - Foreshadow the betrayal later
        - Plant seeds for the magic reveal

        ## Chapter 3: The Journey
        - Hint at the villain's true identity
        """
        count = ft.extract_seeds_from_outline(outline)
        assert count >= 2


# ============================================================================
# Continuity: Full Verification
# ============================================================================

class TestFullVerification:

    def test_verify_clean_manuscript(self):
        from autonovelclaw.continuity.verify import verify_manuscript
        chapters = {
            1: "Marcus walked through the morning mist. The salt air stung his face.",
            2: "By afternoon, Marcus reached the dock. Elena waited.",
        }
        report = verify_manuscript(chapters)
        assert report.chapters_checked == 2
        assert isinstance(report.to_markdown(), str)

    def test_verify_with_profiles(self):
        from autonovelclaw.continuity.verify import verify_manuscript
        chapters = {1: "Marcus looked at Elena. She nodded."}
        profiles = "## Marcus\n\nA pilot.\n\n## Elena\n\nA scientist."
        report = verify_manuscript(chapters, character_profiles=profiles)
        assert report.entities_tracked >= 2


# ============================================================================
# Chapter: Context Assembly
# ============================================================================

class TestChapterContext:

    def test_assemble_basic_context(self):
        from autonovelclaw.chapter.context import assemble_writer_context
        ctx = assemble_writer_context(
            codex="The world is ancient and broken.",
            characters="Marcus is a pilot. Elena is a scientist.",
            scene_plan="Scene 1: Marcus arrives at the dock.",
        )
        assert ctx.codex_excerpt != ""
        assert ctx.characters_excerpt != ""
        assert ctx.scene_plan != ""
        assert ctx.total_estimated_tokens > 0

    def test_extract_relevant_codex_prioritises(self):
        from autonovelclaw.chapter.context import extract_relevant_codex
        codex = (
            "## Geography\nThe island chain stretches across the warm sea.\n\n"
            "## History\nAncient wars shaped the land.\n\n"
            "## Economy\nFishing and trade sustain the villages.\n\n"
            "## Religion\nThe old gods are remembered in song."
        )
        result = extract_relevant_codex(codex, location_hint="island", max_tokens=100)
        assert "island" in result.lower() or "Geography" in result

    def test_rolling_context_for_first_chapter(self):
        from autonovelclaw.chapter.context import build_rolling_context
        result = build_rolling_context({}, current_chapter=1)
        assert "first chapter" in result.lower()

    def test_rolling_context_includes_previous(self):
        from autonovelclaw.chapter.context import build_rolling_context
        summaries = {
            1: "Marcus discovered the pyramid.",
            2: "Elena was rescued from the fold.",
        }
        result = build_rolling_context(summaries, current_chapter=3)
        assert "Chapter 2" in result
        assert "Elena" in result or "rescued" in result


# ============================================================================
# Chapter: Sensory Auditor
# ============================================================================

class TestSensoryAuditor:

    def test_audit_detects_senses(self):
        from autonovelclaw.chapter.sensory_auditor import audit_chapter_sensory
        text = (
            "The bright morning light gleamed off the water. "
            "Salt air carried the smell of seaweed and diesel. "
            "The rough wood of the dock felt warm beneath his bare feet. "
            "Gulls screamed overhead. " * 5
        )
        report = audit_chapter_sensory(text)
        assert report.sense_totals["visual"] > 0
        assert report.sense_totals["olfactory"] > 0
        assert report.sense_totals["kinesthetic"] > 0
        assert report.sense_totals["auditory"] > 0

    def test_audit_detects_sensory_deserts(self):
        from autonovelclaw.chapter.sensory_auditor import audit_chapter_sensory
        text = (
            "He walked to the store and bought some things. "
            "Then he went home and thought about the situation. "
            "It was a normal day with nothing special happening at all. "
        ) * 10
        report = audit_chapter_sensory(text)
        assert report.sensory_deserts > 0

    def test_audit_gap_analysis(self):
        from autonovelclaw.chapter.sensory_auditor import audit_chapter_sensory
        # Heavily visual, no olfactory
        text = (
            "The bright light illuminated the gleaming silver surface. "
            "Shadows danced across the vivid walls. Colors shimmered. " * 10
        )
        report = audit_chapter_sensory(text)
        gaps = report.gap_analysis()
        assert gaps["visual"] > 0  # above target
        # olfactory should be below target
        assert gaps["olfactory"] < 0

    def test_report_to_markdown(self):
        from autonovelclaw.chapter.sensory_auditor import audit_chapter_sensory
        text = "The morning light was warm. The air smelled of salt. " * 10
        report = audit_chapter_sensory(text)
        md = report.to_markdown()
        assert "Sensory Audit" in md
        assert "visual" in md


# ============================================================================
# Chapter: Structure Validator
# ============================================================================

class TestChapterValidator:

    def test_validates_good_chapter(self):
        from autonovelclaw.chapter.validator import validate_chapter_structure
        text = (
            'The morning light filtered through gaps in the corrugated roof, '
            'each beam catching particles of dust that swirled like ghosts. '
            'The salt air carried diesel fumes and the green-rot scent of seaweed.\n\n'
            '"We need to leave," Marcus said, his voice tight.\n\n'
            'Elena nodded. "The tide won\'t wait."\n\n'
            '* * *\n\n'
            'Three hours later, they stood on the deck of the Deep Blue. '
            'The horizon stretched endless and blue ahead of them.\n\n'
            '"What happens next?" Elena asked.\n\n'
            'Marcus had no answer. But he knew they couldn\'t stop now.\n\n'
        ) * 6  # Repeat to meet word count
        report = validate_chapter_structure(text, min_words=500, max_words=10000)
        assert report.has_sensory_opening
        assert report.scene_count >= 2

    def test_flags_missing_sensory_opening(self):
        from autonovelclaw.chapter.validator import validate_chapter_structure
        text = "# Chapter 1\n\nHe did stuff. Things happened. More things.\n\n" * 30
        report = validate_chapter_structure(text, min_words=50)
        sensory_issues = [i for i in report.issues if "sensory" in i.issue_type.lower()]
        assert len(sensory_issues) >= 1

    def test_flags_short_word_count(self):
        from autonovelclaw.chapter.validator import validate_chapter_structure
        text = "Short chapter. " * 50
        report = validate_chapter_structure(text, min_words=5000)
        assert any("word count" in i.description.lower() for i in report.issues)


# ============================================================================
# Reviewers: Parser
# ============================================================================

class TestReviewParser:

    def test_parse_critic_review(self):
        from autonovelclaw.reviewers.parser import parse_critic_review
        review = """
        ## OVERALL RATING: 8.5/10

        ## WHAT WORKS
        1. The sensory immersion in the opening paragraph is exceptional
        2. Dialogue feels natural and distinctive per character
        3. Pacing builds tension effectively

        ## WHAT DOESN'T WORK
        1. The middle section drags with repetitive description
        2. Supporting character Rico feels underdeveloped
        3. One info-dump disguised as dialogue in paragraph 12

        ## SPECIFIC SUGGESTIONS
        1. Cut 20% of the grey landscape descriptions in paragraphs 8-10
        2. Give Rico a distinctive physical mannerism
        3. Convert the exposition in paragraph 12 to action

        ## PATH TO IMPROVEMENT
        With these changes, this chapter could reach 9.0/10
        """
        parsed = parse_critic_review(review)
        assert parsed.rating == 8.5
        assert len(parsed.strengths) >= 2
        assert len(parsed.weaknesses) >= 2
        assert len(parsed.suggestions) >= 2
        assert parsed.parse_confidence > 0.5

    def test_parse_reader_review(self):
        from autonovelclaw.reviewers.parser import parse_reader_review
        review = """
        ## ENGAGEMENT RATING: 8.0/10

        ## PAGE-TURNER MOMENTS
        - The confrontation scene had me reading faster
        - The reveal at the end was genuinely surprising

        ## DRAG POINTS
        - The travel sequence felt too long
        - Technical explanation in the middle lost me

        ## CONFUSION POINTS
        - I wasn't sure who was speaking in the group scene

        ## EMOTIONAL PEAKS
        - The reunion scene genuinely moved me

        ## CHARACTER INVESTMENT
        I care about Marcus. Elena is interesting but distant.

        ## MEMORABILITY
        The image of dust catching in beams of light will stay with me.

        ## SUGGESTIONS
        - Tighten the travel sequence
        - Add dialogue tags in the group scene
        """
        parsed = parse_reader_review(review)
        assert parsed.rating == 8.0
        assert len(parsed.drag_points) >= 1
        assert len(parsed.confusion_points) >= 1
        assert parsed.memorability != ""

    def test_extract_rating_fallback(self):
        from autonovelclaw.reviewers.parser import extract_rating
        rating, source = extract_rating("No rating here at all")
        assert rating == 7.0
        assert source == "default"

    def test_combine_reviews(self):
        from autonovelclaw.reviewers.parser import parse_critic_review, parse_reader_review, combine_reviews
        critic = parse_critic_review("OVERALL RATING: 8.0/10\n\n## WHAT WORKS\n1. Good prose")
        reader = parse_reader_review("ENGAGEMENT RATING: 9.0/10\n\n## PAGE-TURNER MOMENTS\n- Great hook")
        combined = combine_reviews(critic, reader, critic_weight=0.6, reader_weight=0.4)
        assert combined["composite_rating"] == 8.4  # 8.0*0.6 + 9.0*0.4


# ============================================================================
# Reviewers: Enhancement Planner
# ============================================================================

class TestEnhancementPlanner:

    def test_plan_enhancement(self):
        from autonovelclaw.reviewers.parser import parse_critic_review, parse_reader_review
        from autonovelclaw.reviewers.planner import plan_enhancement

        critic = parse_critic_review(
            "OVERALL RATING: 7.5/10\n\n"
            "## WHAT DOESN'T WORK\n"
            "1. Sensory immersion is thin in paragraphs 5-8\n"
            "2. Dialogue feels generic in the confrontation\n\n"
            "## SPECIFIC SUGGESTIONS\n"
            "1. Add olfactory detail to the dock scene\n"
            "2. Give each character a distinctive speech pattern\n"
        )
        reader = parse_reader_review(
            "ENGAGEMENT RATING: 7.0/10\n\n"
            "## DRAG POINTS\n"
            "- The description of the landscape went on too long\n\n"
            "## CONFUSION POINTS\n"
            "- Couldn't tell who was speaking in the argument\n\n"
            "## SUGGESTIONS\n"
            "- Add dialogue tags in the argument scene\n"
        )

        plan = plan_enhancement(critic, reader, loop_index=0)
        assert len(plan.changes) >= 3
        assert plan.phase_name == "Phase 1"
        assert plan.strengths_to_preserve is not None

    def test_plan_to_prompt_instructions(self):
        from autonovelclaw.reviewers.parser import parse_critic_review
        from autonovelclaw.reviewers.planner import plan_enhancement
        critic = parse_critic_review(
            "OVERALL RATING: 8.0/10\n\n"
            "## SPECIFIC SUGGESTIONS\n1. Fix the pacing in scene 2\n"
        )
        plan = plan_enhancement(critic, loop_index=1)
        instructions = plan.to_prompt_instructions()
        assert "Phase 1.5" in instructions
        assert "PRESERVE" in instructions or "CHANGES" in instructions


# ============================================================================
# Reviewers: Convergence
# ============================================================================

class TestConvergence:

    def test_convergence_tracking(self):
        from autonovelclaw.reviewers.planner import ConvergenceAnalysis
        ca = ConvergenceAnalysis(target_rating=9.0, diminishing_threshold=0.2)

        ca.add_point(7.5, 7.0, 7.3, word_count=6000)
        ca.add_point(8.0, 7.5, 7.8, word_count=6200, prev_word_count=6000)
        ca.add_point(8.5, 8.0, 8.3, word_count=6350, prev_word_count=6200)

        assert ca.current_composite == 8.3
        assert ca.total_improvement > 0
        assert not ca.is_converged  # Below 9.0

    def test_convergence_target_reached(self):
        from autonovelclaw.reviewers.planner import ConvergenceAnalysis
        ca = ConvergenceAnalysis(target_rating=9.0)
        ca.add_point(8.5, 8.0, 8.3)
        ca.add_point(9.2, 9.0, 9.1)
        assert ca.is_converged
        assert "target reached" in ca.convergence_reason

    def test_convergence_diminishing_returns(self):
        from autonovelclaw.reviewers.planner import ConvergenceAnalysis
        ca = ConvergenceAnalysis(target_rating=9.0, diminishing_threshold=0.2)
        ca.add_point(8.0, 7.5, 7.8)
        ca.add_point(8.1, 7.6, 7.9)  # Only +0.1 improvement
        assert ca.is_converged
        assert "diminishing" in ca.convergence_reason

    def test_convergence_to_markdown(self):
        from autonovelclaw.reviewers.planner import ConvergenceAnalysis
        ca = ConvergenceAnalysis(target_rating=9.0)
        ca.add_point(7.5, 7.0, 7.3)
        ca.add_point(8.5, 8.0, 8.3)
        md = ca.to_markdown()
        assert "Convergence" in md
        assert "7.3" in md
        assert "8.3" in md


# ============================================================================
# Publishing: EPUB Builder
# ============================================================================

class TestEpubBuilder:

    def test_build_epub(self, tmp_path: Path):
        try:
            from autonovelclaw.publishing.epub_builder import build_epub
        except ImportError:
            pytest.skip("ebooklib not installed")

        chapters = {
            1: "# Chapter 1: The Beginning\n\nMarcus walked through the fog.\n\n* * *\n\nElena waited.",
            2: "# Chapter 2: The Journey\n\nThey sailed at dawn.\n\nThe horizon stretched ahead.",
        }
        out = tmp_path / "test.epub"
        result = build_epub(
            title="Test Novel",
            author="Test Author",
            chapters=chapters,
            output_path=out,
        )
        assert result.exists()
        assert result.stat().st_size > 1000  # Should be a real EPUB

    def test_md_to_html_conversion(self):
        from autonovelclaw.publishing.epub_builder import _md_to_html
        html = _md_to_html("# Chapter 1\n\nFirst paragraph.\n\nSecond paragraph.\n\n* * *\n\nAfter break.")
        assert "<h1>" in html
        assert "First paragraph" in html
        assert "scene-break" in html
        assert "After break" in html

    def test_inline_formatting(self):
        from autonovelclaw.publishing.epub_builder import _inline_format
        assert "<strong>" in _inline_format("**bold**")
        assert "<em>" in _inline_format("*italic*")
        assert "—" in _inline_format("---")


# ============================================================================
# Publishing: PDF Builder
# ============================================================================

class TestPdfBuilder:

    def test_build_pdf(self, tmp_path: Path):
        try:
            from autonovelclaw.publishing.pdf_builder import build_pdf
        except ImportError:
            pytest.skip("reportlab not installed")

        chapters = {
            1: "# Chapter 1\n\nMarcus walked.\n\nThe fog was thick.",
            2: "# Chapter 2\n\nElena sailed.\n\nThe wind blew.",
        }
        out = tmp_path / "test.pdf"
        result = build_pdf(
            title="Test Novel",
            author="Test Author",
            chapters=chapters,
            output_path=out,
            trim_size="6x9",
        )
        assert result.exists()
        # Check PDF magic bytes
        with open(result, "rb") as f:
            assert f.read(5) == b"%PDF-"

    def test_gutter_margins(self):
        from autonovelclaw.publishing.pdf_builder import _gutter_for_pages
        assert _gutter_for_pages(100) == 0.375
        assert _gutter_for_pages(200) == 0.75
        assert _gutter_for_pages(500) == 0.875
        assert _gutter_for_pages(700) == 1.0

    def test_trim_sizes_defined(self):
        from autonovelclaw.publishing.pdf_builder import TRIM_SIZES
        assert "6x9" in TRIM_SIZES
        assert "5x8" in TRIM_SIZES
        assert TRIM_SIZES["6x9"] == (6.0, 9.0)


# ============================================================================
# Publishing: KDP Validator
# ============================================================================

class TestKDPValidator:

    def test_validate_epub_missing(self, tmp_path: Path):
        from autonovelclaw.publishing.validator import validate_epub
        issues = validate_epub(tmp_path / "nonexistent.epub")
        assert len(issues) == 1
        assert issues[0].severity == "error"

    def test_validate_epub_exists(self, tmp_path: Path):
        from autonovelclaw.publishing.validator import validate_epub
        # Create a valid zip/epub-like file with enough content
        import zipfile
        epub_path = tmp_path / "test.epub"
        with zipfile.ZipFile(epub_path, "w") as zf:
            zf.writestr("mimetype", "application/epub+zip")
            zf.writestr("content.opf", "<package>" + "x" * 10000 + "</package>")
            zf.writestr("chapter1.xhtml", "<html><body>" + "word " * 5000 + "</body></html>")
        issues = validate_epub(epub_path)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_validate_metadata_complete(self):
        from autonovelclaw.publishing.validator import validate_metadata
        metadata = {"title": "Test", "author": "Author", "genre": "Fantasy",
                    "word_count": 80000, "chapter_count": 25}
        issues = validate_metadata(metadata)
        errors = [i for i in issues if i.severity == "error"]
        assert len(errors) == 0

    def test_validate_metadata_missing_title(self):
        from autonovelclaw.publishing.validator import validate_metadata
        issues = validate_metadata({"author": "Test"})
        assert any("title" in i.description for i in issues)

    def test_validate_all_missing_everything(self, tmp_path: Path):
        from autonovelclaw.publishing.validator import validate_all
        report = validate_all()
        # No files provided — should just have cover warning
        assert len(report.issues) >= 1

    def test_report_to_markdown(self):
        from autonovelclaw.publishing.validator import KDPValidationReport, ValidationIssue
        report = KDPValidationReport(issues=[
            ValidationIssue("epub", "error", "File missing"),
            ValidationIssue("cover", "warning", "Too small"),
        ])
        md = report.to_markdown()
        assert "NOT READY" in md
        assert "File missing" in md
