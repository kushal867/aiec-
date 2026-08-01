from functools import lru_cache

from sentence_transformers import SentenceTransformer

from app.config import config

# BGE models are trained asymmetrically: queries get this instruction prefix,
# documents/passages do not. Improves retrieval quality over embedding both
# sides identically. https://huggingface.co/BAAI/bge-small-en-v1.5
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    # Runs fully locally (CPU) — no API key, no network calls at inference
    # time, no per-request cost. Model weights download once from the
    # Hugging Face Hub on first run and are cached under ~/.cache.
    return SentenceTransformer(config.embedding_model)


def embed_texts(texts: list[str], input_type: str) -> list[list[float]]:
    model = _get_model()
    inputs = [_QUERY_PREFIX + t for t in texts] if input_type == "query" else texts
    embeddings = model.encode(inputs, normalize_embeddings=True)
    return embeddings.tolist()


def embed_query(text: str) -> list[float]:
    return embed_texts([text], "query")[0]
