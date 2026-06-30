"""ChromaDB PersistentClient setup with anonymized_telemetry=False and actuators collection initialization."""

import chromadb
import chromadb.errors
from chromadb.config import Settings as ChromaSettings  # ponytail: alias avoids collision with app Settings
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction

# ponytail: module singleton; lifespan calls init_chroma_collection once, lazy fallback covers tests/CLI
_chroma_collection = None


def init_chroma_collection(settings):
    """Build PersistentClient + collection and cache it in the module-level singleton.

    Called by the FastAPI lifespan so the client is constructed exactly once per process.
    Raises ValueError if the 'actuators' collection is missing (ingest not run).
    """
    global _chroma_collection
    client = chromadb.PersistentClient(
        path=settings.chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    ef = OpenAIEmbeddingFunction(
        api_key=settings.openai_api_key,
        model_name=settings.embedding_model,
    )
    try:
        _chroma_collection = client.get_collection(name="actuators", embedding_function=ef)
    except (chromadb.errors.InvalidCollectionException, Exception) as exc:
        if "does not exist" in str(exc).lower() or "not found" in str(exc).lower() or "invalidcollection" in type(exc).__name__.lower():
            raise ValueError("ChromaDB collection 'actuators' not found — run scripts/ingest.py first") from exc
        raise
    return _chroma_collection


def get_chroma_collection(settings):
    """Return the cached 'actuators' ChromaDB collection, initializing lazily if needed.

    Lazy init handles test/CLI paths where lifespan doesn't run.
    """
    if _chroma_collection is None:
        return init_chroma_collection(settings)
    return _chroma_collection
