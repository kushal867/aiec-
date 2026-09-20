"""
Generates a supervised fine-tuning dataset for the AIEC chat assistant,
entirely offline and without calling any LLM (Claude or otherwise).

How it works: the existing rule-based chat engine (app/services/chat_answer.py)
is already a *correct*, grounded responder — it just answers by rigid keyword
matching instead of natural language understanding. This script throws a large,
varied set of realistic student phrasings (many ways to ask the same thing,
typos, Romanized Nepali, mixed intents) at that engine and records the
question -> engine-produced answer pairs.

The resulting JSONL is training data for a small local model: the model
learns to reproduce the *policy* embedded in chat_answer.py (only state facts
from the course DB, say "I don't have that on file" instead of guessing,
match the country/field/budget the student actually asked about) while
generalizing past the rigid keyword rules to phrasings the rules don't cover.

No student PII, no real conversations — every question here is synthetic.

Usage:
    python -m app.scripts.generate_training_data [--out PATH] [--seed N]
"""

import argparse
import json
import random
from pathlib import Path
from typing import Iterator

from app.services.chat_answer import (
    _comparison_reply,
    _is_nepali_roman,
    _lookup_courses,
    _lookup_universities,
    _small_talk_reply,
    generate_answer,
)
from app.services.lead_scoring import StudentProfile
from app.services.local_chat_generation import SYSTEM_PROMPT, _build_data_block
from app.services.retrieval import retrieve_relevant_chunks

_COUNTRIES = ["Australia", "USA", "Canada", "UK", "Japan", "South Korea"]
_COUNTRY_COLLOQUIAL = {
    "USA": ["USA", "the US", "America", "the States"],
    "UK": ["UK", "the UK", "Britain", "England"],
    "South Korea": ["South Korea", "Korea"],
}

_FIELDS = [
    "nursing", "computer science", "business", "hospitality", "engineering",
    "IT", "data science", "accounting", "psychology", "law", "early childhood education",
    "cyber security", "culinary arts", "architecture", "fashion design", "artificial intelligence",
]

_BUDGETS = [3000, 5000, 8000, 12000, 15000, 20000, 25000]

_TEMPLATES_FIELD = [
    "Do you have {field} courses?",
    "I want to study {field}, what options do you have?",
    "Show me {field} programs",
    "What {field} courses are available?",
    "Is there any {field} course for me?",
    "looking for {field} course options",
    "can you recommend a good {field} program",
    "hey do u guys offer {field}",
    "i'm interested in {field}, help me out",
    "any {field} degree available",
    "what about {field}, do you have that",
    "i finished high school and want to do {field}",
    "where can i study {field} abroad",
    "{field} kaha padhna paincha",
    "is {field} a good field to study abroad",
    "planning to pursue {field}, what are my choices",
]

_TEMPLATES_FIELD_COUNTRY = [
    "What {field} courses do you have in {country}?",
    "I want to study {field} in {country}",
    "{field} programs in {country}?",
    "Can I study {field} in {country} with a low budget?",
    "is {field} available in {country}",
    "looking for {field} degree in {country} specifically",
    "{country} ma {field} padhna man cha",
    "which university in {country} offers {field}",
    "cheapest {field} course in {country}",
    "{field} + {country}, what do you have",
]

_TEMPLATES_COUNTRY = [
    "What courses are available in {country}?",
    "Show me universities in {country}",
    "I'm interested in studying in {country}",
    "options for {country}",
    "tell me about studying in {country}",
    "can I get a student visa for {country}",
    "what's it like studying in {country}",
    "{country} ma k k course cha",
    "give me info about {country} for study abroad",
    "is {country} a good option for international students",
    "how much does it cost to study in {country}",
]

_TEMPLATES_UNIVERSITY = [
    "Which universities are in {country}?",
    "What universities do you partner with in {country}?",
    "top universities in {country}",
    "any good colleges in {country}",
    "what's the QS ranking of universities you offer in {country}",
    "recommend a university in {country}",
    "top universities",
    "which universities do you work with",
    "what are the best colleges you offer",
]

