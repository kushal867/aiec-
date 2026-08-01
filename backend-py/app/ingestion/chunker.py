import re

_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150
_BOUNDARY_LOOKAHEAD = 200

_SENTENCE_BREAK = re.compile(r"[.!?]\s")


def chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Splits text into overlapping chunks, preferring to break on sentence
    boundaries near the target size rather than mid-sentence."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    if len(normalized) <= chunk_size:
        return [normalized]

    chunks: list[str] = []
    start = 0

    while start < len(normalized):
        end = min(start + chunk_size, len(normalized))

        if end < len(normalized):
            search_window = normalized[end : min(end + _BOUNDARY_LOOKAHEAD, len(normalized))]
            match = _SENTENCE_BREAK.search(search_window)
            if match:
                end += match.end()

        chunk = normalized[start:end].strip()
        if chunk:
            chunks.append(chunk)

        if end >= len(normalized):
            break
        start = end - overlap

    return chunks
