"""Tests for the knowledge base."""

from pathlib import Path
import pytest

from autonovelclaw.knowledge_base import KnowledgeBase


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    return KnowledgeBase(root=tmp_path / "kb", categories=["world_codex", "characters", "reviews"])


class TestKnowledgeBaseStore:

    def test_store_and_retrieve(self, kb: KnowledgeBase):
        kb.store("world_codex", "codex", "The world is ancient.")
        result = kb.retrieve("world_codex", "codex")
        assert result == "The world is ancient."

    def test_store_with_metadata(self, kb: KnowledgeBase):
        kb.store("characters", "hero", "Brave knight.", meta={"type": "protagonist"})
        result = kb.retrieve("characters", "hero")
        assert result == "Brave knight."

    def test_retrieve_nonexistent_returns_none(self, kb: KnowledgeBase):
        assert kb.retrieve("world_codex", "nonexistent") is None

    def test_store_creates_category_dir(self, kb: KnowledgeBase):
        kb.store("new_category", "doc", "content")
        assert (kb.root / "new_category").exists()


class TestKnowledgeBaseList:

    def test_list_documents(self, kb: KnowledgeBase):
        kb.store("characters", "alice", "Alice is brave.")
        kb.store("characters", "bob", "Bob is clever.")
        docs = kb.list_documents("characters")
        assert "alice" in docs
        assert "bob" in docs

    def test_list_empty_category(self, kb: KnowledgeBase):
        assert kb.list_documents("reviews") == []


class TestKnowledgeBaseRetrieveAll:

    def test_retrieve_all(self, kb: KnowledgeBase):
        kb.store("characters", "alice", "Alice content.")
        kb.store("characters", "bob", "Bob content.")
        all_docs = kb.retrieve_all("characters")
        assert len(all_docs) == 2
        assert "Alice content." in all_docs.values()


class TestKnowledgeBaseDelete:

    def test_delete_existing(self, kb: KnowledgeBase):
        kb.store("reviews", "review1", "Great chapter.")
        assert kb.delete("reviews", "review1") is True
        assert kb.retrieve("reviews", "review1") is None

    def test_delete_nonexistent(self, kb: KnowledgeBase):
        assert kb.delete("reviews", "nonexistent") is False


class TestKnowledgeBaseConvenience:

    def test_get_world_codex(self, kb: KnowledgeBase):
        kb.store("world_codex", "codex", "Ancient lands.")
        assert kb.get_world_codex() == "Ancient lands."

    def test_get_world_codex_empty(self, kb: KnowledgeBase):
        assert kb.get_world_codex() == ""

    def test_store_and_get_chapter_summary(self, kb: KnowledgeBase):
        kb2 = KnowledgeBase(root=kb.root, categories=["chapter_summaries"])
        kb2.store("chapter_summaries", "chapter_01", "The hero begins.")
        assert kb2.get_chapter_summary(1) == "The hero begins."

    def test_store_lesson(self, kb: KnowledgeBase):
        kb2 = KnowledgeBase(root=kb.root, categories=["lessons_learned"])
        path = kb2.store_lesson("convergence", "Chapter 3 converged at 9.2")
        assert path.exists()
        assert "convergence" in path.name