_TEMPLATES_BUDGET = [
    "My budget is ${budget} per year, what can I study?",
    "I can afford under ${budget}, what are my options?",
    "budget is around {budget} dollars",
    "what courses cost less than ${budget} a year?",
    "i only have ${budget} for tuition, any suggestions",
    "cheapest courses under {budget}",
    "my parents can only afford {budget} dollars a year",
    "{budget} budget cha, k padhna milxa",
]

_TEMPLATES_COMPARISON = [
    "Compare {c1} and {c2}",
    "{c1} vs {c2}, which is better?",
    "what's the difference between studying in {c1} and {c2}",
    "should I choose {c1} or {c2}",
    "{c1} or {c2} for international students, which one",
    "difference between {c1} and {c2} fees",
]

_TEMPLATES_POLICY = [
    "How long does the visa process take?",
    "Do you offer scholarships?",
    "What documents do I need to apply?",
    "What is a No Objection Certificate?",
    "Can my family come with me on a student visa?",
    "What is the application deadline?",
    "Am I eligible if my IELTS score is low?",
    "What happens if my visa gets rejected?",
    "Do I need a co-signer for the loan?",
    "How do I book a counselling appointment?",
    "Is there an application fee?",
    "What's the refund policy if I cancel?",
    "Do you help with accommodation after arrival?",
]

_TEMPLATES_PTE_IELTS = [
    "What is PTE?",
    "What's the difference between PTE and IELTS?",
    "Is PTE accepted instead of IELTS?",
    "How long is a PTE score valid?",
    "Can I retake PTE if I get a low score?",
    "What is IELTS?",
    "How many times can I retake IELTS?",
    "How long is my IELTS score valid for?",
    "what's the score scale for PTE",
    "does PTE also test speaking and writing",
]

_TEMPLATES_SMALL_TALK = [
    "hi", "hello", "hey there", "thanks", "thank you so much", "ok great", "bye",
    "goodbye", "sure", "cool", "nice", "hey", "good morning", "hello there",
    "thanks a lot", "ok thank you", "alright", "yo",
    "namaste", "dhanyabad", "sanchai hunuhuncha", "namaskar", "dhanyawad",
]

_TEMPLATES_NEPALI_FIELD = [
    "{field} ko course cha?",
    "malai {field} padhna man cha, k options cha?",
    "{country} ma {field} course cha?",
    "{country} ma padhna man cha, kasto huncha?",
    "budget kam cha, {field} padhna milxa?",
    "malai bidesh ma {field} padhne bare jankari chahiyo",
    "{field} ko lagi kun desh ramro huncha",
]

_TYPOS = {
    "Australia": ["austrelia", "austalia", "australlia"],
    "USA": ["amrica", "unitd states", "the usa"],
    "Canada": ["canda", "canaada"],
}


def _rand_field_phrase(rng: random.Random) -> tuple[str, str]:
    field = rng.choice(_FIELDS)
    template = rng.choice(_TEMPLATES_FIELD)
    return template.format(field=field), field


def _rand_country_phrase(rng: random.Random) -> tuple[str, str]:
    country = rng.choice(_COUNTRIES)
    display = rng.choice(_COUNTRY_COLLOQUIAL.get(country, [country]))
    template = rng.choice(_TEMPLATES_COUNTRY)
    return template.format(country=display), country


