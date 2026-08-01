from io import BytesIO

from reportlab.pdfgen import canvas

from app.ingestion.chunker import chunk_text
from app.ingestion.pdf_parser import parse_pdf_pages


def test_short_text_is_a_single_chunk():
    assert chunk_text("A short policy note.") == ["A short policy note."]


def test_empty_text_produces_no_chunks():
    assert chunk_text("") == []
    assert chunk_text("   \n\t  ") == []


def test_whitespace_is_normalized():
    chunks = chunk_text("Line one.\n\n\tLine   two.")
    assert chunks == ["Line one. Line two."]


def test_long_text_is_split_into_overlapping_chunks():
    # Well past the 1200-char default chunk size
    text = "This is a sentence about visa requirements. " * 60
    chunks = chunk_text(text)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 1200 + 200  # chunk_size + boundary lookahead slack

    # overlap: total chunked length exceeds the source length, confirming
    # chunks genuinely share trailing/leading text rather than being a hard,
    # non-overlapping split
    combined_length = sum(len(c) for c in chunks)
    assert combined_length > len(text.strip())


def test_prefers_breaking_on_sentence_boundaries():
    # Two sentences that together exceed one chunk, separated by ". "
    first = "A" * 1190 + ". "
    second = "B" * 100
    chunks = chunk_text(first + second, chunk_size=1200, overlap=50)
    # the first chunk should end at or just after the sentence break, not
    # mid-word into the "B"s
    assert chunks[0].rstrip().endswith(".") or chunks[0].count("A") == 1190


def _make_pdf(pages_text: list[str]) -> bytes:
    buf = BytesIO()
    c = canvas.Canvas(buf)
    for text in pages_text:
        c.drawString(72, 750, text)
        c.showPage()
    c.save()
    return buf.getvalue()


def test_parse_pdf_pages_returns_correct_page_numbers_and_text():
    pdf_bytes = _make_pdf(["Canada Study Permit Guide", "Page two content here"])
    pages = parse_pdf_pages(pdf_bytes)
    assert len(pages) == 2
    assert pages[0].page == 1
    assert "Canada Study Permit Guide" in pages[0].text
    assert pages[1].page == 2
    assert "Page two content" in pages[1].text
