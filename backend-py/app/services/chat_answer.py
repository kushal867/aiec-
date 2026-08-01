import re
from dataclasses import dataclass, field
from typing import Any

from app.db import get_db, query_courses
from app.services.course_matcher import format_courses_for_prompt
from app.services.lead_scoring import StudentProfile

# No LLM here — this is deliberate retrieval-only chat (see the migration
# plan). The reply is either the best-matching passage from the ingested
# policy PDFs (retrieval.py, unchanged, local embeddings) or a direct lookup
# against the real course table (course_matcher.py's SQL filtering, which was
# never Claude-dependent), never a generated/synthesized answer. This is a
# real capability drop from the previous Claude-backed version: no reasoning
# about ambiguous questions, no multi-turn awareness, no personalized prose —
# just "here's the closest matching thing we actually have on file."

# Matches the 16 countries the real course dataset covers (see
# backend-py/data/seed_courses.sql) — used to detect a country mention in the
# student's raw message so a course lookup can filter by it without an LLM
# deciding the filter arguments. Real students don't type the DB's exact
# string ("USA") — they say "America", "the US", "the States", etc. — so each
# entry maps every common alias to the exact value stored in course_name.
_COUNTRY_ALIASES: dict[str, str] = {
    "australia": "Australia",
    "usa": "USA", "us": "USA", "u.s.": "USA", "u.s.a.": "USA", "america": "USA",
    "united states": "USA", "states": "USA",
    "canada": "Canada",
    "new zealand": "New Zealand", "nz": "New Zealand",
    "uk": "UK", "u.k.": "UK", "united kingdom": "UK", "britain": "UK", "england": "UK",
    "great britain": "UK",
    "japan": "Japan",
    "south korea": "South Korea", "korea": "South Korea",
    "malta": "Malta",
    "germany": "Germany",
    "netherlands": "Netherlands", "holland": "Netherlands",
    "finland": "Finland",
    "cyprus": "Cyprus",
    "romania": "Romania",
    "ireland": "Ireland",
    "dubai": "Dubai (UAE)", "uae": "Dubai (UAE)", "emirates": "Dubai (UAE)",
    "denmark": "Denmark",
}
# Sorted longest-alias-first so "united kingdom" is checked before a shorter
# alias that might otherwise partially shadow it in a naive scan.
_COUNTRY_ALIAS_KEYS = sorted(_COUNTRY_ALIASES.keys(), key=len, reverse=True)

# A plain word-in-message == substring-in-course_name search misses almost
# every real query ("health" wouldn't have been found without this, even
# though "Certificate in Healthcare Assistant" exists — LIKE '%health%' does
# match "Healthcare", but only once a lookup is even attempted, which is what
# this map is really for: mapping what a student actually types to the
# vocabulary the course catalog actually uses (see seed_courses.sql). Each
# value is tried in order against course_name; first one with real results
# wins. Retune/extend here as real chat queries reveal more gaps.
_FIELD_SYNONYMS: dict[str, list[str]] = {
    "health": ["health", "nursing", "medic", "pharma", "dent"],
    "healthcare": ["health", "nursing"],
    "medical": ["medic", "health", "nursing", "pharma", "dent"],
    "medicine": ["medic"],
    "nurse": ["nursing"], "nursing": ["nursing"],
    "doctor": ["medic", "dent"], "dentist": ["dent"], "pharmacy": ["pharma"],
    "computer": ["computer", "computing", "information technology"],
    "computing": ["computing", "computer"],
    "software": ["computer", "computing", "data science", "cyber"],
    "programming": ["computer", "computing"],
    "technology": ["information technology", "computer"], "tech": ["information technology", "computer"],
    "cyber": ["cyber"], "security": ["cyber", "security"],
    "data": ["data science"], "artificial": ["artificial intelligence"], "intelligence": ["artificial intelligence"],
    "robotics": ["robotics"], "robot": ["robotics"],
    "engineering": ["engineering"], "engineer": ["engineering"],
    "civil": ["civil engineering"], "mechanical": ["mechatronics", "automobile", "automotive", "engineering"],
    "automotive": ["automobile", "automotive"], "automobile": ["automobile"],
    "car": ["automobile", "automotive"], "cars": ["automobile", "automotive"], "electrical": ["engineering"],
    "business": ["business"], "management": ["management", "business"], "commerce": ["business", "accounting"],
    "accounting": ["accounting"], "finance": ["finance", "accounting"], "economics": ["economics"],
    "marketing": ["business", "international business"],
    "hospitality": ["hospitality"], "hotel": ["hotel", "hospitality"], "tourism": ["tourism", "hospitality"],
    "culinary": ["culinary"], "cooking": ["culinary"], "chef": ["culinary"],
    "law": ["law"], "legal": ["law"], "psychology": ["psychology"],
    "arts": ["arts"], "art": ["arts", "animation"], "design": ["design", "animation"], "animation": ["animation"],
    "architecture": ["architecture"], "media": ["media"], "communication": ["communication", "media"],
    "journalism": ["media", "communication"],
    "fashion": ["fashion"], "game": ["game", "animation"], "gaming": ["game"],
    "logistics": ["logistics"], "supply": ["logistics", "supply chain"],
    "childcare": ["early childhood"], "children": ["early childhood"],
    "teaching": ["early childhood", "education"], "education": ["early childhood", "education"],
    "science": ["science"], "environment": ["environmental science"], "environmental": ["environmental science"],
    "energy": ["energy engineering"], "renewable": ["renewable energy"], "cloud": ["cloud computing"],
    "beauty": ["beauty"], "cosmetology": ["cosmetology", "beauty"],
    "elderly": ["elderly care", "caregiver"], "caregiver": ["caregiver", "elderly care"],
    "care": ["caregiver", "elderly care", "healthcare"],
    "english": ["english language"], "language": ["language course"], "german": ["german language"],
    "japanese": ["japanese"], "korean": ["korean"],
    "foundation": ["foundation"], "pathway": ["pathway", "foundation"],
    "international": ["international"], "relations": ["international relations"], "public": ["public health"],
}

