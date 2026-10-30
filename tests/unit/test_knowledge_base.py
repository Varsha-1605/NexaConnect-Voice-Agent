import asyncio

import pytest

from services import knowledge_base


class FakeStore:
    def __init__(self, delay=0.0, fail=False):
        self.delay, self.fail = delay, fail

    async def asimilarity_search_by_vector(self, vector, k):
        await asyncio.sleep(self.delay)
        if self.fail:
            raise ConnectionError("pinecone is down")

        class Doc:
            metadata = {"source": "F&Q Internet Plan.md"}
            page_content = "Q: Is there a contract?\nA: month-to-month"

        return [Doc()]


@pytest.fixture
def kb(monkeypatch):
    async def fake_embed(query):
        return [0.0]

    monkeypatch.setattr(knowledge_base, "_embed_query", fake_embed)

    def use(store, timeout=4.0):
        monkeypatch.setattr(knowledge_base, "vector_store", lambda: store)
        monkeypatch.setattr(knowledge_base, "SEARCH_TIMEOUT", timeout)

    return use


async def test_results_have_source_and_content(kb):
    kb(FakeStore())
    results = await knowledge_base.search_or_unavailable("is there a contract")
    assert results == [{"source": "F&Q Internet Plan.md", "content": "Q: Is there a contract?\nA: month-to-month"}]


async def test_slow_search_says_not_available(kb):
    kb(FakeStore(delay=1.0), timeout=0.05)
    assert await knowledge_base.search_or_unavailable("price") == knowledge_base.UNAVAILABLE


async def test_failed_search_says_not_available(kb):
    kb(FakeStore(fail=True))
    assert await knowledge_base.search_or_unavailable("price") == knowledge_base.UNAVAILABLE


async def test_unavailable_message_tells_the_agent_not_to_guess():
    assert "Do not answer from memory" in knowledge_base.UNAVAILABLE


async def test_failure_is_logged_with_an_event_name(kb, caplog):
    kb(FakeStore(fail=True))
    await knowledge_base.search_or_unavailable("price")
    assert any(getattr(r, "event", None) == "kb_unavailable" for r in caplog.records)


async def test_no_results_is_a_plain_message(kb, monkeypatch):
    class Empty(FakeStore):
        async def asimilarity_search_by_vector(self, vector, k):
            return []

    kb(Empty())
    assert await knowledge_base.search_or_unavailable("zzz") == "No relevant information found."


def test_namespace_and_index_come_from_config():
    assert knowledge_base.namespace() == knowledge_base.PINECONE_NAMESPACE
    assert knowledge_base.index_name() == knowledge_base.PINECONE_INDEX_NAME
