"""RAG retrieval: semantic search over the Pinecone index with LangChain."""

import asyncio
import logging
import os
import re
import ssl
from functools import lru_cache

import certifi
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536

logger = logging.getLogger("voice-agent")

# Pinecone drops an idle connection after a few seconds and reconnecting costs 1-2.5 s.
# A tiny query this often keeps it open during a call.
KEEPALIVE_INTERVAL = 4.0

# Embedded in prewarm so common questions skip the OpenAI round trip.
# Includes the phrasings the model actually used in console calls.
COMMON_QUERIES = [
    "best plan for working from home",
    "best plan for streaming",
    "best plan for gaming",
    "best plan for basic internet use",
    "best plan for a household with several devices",
    "best plan for heavy internet use",
    "plan pricing",
    "price of Home 300",
    "price of Home 500",
    "price of Home Gigabit",
    "price of Home 500 and router rental and installation fee",
    "price of Home 300 and router rental and installation fee",
    "price of Home Gigabit and router rental and installation fee",
    "router rental price",
    "installation fee",
    "contract length",
    "early termination fee",
    "data cap",
    "internet speeds",
    "which cities do you serve",
    "can I use my own router",
]

_query_embeddings: dict[str, list[float]] = {}
_keepalive_task: asyncio.Task | None = None


def index_name() -> str:
    return os.environ.get("PINECONE_INDEX_NAME", "nexaconnect-kb")


@lru_cache(maxsize=1)
def embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def vector_store() -> PineconeVectorStore:
    """Built once per process in prewarm: it looks up the index host with a blocking call."""
    return PineconeVectorStore(index_name=index_name(), embedding=embeddings())


def share_ssl_context() -> None:
    """Build Pinecone's CA-bundle SSL context in prewarm so connect() doesn't block the loop for ~1 s.

    Pinecone calls ssl.create_default_context(cafile=...) with no way to pass a context in.
    """
    original = ssl.create_default_context
    shared = lru_cache(maxsize=None)(lambda cafile: original(cafile=cafile))

    def create_default_context(*args, cafile=None, **kwargs):
        if args or kwargs or cafile is None:
            return original(*args, cafile=cafile, **kwargs)
        return shared(cafile)

    ssl.create_default_context = create_default_context
    shared(certifi.where())


def _cache_key(query: str) -> str:
    return " ".join(re.sub(r"[^\w\s]", " ", query.lower()).split())


def warm_up() -> None:
    vectors = embeddings().embed_documents(COMMON_QUERIES)
    for query, vector in zip(COMMON_QUERIES, vectors):
        _query_embeddings[_cache_key(query)] = vector


async def _keep_warm() -> None:
    probe = [1.0] + [0.0] * (EMBEDDING_DIMENSIONS - 1)  # cosine search rejects an all-zero vector
    while True:  # the first ping opens the connection during the greeting
        try:
            await vector_store().asimilarity_search_by_vector(probe, k=1)
        except Exception as e:  # a failed ping must not end the loop
            logger.debug("Pinecone keep-alive failed: %s", type(e).__name__)
        await asyncio.sleep(KEEPALIVE_INTERVAL)


async def connect() -> None:
    global _keepalive_task
    await vector_store().__aenter__()
    _keepalive_task = asyncio.create_task(_keep_warm())


async def disconnect() -> None:
    if _keepalive_task:
        _keepalive_task.cancel()
    await vector_store().aclose()


async def _embed_query(query: str) -> list[float]:
    key = _cache_key(query)
    if key not in _query_embeddings:
        _query_embeddings[key] = await embeddings().aembed_query(query)
    return _query_embeddings[key]


async def search(query: str, k: int = 3) -> list[dict]:
    docs = await vector_store().asimilarity_search_by_vector(await _embed_query(query), k=k)
    return [{"source": doc.metadata.get("source"), "content": doc.page_content} for doc in docs]