_STOPWORDS = {
    "the", "and", "for", "with", "into", "from", "that", "this", "have", "want", "will",
    "what", "which", "about", "does", "there", "any", "can", "you", "tell", "me", "please",
    "study", "course", "courses", "program", "programs", "university", "universities",
}

# A message with none of these and no country/field match is treated as
# small talk ("hi", "thanks", "ok") and does NOT get a course dump — anything
# else that reaches the final fallback in _lookup_courses gets a general
# sample instead of a dead end, since this is a study-abroad chat widget and
# almost anything else sent to it is realistically course-related even
# without a specific field or country ("list the universities", "what do you
# have", "show me options").
_GREETING_ONLY = {
    "hi", "hello", "hey", "yo", "sup", "thanks", "thank", "ok", "okay", "yes", "no", "bye",
    "goodbye", "cool", "great", "nice", "sure", "nvm", "nevermind",
    # common filler words that ride along in a greeting phrase ("thank you",
    # "hi there", "thanks so much", "good morning", "what's up") — harmless
    # to treat as greeting-only since none of them carry course/country
    # intent on their own, and this only ever matters when EVERY word in the
    # message is in this set (see _small_talk_reply) — a real content
    # question like "what's the cheapest program" still has "cheapest" and
    # "program" outside this set, so it's unaffected either way.
    "you", "there", "so", "much", "very", "really", "good", "morning", "afternoon",
    "evening", "whats", "up", "mind", "never",
}

_GREETING_OPENERS = {"hi", "hello", "hey", "yo", "sup", "morning", "afternoon", "evening"}
_GREETING_THANKS = {"thanks", "thank"}
_GREETING_FAREWELL = {"bye", "goodbye"}

_WELCOME_REPLY = (
    "Hi! I can help you explore study-abroad options — ask about a field (e.g. \"nursing courses\"), "
    "a country (e.g. \"universities in the UK\"), or your budget, and I'll show you what we actually have on file."
)
_THANKS_REPLY = "You're welcome! Let me know if you'd like to explore any courses or countries."
_FAREWELL_REPLY = "Take care! Feel free to come back anytime you have more questions."
_ACK_REPLY = "Got it — let me know if you'd like to explore courses, universities, or countries."


def _small_talk_reply(message: str) -> str | None:
    """A message made up entirely of greeting/small-talk words gets a real
    scripted reply instead of falling through to the "no grounded
    information" message, which reads badly for something as simple as
    "hi"."""
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    if not words or words != (words & _GREETING_ONLY):
        return None
    if words & _GREETING_OPENERS:
        return _WELCOME_REPLY
    if words & _GREETING_THANKS:
        return _THANKS_REPLY
    if words & _GREETING_FAREWELL:
        return _FAREWELL_REPLY
    return _ACK_REPLY


def _detect_countries(message: str) -> list[str]:
    lower = message.lower()
    found: list[str] = []
    for alias in _COUNTRY_ALIAS_KEYS:
        # Word-boundary match, not substring — "us" as a bare substring would
        # match inside "using"/"trust"/etc; short aliases like "us"/"uk"/"nz"
        # need this to avoid constant false triggers.
        if re.search(rf"\b{re.escape(alias)}\b", lower):
            country = _COUNTRY_ALIASES[alias]
            if country not in found:
                found.append(country)
    return found


