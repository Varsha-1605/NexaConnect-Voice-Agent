import asyncio
import logging
import re
import ssl
import threading
import time
from functools import lru_cache

import certifi
from langchain_openai import OpenAIEmbeddings
from langchain_pinecone import PineconeVectorStore

from config import (
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    KEEPALIVE_INTERVAL,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    PREWARM_KB_TIMEOUT,
    SEARCH_RESULTS,
    SEARCH_TIMEOUT,
)

logger = logging.getLogger("voice-agent")

UNAVAILABLE = (
    "The knowledge base is not available right now. Tell the customer you can't check that "
    "at the moment and offer a team member. Do not answer from memory."
)

# embedded in prewarm to skip the OpenAI call
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
_last_search_at = 0.0


def index_name() -> str:
    return PINECONE_INDEX_NAME


def namespace() -> str:
    return PINECONE_NAMESPACE


@lru_cache(maxsize=1)
def embeddings() -> OpenAIEmbeddings:
    return OpenAIEmbeddings(model=EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def vector_store() -> PineconeVectorStore:
    return PineconeVectorStore(index_name=index_name(), embedding=embeddings(), namespace=namespace())


def prepare_vector_store(timeout: float = PREWARM_KB_TIMEOUT) -> None:
    thread = threading.Thread(target=vector_store, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        logger.warning("Pinecone index lookup is slow; it will finish at call start")


def share_ssl_context() -> None:
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
        if time.monotonic() - _last_search_at < KEEPALIVE_INTERVAL:
            await asyncio.sleep(KEEPALIVE_INTERVAL)  # a real search just kept it warm
            continue
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


async def search(query: str, k: int = SEARCH_RESULTS) -> list[dict]:
    global _last_search_at
    _last_search_at = time.monotonic()

    async def run() -> list[dict]:
        docs = await vector_store().asimilarity_search_by_vector(await _embed_query(query), k=k)
        return [{"source": doc.metadata.get("source"), "content": doc.page_content} for doc in docs]

    return await asyncio.wait_for(run(), SEARCH_TIMEOUT)


async def search_or_unavailable(query: str) -> list[dict] | str:
    try:
        return await search(query) or "No relevant information found."
    except Exception as e:
        logger.warning(
            "Knowledge base search failed: %s", type(e).__name__, extra={"event": "kb_unavailable"}
        )
        return UNAVAILABLE
