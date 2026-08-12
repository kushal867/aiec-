import re

_CHUNK_SIZE = 1200
_CHUNK_OVERLAP = 150
_BOUNDARY_LOOKAHEAD = 200

_SENTENCE_BREAK = re.compile(r"[.!?]\s")

# Matches the start of a numbered FAQ entry ("14. Which English language
# tests are accepted?") once whitespace has been collapsed to single spaces.
# The capital-letter lookahead keeps this from matching a decimal number
# ("6.0 to 7.5") — the digit after the period there isn't a capital letter.
_FAQ_QUESTION_START = re.compile(r"(?<!\d)(\d{1,3})\.\s+(?=[A-Z])")

# Require several matches, not just one — a single numbered legal clause in
# an otherwise normal policy PDF shouldn't force FAQ-style splitting.
_MIN_FAQ_MATCHES = 3


def _is_sequential_numbering(matches: list[re.Match]) -> bool:
    """A real enumerated list (1, 2, 3, ...) is monotonically increasing.
    Coincidental digit-period-capital matches in ordinary prose (a page full
    of "$50. Universities require...", "$30. Other institutions...") mostly
    aren't. Allows a little noise (e.g. one out-of-order figure) rather than
    requiring a perfect run, since PDF text extraction is occasionally messy."""
    numbers = [int(m.group(1)) for m in matches]
    ascending = sum(1 for a, b in zip(numbers, numbers[1:]) if b > a)
    return ascending >= len(numbers) - 2


def _split_faq_questions(text: str) -> list[str] | None:
    """Splits FAQ-formatted text into one chunk per numbered Q&A pair instead
    of a fixed-size sliding window. Generic chunking on a document like a
    500-question FAQ PDF lumps 6-8 unrelated questions into a single
    1200-char chunk — e.g. IELTS score requirements ended up in the same
    chunk as intake months and a scholarships intro, so a student asking
    "what IELTS score do I need" got a paragraph of noise back instead of
    the one line that actually answers it. This system never rewrites
    retrieved text (see chat_answer.py) — the chunk boundaries ARE the
    answer quality, so they need to match the document's real structure.
    Returns None (defer to the generic chunker) when the text doesn't look
    like a numbered FAQ."""
    matches = list(_FAQ_QUESTION_START.finditer(text))
    if len(matches) < _MIN_FAQ_MATCHES or not _is_sequential_numbering(matches):
        return None

    segments: list[str] = []
    lead = text[: matches[0].start()].strip()
    if lead:
        segments.append(lead)

    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment = text[match.start() : end].strip()
        if segment:
            segments.append(segment)

    return segments


def _chunk_by_sliding_window(normalized: str, chunk_size: int, overlap: int) -> list[str]:
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


def chunk_text(text: str, chunk_size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> list[str]:
    """Splits text into chunks. FAQ-formatted text (numbered Q&A pairs) is
    split one-chunk-per-question (see _split_faq_questions); anything else
    falls back to overlapping sliding-window chunks, preferring to break on
    sentence boundaries near the target size rather than mid-sentence."""
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []

    faq_segments = _split_faq_questions(normalized)
    if faq_segments is not None:
        chunks: list[str] = []
        for segment in faq_segments:
            if len(segment) <= chunk_size:
                chunks.append(segment)
            else:
                chunks.extend(_chunk_by_sliding_window(segment, chunk_size, overlap))
        return chunks

    if len(normalized) <= chunk_size:
        return [normalized]

    return _chunk_by_sliding_window(normalized, chunk_size, overlap)