def generate_questions(rng: random.Random, n_per_category: int) -> Iterator[tuple[str, StudentProfile | None]]:
    """Yields (question_text, profile) pairs. profile is None for most —
    only set when simulating a logged-in student with a saved IELTS score,
    since generate_answer() uses profile['ielts'] to filter results."""

    for _ in range(n_per_category):
        text, _ = _rand_field_phrase(rng)
        yield text, None

    for _ in range(n_per_category):
        text, _ = _rand_country_phrase(rng)
        yield text, None

    for _ in range(n_per_category):
        field = rng.choice(_FIELDS)
        country = rng.choice(_COUNTRIES)
        display = rng.choice(_COUNTRY_COLLOQUIAL.get(country, [country]))
        template = rng.choice(_TEMPLATES_FIELD_COUNTRY)
        yield template.format(field=field, country=display), None

    for _ in range(n_per_category):
        budget = rng.choice(_BUDGETS)
        template = rng.choice(_TEMPLATES_BUDGET)
        yield template.format(budget=budget), None

    for _ in range(n_per_category):
        c1, c2 = rng.sample(_COUNTRIES, 2)
        template = rng.choice(_TEMPLATES_COMPARISON)
        yield template.format(c1=c1, c2=c2), None

    for _ in range(n_per_category):
        yield rng.choice(_TEMPLATES_POLICY), None

    for _ in range(n_per_category):
        country = rng.choice(_COUNTRIES)
        display = rng.choice(_COUNTRY_COLLOQUIAL.get(country, [country]))
        template = rng.choice(_TEMPLATES_UNIVERSITY)
        yield template.format(country=display), None

    for _ in range(max(4, n_per_category // 3)):
        yield rng.choice(_TEMPLATES_PTE_IELTS), None

    for _ in range(max(4, n_per_category // 3)):
        yield rng.choice(_TEMPLATES_SMALL_TALK), None

    for _ in range(max(4, n_per_category // 3)):
        field = rng.choice(_FIELDS)
        country = rng.choice(_COUNTRIES)
        template = rng.choice(_TEMPLATES_NEPALI_FIELD)
        yield template.format(field=field, country=country), None

    for country, variants in _TYPOS.items():
        for typo in variants:
            yield f"do you have courses in {typo}?", None

    # A handful with a simulated student profile (affects IELTS filtering).
    for _ in range(max(4, n_per_category // 4)):
        field = rng.choice(_FIELDS)
        template = rng.choice(_TEMPLATES_FIELD)
        profile: StudentProfile = {
            "gpa": rng.choice([2.8, 3.2, 3.6]),
            "ielts": rng.choice([5.5, 6.0, 6.5, 7.0]),
            "budget": rng.choice(_BUDGETS),
            "gap": rng.choice([0, 1, 2]),
            "preferredCountry": "ANY",
            "academicBackground": "bachelors",
            "careerGoals": "",
            "migrationIntent": "study_then_work",
        }
        yield template.format(field=field), profile


def build_dataset(seed: int, n_per_category: int) -> list[dict]:
    rng = random.Random(seed)
    seen_questions: set[str] = set()
    records: list[dict] = []

    for question, profile in generate_questions(rng, n_per_category):
        key = question.strip().lower()
        if key in seen_questions:
            continue
        seen_questions.add(key)

        # generate_grounded_answer() (the live /api/chat path) never calls the
        # model at all for small-talk/comparison — it returns a deterministic
        # reply straight from chat_answer.py. Training the model on these
        # would teach it nothing it will ever be asked to do in production
        # (it never sees these questions), so they're excluded here rather
        # than padding the dataset with irrelevant examples.
        if _small_talk_reply(question) is not None:
            continue
        if _comparison_reply(question, "ne" if _is_nepali_roman(question) else "en") is not None:
            continue

        # Critical: the DATA block built here must be byte-for-byte the same
        # shape local_chat_generation.generate_grounded_answer() builds at
        # inference time (see _build_data_block there), or the model is
        # fine-tuned on a prompt format it will never actually see — which is
        # exactly the bug that caused an earlier checkpoint to ignore its
        # retrieved context and answer from memory instead.
        lang = "ne" if _is_nepali_roman(question) else "en"
        courses, match_type = _lookup_courses(question, profile)
        universities = _lookup_universities(question)
        retrieved_chunks = retrieve_relevant_chunks(question)
        data_block = _build_data_block(question, courses, match_type, universities, retrieved_chunks, lang)

        # The gold answer still comes from the deterministic engine — it's
        # already a correct, grounded response built from this exact same
        # data, just needs the model to learn to phrase/present it fluently.
        answer = generate_answer(question, retrieved_chunks, profile)
        records.append(
            {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": f"STUDENT QUESTION: {question}\n\nDATA:\n{data_block}"},
                    {"role": "assistant", "content": answer.reply},
                ]
            }
        )

    rng.shuffle(records)
    return records


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "data" / "training" / "chat_finetune.jsonl",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--n-per-category",
        type=int,
        default=60,
        help="Base sample count per question category before de-duplication.",
    )
    args = parser.parse_args()

    records = build_dataset(args.seed, args.n_per_category)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"Wrote {len(records)} training examples to {args.out}")


if __name__ == "__main__":
    main()