_IT_ABBREVIATION = re.compile(r"\bIT\b")


def _candidate_keywords(message: str) -> list[str]:
    """Synonym-expanded search terms first (more likely to hit a real course
    name), then raw significant words as a fallback — tried in this order
    until one returns results."""
    candidates: list[str] = []

    # "IT" (the field) only counts capitalized — lowercase "it" is almost
    # always the pronoun ("I want to study it"), and this must be checked
    # against the original-case message before it gets lowercased below.
    if _IT_ABBREVIATION.search(message):
        candidates.extend(["information technology", "computer"])

    words = re.findall(r"[a-zA-Z]+", message.lower())

    for w in words:
        for term in _FIELD_SYNONYMS.get(w, []):
            if term not in candidates:
                candidates.append(term)

    for w in words:
        if len(w) > 3 and w not in _STOPWORDS and w not in candidates:
            candidates.append(w)

    return candidates[:6]


def _typo_variants(word: str) -> list[str]:
    """A cheap, contained typo tolerance (not general fuzzy matching): strips
    a trailing 'e' or 's' one at a time. Catches the common cases without the
    cost/complexity of real edit-distance matching — "programe" -> "program",
    "diplomas" -> "diploma"."""
    variants = []
    if word.endswith("e") and len(word) > 4:
        variants.append(word[:-1])
    if word.endswith("s") and len(word) > 4:
        variants.append(word[:-1])
    return variants


def _lookup_courses(message: str, profile: StudentProfile | None) -> tuple[list[Any], str]:
    """Returns (courses, match_type), match_type one of "exact",
    "country_sample", "general_sample" — used to pick honest header wording
    (a general sample should never be introduced as "matching your
    question")."""
    countries = _detect_countries(message) or None
    max_ielts = profile["ielts"] if profile else None
    conn = get_db()

    candidates = _candidate_keywords(message)
    for keyword in candidates:
        results = query_courses(conn, countries=countries, keyword=keyword, max_ielts=max_ielts, limit=8)
        if results:
            return results, "exact"
        for variant in _typo_variants(keyword):
            results = query_courses(conn, countries=countries, keyword=variant, max_ielts=max_ielts, limit=8)
            if results:
                return results, "exact"

    if countries:
        fallback = query_courses(conn, countries=countries, max_ielts=max_ielts, limit=5)
        if fallback:
            return fallback, "country_sample"

    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    if words and words != (words & _GREETING_ONLY):
        sample = query_courses(conn, max_ielts=max_ielts, limit=6)
        if sample:
            return sample, "general_sample"

    return [], "exact"


@dataclass
class GeneratedAnswer:
    reply: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    coursesReferenced: list[dict[str, Any]] = field(default_factory=list)


_NO_INFO_REPLY = (
    "I don't have grounded information on that yet. Please contact a human counsellor for help with this question."
)


def generate_answer(latest_message: str, retrieved_chunks: list[Any], profile: StudentProfile | None = None) -> GeneratedAnswer:
    """Retrieval-only chat reply — no generation. Always attempts a
    course-table lookup (cheap, local, no LLM) plus policy-PDF retrieval, and
    combines whichever has results."""
    small_talk = _small_talk_reply(latest_message)
    if small_talk:
        return GeneratedAnswer(reply=small_talk, sources=[], coursesReferenced=[])

    reply_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    courses_referenced: list[dict[str, Any]] = []

    courses, match_type = _lookup_courses(latest_message, profile)
    if courses:
        header = {
            "exact": "Here's what we have on file that matches your question:",
            "country_sample": "We don't have an exact match for that, but here's what's available:",
            "general_sample": "Here's a sample of what we currently offer — let me know a field or country and I can narrow it down:",
        }[match_type]
        reply_parts.append(f"{header}\n" + format_courses_for_prompt(courses))
        courses_referenced = [
            {
                "courseName": c["course_name"],
                "university": c["university"],
                "country": c["country"],
                "feePerYear": c["fee_per_year"],
            }
            for c in courses
        ]

    if retrieved_chunks:
        top = retrieved_chunks[0]
        reply_parts.append(f'From our records ("{top.document}", p.{top.page}): {top.text}')
        seen: dict[str, dict[str, Any]] = {}
        for c in retrieved_chunks:
            seen[f"{c.document}:{c.page}"] = {"document": c.document, "page": c.page}
        sources = list(seen.values())

    if not reply_parts:
        return GeneratedAnswer(reply=_NO_INFO_REPLY, sources=[], coursesReferenced=[])

    return GeneratedAnswer(reply="\n\n".join(reply_parts), sources=sources, coursesReferenced=courses_referenced)
