import os
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import MarkdownHeaderTextSplitter
from pinecone import Pinecone, ServerlessSpec

from services.knowledge_base import EMBEDDING_DIMENSIONS, embeddings, index_name

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

splitter = MarkdownHeaderTextSplitter(
    headers_to_split_on=[("##", "section"), ("###", "question")],
)


def load_chunks() -> list[Document]:
    chunks = []
    for path in sorted(DATA_DIR.glob("*.md")):
        for chunk in splitter.split_text(path.read_text(encoding="utf-8")):
            if "question" in chunk.metadata:  # one Q&A per chunk; skips titles and tables
                chunk.page_content = f"{chunk.metadata['question']}\n{chunk.page_content}"
                chunk.metadata["source"] = path.name
                chunks.append(chunk)
    return chunks


def main() -> None:
    load_dotenv()
    chunks = load_chunks()

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
    if index.describe_index_stats().total_vector_count:
        index.delete(delete_all=True)

    PineconeVectorStore(index=index, embedding=embeddings()).add_documents(chunks)
    print(f"Indexed {len(chunks)} chunks into Pinecone index '{name}'.")


if __name__ == "__main__":
    main()
