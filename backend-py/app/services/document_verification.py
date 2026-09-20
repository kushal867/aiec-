import logging
import re
from io import BytesIO

from PIL import Image
from pypdf import PdfReader

from app.services.lead_scoring import StudentProfile

# No LLM/vision model here — text is extracted (pypdf for PDFs, pytesseract
# OCR for images) and checked against per-document-type keyword/pattern
# heuristics. This is meaningfully weaker than the previous Claude-vision
# version: it can only check whether expected words/patterns are present, not
# reason about whether a document is genuinely the right one, forged, or
# internally consistent. Treat "valid" here as "looks plausible", not a
# guarantee — there is no keyword-heuristic approach that hits 100% accuracy
# on arbitrary real-world documents.

logger = logging.getLogger("aiec.document_verification")


class OcrUnavailableError(RuntimeError):
    """Raised only for real server misconfiguration (missing tesseract
    binary/language pack) — deliberately NOT plain RuntimeError, because
    third-party libraries (e.g. pymupdf.FileDataError) also subclass
    RuntimeError for unrelated "this file is garbage" failures, and those two
    cases need different handling: this one should surface as a real error,
    a corrupt upload should degrade to "unclear"."""

DOCUMENT_TYPES = ["citizenship", "marksheet", "ielts_certificate", "pte_certificate"]

_MIN_READABLE_CHARS = 20
_SUMMARY_LENGTH = 200

