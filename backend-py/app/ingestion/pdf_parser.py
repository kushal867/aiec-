from dataclasses import dataclass
from io import BytesIO

from pypdf import PdfReader


@dataclass
class ParsedPage:
    page: int
    text: str


def parse_pdf_pages(data: bytes) -> list[ParsedPage]:
    """Parses a PDF buffer into per-page text, needed later for citations
    (e.g. "see page 4 of the Canada Study Permit Guide")."""
    reader = PdfReader(BytesIO(data))
    return [ParsedPage(page=i + 1, text=page.extract_text() or "") for i, page in enumerate(reader.pages)]
