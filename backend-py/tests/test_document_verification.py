import io
import shutil

import pytest
from PIL import Image, ImageDraw

from app.services.document_verification import (
    _check_citizenship,
    _check_ielts,
    _check_marksheet,
    verify_document,
)

_HAS_TESSERACT = shutil.which("tesseract") is not None
requires_tesseract = pytest.mark.skipif(not _HAS_TESSERACT, reason="tesseract-ocr not installed on this machine")


# --- regression: the original keyword list ("transcript"/"marksheet"/
# "grade"/"gpa"/"academic") missed real Indian board certificates entirely,
# which say "STATEMENT OF MARKS" / "SECONDARY SCHOOL CERTIFICATE
# EXAMINATION" and never use the word "marksheet" or "transcript" ---
def test_real_board_marksheet_wording_is_recognized():
    text = (
        "MAHARASHTRA STATE BOARD OF SECONDARY AND HIGHER SECONDARY EDUCATION PUNE\n"
        "SECONDARY SCHOOL CERTIFICATE EXAMINATION STATEMENT OF MARKS\n"
        "CANDIDATE FULL NAME Jane Doe\nResult PASS Percentage 86.80"
    )
    assert _check_marksheet(text, None) == []


def test_marksheet_missing_institution_is_flagged():
    text = "STATEMENT OF MARKS. Result PASS."
    issues = _check_marksheet(text, None)
    assert any("institution" in issue.lower() for issue in issues)


# --- regression: band-score check used to accept any bare digit; tightened
# to the real x.0/x.5 pattern IELTS actually uses ---
def test_ielts_band_score_pattern_requires_real_format():
    valid = "IELTS Test Report Form. Listening 6.0 Reading 6.5 Writing 6.0 Speaking 6.0 Overall Band Score 6.0. Date: 12/05/2025"
    assert _check_ielts(valid) == []


def test_ielts_missing_band_scores_is_flagged():
    text = "IELTS Test Report Form. Date: 12/05/2025."
    issues = _check_ielts(text)
    assert any("band score" in issue.lower() for issue in issues)


# --- regression: citizenship check was Latin-script-only, silently unable to
# validate Nepali/Devanagari documents (a large share of this agency's
# applicants) ---
def test_devanagari_citizenship_document_is_recognized():
    text = "नेपाल सरकार गृह मन्त्रालय जिल्ला प्रशासन कार्यालय सर्लाही नेपाली नागरिकताको प्रमाणपत्र जन्म मिति २०६० साल"
    assert _check_citizenship(text) == []


def test_english_citizenship_document_still_works():
    text = "Government of Australia Passport. Name: Jane Doe. Date of Birth: 01/01/1995."
    assert _check_citizenship(text) == []


def test_unrelated_text_fails_citizenship_check():
    text = "This is a business strategy memo about AI integration and lead qualification."
    issues = _check_citizenship(text)
    assert len(issues) > 0


@requires_tesseract
def test_scanned_pdf_with_no_text_layer_falls_back_to_ocr():
    """Regression: a phone photo saved/shared as PDF has no embedded text
    layer — pypdf's extract_text() returns nothing for it, and the old code
    had no fallback, so this always came back "unclear" even for a perfectly
    legible real document."""
    import fitz

    img = Image.new("RGB", (900, 300), color="white")
    draw = ImageDraw.Draw(img)
    draw.text((20, 20), "IELTS Test Report Form", fill="black")
    draw.text((20, 60), "Candidate Name: Jane Doe", fill="black")
    draw.text((20, 100), "Test Date: 12/05/2025", fill="black")
    draw.text((20, 140), "Listening 6.0 Reading 6.5 Writing 6.0 Speaking 6.0", fill="black")
    draw.text((20, 180), "Overall Band Score 6.0", fill="black")

    img_buf = io.BytesIO()
    img.save(img_buf, format="PNG")

    doc = fitz.open()
    page = doc.new_page(width=900, height=300)
    page.insert_image(fitz.Rect(0, 0, 900, 300), stream=img_buf.getvalue())
    pdf_bytes = doc.tobytes()
    doc.close()

    result = verify_document("ielts_certificate", pdf_bytes, "application/pdf")
    assert result["status"] == "valid"


def test_unreadable_file_returns_unclear_not_a_crash():
    result = verify_document("citizenship", b"not a real pdf or image", "application/pdf")
    assert result["status"] == "unclear"
