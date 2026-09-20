"""
RAG-grounded chat generation using the locally fine-tuned model instead of
Claude. Mirrors backend/src/services/claude.ts's architecture: retrieve real
data first (course DB lookup + policy PDF chunks), then have the model
phrase a natural-language reply strictly from that retrieved context — the
model is never trusted to recall facts from its own training/pretraining,
only to write fluent prose around data it's explicitly handed.

This is what fixed the hallucination seen in raw fine-tuned inference (e.g.
inventing an India-specific "No Objection Certificate" answer instead of the
real Nepal one, or answering a visa-timing question with unrelated courses):
the model was previously asked to answer from memory. Here it can only see
what retrieval actually found, and the system prompt requires it to say so
honestly when that's nothing relevant.

No LLM API calls, no Claude, no Anthropic dependency — model runs locally
via transformers + peft (LoRA adapter) in 4-bit.
"""

from dataclasses import dataclass
from pathlib import Path

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig

from app.services.chat_answer import (
    _comparison_reply,
    _is_nepali_roman,
    _lookup_courses,
    _lookup_universities,
    _small_talk_reply,
    has_policy_signal,
)
from app.services.course_matcher import format_courses_for_prompt, format_universities_for_prompt
from app.services.lead_scoring import StudentProfile
from app.services.retrieval import retrieve_relevant_chunks

BASE_MODEL = "Qwen/Qwen2.5-3B-Instruct"
ADAPTER_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "finetuned" / "aiec-chat-lora"

SYSTEM_PROMPT = (
    "You are the AIEC Global study-abroad counsellor assistant. You will be given a "
    "STUDENT QUESTION and a DATA block containing the only facts you are allowed to use "
    "(real course listings and/or policy FAQ excerpts). Answer the student's question "
    "using ONLY the information in the DATA block. Do not use outside knowledge, prior "
    "training data, or assumptions to fill gaps — especially for fees, deadlines, "
    "visa rules, or document requirements, where being wrong could mislead a student. "
    "If the DATA block is empty or doesn't actually answer the question, say plainly that "
    "you don't have that information on file and suggest the student contact a human "
    "counsellor — never invent a course, university, fee, country, or policy detail not "
    "present in the DATA block. Reply in the same language style (English or Romanized "
    "Nepali) as the student's question. Keep the reply concise and conversational."
)

_model = None
_tokenizer = None


def _load_model() -> None:
    global _model, _tokenizer
    if _model is not None:
        return
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_compute_dtype=torch.bfloat16,
        bnb_4bit_use_double_quant=True,
    )
    _tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base = AutoModelForCausalLM.from_pretrained(BASE_MODEL, quantization_config=bnb_config, device_map="auto")
    _model = PeftModel.from_pretrained(base, str(ADAPTER_DIR))
    _model.eval()


def _build_data_block(message: str, courses: list, match_type: str, universities: list, retrieved_chunks: list, lang: str) -> str:
    parts = []
    if courses:
        parts.append(f"COURSE RESULTS ({match_type}):\n{format_courses_for_prompt(courses, lang=lang)}")
    if universities:
        parts.append(f"REAL PARTNER UNIVERSITIES:\n{format_universities_for_prompt(universities, lang=lang)}")
    # Must mirror chat_answer.generate_answer()'s show_chunk logic exactly —
    # that function produces the gold training answers, and if this DATA
    # block includes a chunk the gold answer never uses (or vice versa), the
    # model is trained on a mismatch between what it's shown and what it's
    # asked to produce. Concretely: a chunk only earns a place here when the
    # student's wording actually signals policy intent, or when courses/
    # universities found nothing else to answer with — otherwise a loosely
    # related chunk (cleared similarity threshold but off-topic) used to get
    # tacked onto an already-complete course/university answer.
    show_chunk = bool(retrieved_chunks) and (has_policy_signal(message) or not (courses or universities))
    if show_chunk:
        # Only the top chunk — chat_answer.py's own generate_answer() (which
        # produces the gold training answers) only ever quotes
        # retrieved_chunks[0] in its reply, so handing the model 3 chunks
        # here would train it on unused context and needlessly bloat every
        # prompt (this alone used to push some examples past 1800 tokens).
        parts.append(f"POLICY/FAQ EXCERPT:\n{retrieved_chunks[0].text}")
    if not parts:
        return "(no matching data found for this question)"
    return "\n\n".join(parts)


@dataclass
class LocalGeneratedAnswer:
    reply: str
    sources: list
    coursesReferenced: list


def generate_grounded_answer(message: str, profile: StudentProfile | None = None) -> LocalGeneratedAnswer:
    # Deterministic paths first — same anti-hallucination shortcuts as
    # chat_answer.py, no need to burn a model call on "hi" or a country
    # comparison that's already computed straight from real numbers.
    small_talk = _small_talk_reply(message)
    if small_talk:
        return LocalGeneratedAnswer(reply=small_talk, sources=[], coursesReferenced=[])

    lang = "ne" if _is_nepali_roman(message) else "en"

    comparison = _comparison_reply(message, lang)
    if comparison:
        return LocalGeneratedAnswer(reply=comparison.reply, sources=[], coursesReferenced=[])

    courses, match_type = _lookup_courses(message, profile)
    universities = _lookup_universities(message)
    retrieved_chunks = retrieve_relevant_chunks(message)

    data_block = _build_data_block(message, courses, match_type, universities, retrieved_chunks, lang)

    _load_model()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"STUDENT QUESTION: {message}\n\nDATA:\n{data_block}"},
    ]
    prompt = _tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = _tokenizer(prompt, return_tensors="pt").to(_model.device)

    with torch.no_grad():
        output = _model.generate(
            **inputs,
            # 300 was cutting off combined course+university answers
            # mid-sentence — those routinely run past it once both sections
            # and a policy tidbit are all present.
            max_new_tokens=512,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=_tokenizer.eos_token_id,
        )
    reply = _tokenizer.decode(output[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True).strip()

    sources = [{"document": c.document, "page": c.page} for c in retrieved_chunks[:3]]
    courses_referenced = [
        {"courseName": c["course_name"], "university": c["university"], "country": c["country"], "feePerYear": c["fee_per_year"]}
        for c in courses
    ]
    return LocalGeneratedAnswer(reply=reply, sources=sources, coursesReferenced=courses_referenced)
