import os
from pathlib import Path

import pytest
import yaml

from config import SEARCH_RESULTS
from services import knowledge_base

MINIMUM_RECALL = 0.95
QUESTIONS = yaml.safe_load((Path(__file__).parent / "questions.yaml").read_text(encoding="utf-8"))

needs_keys = pytest.mark.skipif(
    not (os.environ.get("PINECONE_API_KEY") and os.environ.get("OPENAI_API_KEY")),
    reason="needs PINECONE_API_KEY and OPENAI_API_KEY",
)


async def found(item) -> bool:
    results = await knowledge_base.search(item["ask"], k=SEARCH_RESULTS)
    return any(r["content"].startswith(f"Q: {item['expect']}") for r in results)


@needs_keys
async def test_recall_at_3(monkeypatch):
    # relaxed time limit: this measures relevance, not speed
    monkeypatch.setattr(knowledge_base, "SEARCH_TIMEOUT", 30.0)
    knowledge_base.share_ssl_context()
    knowledge_base.prepare_vector_store(timeout=30.0)
    await knowledge_base.connect()
    try:
        missed = [item["ask"] for item in QUESTIONS if not await found(item)]
    finally:
        await knowledge_base.disconnect()
    recall = 1 - len(missed) / len(QUESTIONS)
    print(f"\nrecall@{SEARCH_RESULTS}: {recall:.0%} ({len(QUESTIONS) - len(missed)}/{len(QUESTIONS)})")
    for question in missed:
        print("  missed:", question)
    assert recall >= MINIMUM_RECALL, f"recall {recall:.0%} is below {MINIMUM_RECALL:.0%}; missed: {missed}"


def test_questions_point_at_real_faq_entries():
    faq = (Path(__file__).resolve().parents[2] / "data" / "F&Q Internet Plan.md").read_text(encoding="utf-8")
    for item in QUESTIONS:
        assert f"### Q: {item['expect']}" in faq, f"not in the FAQ: {item['expect']}"
