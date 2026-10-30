import re
from pathlib import Path

import pytest

from kb import ingest

FAQ = Path(__file__).resolve().parents[2] / "data" / "F&Q Internet Plan.md"


@pytest.fixture(scope="module")
def faq_text():
    return FAQ.read_text(encoding="utf-8")


def test_file_key_is_pinecone_safe():
    assert ingest.file_key(FAQ) == "F_Q_Internet_Plan.md"


def test_hash_changes_only_when_the_text_changes():
    assert ingest.file_hash("abc") == ingest.file_hash("abc")
    assert ingest.file_hash("abc") != ingest.file_hash("abd")
    assert len(ingest.file_hash("abc")) == 12


def test_faq_is_detected(faq_text):
    assert ingest.is_faq(faq_text)
    assert not ingest.is_faq("# A plain guide\n\nSome text.")


def test_one_chunk_per_question(faq_text):
    chunks = ingest.split_file(FAQ, faq_text)
    assert len(chunks) == len(re.findall(r"^### Q:", faq_text, re.MULTILINE))


def test_every_chunk_starts_with_its_question_and_has_its_answer(faq_text):
    for chunk in ingest.split_file(FAQ, faq_text):
        assert chunk.page_content.startswith("Q: ")
        assert "\nA: " in chunk.page_content


def test_chunks_are_numbered_and_name_their_file(faq_text):
    chunks = ingest.split_file(FAQ, faq_text)
    assert [c.metadata["chunk_number"] for c in chunks] == list(range(len(chunks)))
    assert {c.metadata["source"] for c in chunks} == {FAQ.name}


def test_splitting_twice_gives_the_same_chunks(faq_text):
    first = [c.page_content for c in ingest.split_file(FAQ, faq_text)]
    second = [c.page_content for c in ingest.split_file(FAQ, faq_text)]
    assert first == second


def test_other_documents_are_split_by_size():
    text = "# Guide\n\n## Setup\n\n" + ("word " * 600)
    chunks = ingest.split_file(Path("guide.md"), text)
    assert len(chunks) > 1
    assert all(len(c.page_content) <= ingest.CHUNK_SIZE for c in chunks)