_NAME_PATTERN = re.compile(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b")
# Devanagari numerals (०-९) so a Bikram Sambat date on a Nepali document
# (e.g. २०६०) counts as a detected date, not just ASCII-digit Gregorian ones.
_DATE_PATTERN = re.compile(r"\b\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}\b|\b(19|20)\d{2}\b|[०-९]{4}")
# Band scores are always x.0 or x.5 on a 0-9 scale — narrower than a bare
# digit match, less likely to false-positive on a candidate/centre number.
_BAND_SCORE_PATTERN = re.compile(r"\b[0-9]\.[05]\b")

# PTE Academic is scored 10-90 overall (not IELTS's 0-9 band scale), most
# commonly printed as "Overall Score: 65" or "65/90" — anchored to one of
# those two contexts rather than a bare two-digit number, which would
# false-positive on almost anything (dates, candidate IDs, ages).
_PTE_SCORE_PATTERN = re.compile(r"\b[1-9][0-9]\s*/\s*90\b|overall\s*score\D{0,10}([1-9][0-9])\b", re.IGNORECASE)

# Citizenship documents from Nepal (a large share of this agency's
# applicants) are issued in Nepali/Devanagari script, not English — an
# English-only keyword/regex check silently can't match them at all. OCR
# needs the tesseract-ocr-nep language pack installed
# (apt install tesseract-ocr-nep) in addition to tesseract-ocr itself; when
# it's missing, _extract_text() falls back to English-only OCR (which will
# read Devanagari as noise) rather than failing outright.
_OCR_LANGUAGES = "eng+nep"
_DEVANAGARI_CITIZENSHIP_KEYWORDS = (
    "नेपाल", "नागरिकता", "प्रमाणपत्र", "गृह मन्त्रालय", "जिल्ला प्रशासन",
)


def _ocr_image(image: Image.Image) -> str:
    try:
        import pytesseract
    except ImportError as exc:  # pragma: no cover - dependency install issue
        raise OcrUnavailableError("pytesseract is not installed") from exc

    try:
        return pytesseract.image_to_string(image, lang=_OCR_LANGUAGES)
    except pytesseract.TesseractNotFoundError as exc:
        raise OcrUnavailableError(
            "The tesseract-ocr system package is not installed on this server "
            "(run: apt install tesseract-ocr) — document verification cannot run without it."
        ) from exc
    except pytesseract.TesseractError:
        # Most likely cause: the "nep" language pack isn't installed
        # (apt install tesseract-ocr-nep). Degrade to English-only rather than
        # failing the upload outright — Devanagari text will OCR as garbage,
        # which correctly lands on "unclear" below rather than a false
        # "invalid", but flag it server-side since it's a fixable gap.
        logger.warning(
            "OCR with lang=%s failed (likely missing tesseract-ocr-nep) — falling back to English-only, "
            "which cannot read Devanagari-script documents correctly.",
            _OCR_LANGUAGES,
        )
        return pytesseract.image_to_string(image, lang="eng")


def _ocr_pdf(file_bytes: bytes) -> str:
    """Renders each page to an image and OCRs it — for PDFs that are really
    just a phone photo/scan with no embedded text layer, which pypdf's
    extract_text() silently returns nothing useful for."""
    import fitz  # PyMuPDF — pure-pip, no poppler system dependency needed

    doc = fitz.open(stream=file_bytes, filetype="pdf")
    try:
        pages_text = []
        for page in doc[:3]:
            pixmap = page.get_pixmap(dpi=200)
            image = Image.open(BytesIO(pixmap.tobytes("png")))
            pages_text.append(_ocr_image(image))
        return "\n".join(pages_text)
    finally:
        doc.close()


def _extract_text(file_bytes: bytes, mime_type: str) -> str:
    if mime_type == "application/pdf":
        try:
            reader = PdfReader(BytesIO(file_bytes))
            text = "\n".join((page.extract_text() or "") for page in reader.pages[:3])
        except Exception:
            # Corrupted/truncated/not-actually-a-PDF upload — pypdf raises
            # rather than returning empty text for these. Treat the same as
            # "no usable text layer" below rather than letting the exception
            # propagate into a 500; an unreadable upload is an expected,
            # student-facing "unclear" result, not a server error.
            logger.info("PDF failed to parse — falling back to OCR on rendered pages.")
            return _try_ocr_pdf(file_bytes)
        if len(text.strip()) >= _MIN_READABLE_CHARS:
            return text
        # No usable embedded text layer — likely a scanned/photographed PDF
        # rather than a real text-based one. Fall back to rendering pages to
        # images and OCRing those, instead of treating it as unreadable.
        logger.info("PDF had no extractable text layer — falling back to OCR on rendered pages.")
        return _try_ocr_pdf(file_bytes)

    try:
        return _ocr_image(Image.open(BytesIO(file_bytes)))
    except OcrUnavailableError:
        raise  # missing tesseract binary — a real server misconfiguration, not a bad upload
    except Exception:
        # Not a decodable image at all (corrupted upload, wrong file smuggled
        # past the content-type check) — same "unclear" treatment as below.
        logger.info("Image failed to decode.")
        return ""


def _try_ocr_pdf(file_bytes: bytes) -> str:
    try:
        return _ocr_pdf(file_bytes)
    except OcrUnavailableError:
        raise  # missing tesseract binary — real server misconfiguration
    except Exception:
        logger.info("PDF OCR rendering failed — treating as unreadable.")
        return ""


def _check_citizenship(text: str) -> list[str]:
    issues = []
    lower = text.lower()
    has_english_id_kw = any(
        kw in lower
        for kw in (
            "passport", "citizenship", "identity", "national id", "government",
            "birth certificate", "district administration", "ministry of home",
            "permanent address",
        )
    )
    has_devanagari_kw = any(kw in text for kw in _DEVANAGARI_CITIZENSHIP_KEYWORDS)
    if not has_english_id_kw and not has_devanagari_kw:
        issues.append("Doesn't look like a government-issued ID/citizenship document — no recognizable keywords found.")
    # Devanagari names don't match the Latin-script name pattern — only
    # require a detected name when the document otherwise reads as English.
    if not has_devanagari_kw and not _NAME_PATTERN.search(text):
        issues.append("No full name detected in the document.")
    if not _DATE_PATTERN.search(text):
        issues.append("No date of birth or issue date detected in the document.")
    return issues


def _check_marksheet(text: str, profile: StudentProfile | None) -> list[str]:
    issues = []
    lower = text.lower()
    if not any(
        kw in lower
        for kw in (
            "transcript", "marksheet", "mark sheet", "statement of marks", "grade", "gpa", "academic",
            "examination", "secondary school", "higher secondary", "result", "marks obtained",
        )
    ):
        issues.append("Doesn't look like an academic transcript/marksheet — no recognizable keywords found.")
    if not any(
        kw in lower for kw in ("university", "college", "institute", "school", "board", "division")
    ):
        issues.append("No institution/board name detected in the document.")
    return issues


def _check_ielts(text: str) -> list[str]:
    issues = []
    lower = text.lower()
    if "ielts" not in lower and "test report form" not in lower:
        issues.append("Doesn't look like an IELTS Test Report Form — 'IELTS' not found in the document.")
    has_skill_labels = any(k in lower for k in ("listening", "reading", "writing", "speaking", "overall"))
    has_band_scores = bool(_BAND_SCORE_PATTERN.search(text))
    if not has_skill_labels or not has_band_scores:
        issues.append("No band score section (Listening/Reading/Writing/Speaking/Overall) detected.")
    if not _DATE_PATTERN.search(text):
        issues.append("No test date detected — can't confirm it's within the last 2 years.")
    return issues


def _check_pte(text: str) -> list[str]:
    issues = []
    lower = text.lower()
    if "pte" not in lower and "pearson test of english" not in lower:
        issues.append("Doesn't look like a PTE Academic score report — 'PTE' not found in the document.")
    has_skill_labels = any(k in lower for k in ("listening", "reading", "writing", "speaking", "communicative"))
    has_score = bool(_PTE_SCORE_PATTERN.search(text))
    if not has_skill_labels or not has_score:
        issues.append("No overall score (out of 90) detected.")
    if not _DATE_PATTERN.search(text):
        issues.append("No test date detected — can't confirm it's within the last 2 years.")
    return issues


def verify_document(
    document_type: str, file_bytes: bytes, mime_type: str, profile: StudentProfile | None = None
) -> dict:
    text = _extract_text(file_bytes, mime_type).strip()
    summary = re.sub(r"\s+", " ", text)[:_SUMMARY_LENGTH] or "(no readable text found)"

    if len(text) < _MIN_READABLE_CHARS:
        return {
            "status": "unclear",
            "issues": ["Couldn't extract readable text from this file."],
            "extractedSummary": summary,
            "message": "We couldn't read this document clearly. Please upload a clearer scan or photo.",
        }

    checker = {
        "citizenship": lambda: _check_citizenship(text),
        "marksheet": lambda: _check_marksheet(text, profile),
        "ielts_certificate": lambda: _check_ielts(text),
        "pte_certificate": lambda: _check_pte(text),
    }[document_type]
    issues = checker()

    if not issues:
        status = "valid"
        message = "Looks good — this document passed our automated checks."
    elif len(issues) >= 2:
        status = "unclear"
        message = "We couldn't confirm this is the right document type. Please double-check and re-upload."
    else:
        status = "issues_found"
        message = "This document has an issue our automated check flagged — a counsellor will review it."

    return {"status": status, "issues": issues, "extractedSummary": summary, "message": message}
