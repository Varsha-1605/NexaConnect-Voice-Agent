import argparse
import hashlib
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from pinecone import Pinecone, ServerlessSpec

from config import CHUNK_OVERLAP, CHUNK_SIZE, EMBEDDING_DIMENSIONS, INGEST_FILE_TYPES, UPLOAD_ATTEMPTS, UPLOAD_BATCH
from services.knowledge_base import embeddings, index_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

heading_splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("#", "title"), ("##", "section"), ("###", "question")],
)
size_splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def file_key(path: Path) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", path.name)


def file_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def is_faq(text: str) -> bool:
    return bool(re.search(r"^### Q:", text, re.MULTILINE))


def split_file(path: Path, text: str) -> list[Document]:
    sections = heading_splitter.split_text(text)
    chunks: list[Document] = []
    if is_faq(text):
        for section in sections:
            if "question" in section.metadata:
                section.page_content = f"{section.metadata['question']}\n{section.page_content}"
                chunks.append(section)
    else:
        for section in sections:
            for piece in size_splitter.split_text(section.page_content):
                chunks.append(Document(page_content=piece, metadata=dict(section.metadata)))
    for number, chunk in enumerate(chunks):
        chunk.metadata.update({"source": path.name, "chunk_number": number})
    return chunks


def existing_ids(index, namespace: str, prefix: str = "") -> list[str]:
    ids: list[str] = []
    for page in index.list(prefix=prefix, namespace=namespace):
        ids.extend(page)
    return ids


def upload(store: PineconeVectorStore, chunks: list[Document], ids: list[str]) -> None:
    for start in range(0, len(chunks), UPLOAD_BATCH):
        batch, batch_ids = chunks[start : start + UPLOAD_BATCH], ids[start : start + UPLOAD_BATCH]
        for attempt in range(1, UPLOAD_ATTEMPTS + 1):
            try:
                store.add_documents(batch, ids=batch_ids)
                break
            except Exception:
                if attempt == UPLOAD_ATTEMPTS:
                    raise
                time.sleep(2 ** (attempt - 1))  # 1 s, then 2 s


def delete_ids(index, namespace: str, ids: list[str]) -> None:
    for start in range(0, len(ids), 1000):
        index.delete(ids=ids[start : start + 1000], namespace=namespace)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--namespace", required=True, choices=["test", "production"])
    namespace = parser.parse_args().namespace
    load_dotenv()

    pc = Pinecone(api_key=os.environ["PINECONE_API_KEY"])
    name = index_name()
    if not pc.has_index(name):
        pc.create_index(
            name=name,
            dimension=EMBEDDING_DIMENSIONS,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    index = pc.Index(name)
    store = PineconeVectorStore(index=index, embedding=embeddings(), namespace=namespace)

    files = sorted(path for pattern in INGEST_FILE_TYPES for path in DATA_DIR.glob(pattern))
    current_keys = set()
    added = skipped = 0
    for path in files:
        text = path.read_text(encoding="utf-8")
        key, digest = file_key(path), file_hash(text)
        current_keys.add(key)
        old_ids = existing_ids(index, namespace, prefix=f"{key}#")
        if old_ids and all(i.startswith(f"{key}#{digest}#") for i in old_ids):
            skipped += 1
            continue

        chunks = split_file(path, text)
        new_ids = [f"{key}#{digest}#{n}" for n in range(len(chunks))]
        upload(store, chunks, new_ids)
        delete_ids(index, namespace, [i for i in old_ids if i not in set(new_ids)])
        added += 1
        print(f"{path.name}: {len(chunks)} chunks uploaded")

    removed = [i for i in existing_ids(index, namespace) if i.split("#")[0] not in current_keys]
    delete_ids(index, namespace, removed)

    print(
        f"Namespace '{namespace}' of index '{name}': {added} file(s) uploaded, "
        f"{skipped} unchanged, {len(removed)} chunk(s) of deleted files removed."
    )


if __name__ == "__main__":
    main()
