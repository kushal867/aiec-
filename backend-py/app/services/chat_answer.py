import re
from dataclasses import dataclass, field
from typing import Any

from app.db import get_country_stats, get_db, query_courses, query_universities
from app.services.course_matcher import format_courses_for_prompt, format_universities_for_prompt
from app.services.lead_scoring import PRIORITY_COUNTRIES, StudentProfile

# No LLM here — deliberate retrieval-only chat. `generate_answer` below is no
# longer what the live /api/chat route calls (see
# app/services/local_chat_generation.py, which uses a locally fine-tuned
# model to phrase replies from the same retrieved course/policy data this
# module gathers). This module now serves two purposes: (1) the small-talk,
# country-comparison, and course/policy retrieval helpers it defines are
# reused directly by local_chat_generation.py, and (2) `generate_answer`
# itself is still used by app/scripts/generate_training_data.py as a cheap,
# deterministic "gold answer" generator to bootstrap fine-tuning data —
# useful precisely because it's rigid and never hallucinates.

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
    # Romanized Nepali equivalents, mapped to the same English search terms
    # above. Most subject/course words (nursing, business, engineering, IT,
    # hospitality) are used as-is even in Nepali speech, so they already
    # match without an entry here — these are the cases where a Nepali word
    # is actually used instead of the English loanword. A starter set, not
    # exhaustive; extend as real Nepali-Roman chat queries reveal gaps, same
    # as the English table above.
    "swasthya": ["health", "nursing", "medic", "pharma", "dent"],
    "chikitsa": ["medic", "health"],
    "sikshya": ["early childhood", "education"], "shiksha": ["early childhood", "education"],
    "kanun": ["law"],
    "vyapar": ["business"], "byapar": ["business"],
    "prabidhi": ["information technology", "computer"],
    "injiniyaring": ["engineering"],
}

_STOPWORDS = {
    "the", "and", "for", "with", "into", "from", "that", "this", "have", "want", "will",
    "what", "which", "about", "does", "there", "any", "can", "you", "tell", "me", "please",
    "study", "course", "courses", "program", "programs", "university", "universities",
    # Romanized Nepali grammatical particles/pronouns/copulas — real content
    # words in this same domain (fields, countries) are handled by
    # _FIELD_SYNONYMS/_COUNTRY_ALIASES below; these are only the connective
    # words that would otherwise get tried as useless raw DB keyword searches
    # (see the raw-fallback loop in _candidate_keywords).
    "ma", "ko", "ki", "lai", "bata", "sanga", "ra", "cha", "chha", "xa", "ho", "hoina",
    "yo", "tyo", "malai", "hamro", "hamilai", "tapai", "tapaiko", "tapailai", "vaneko",
    "vanne", "garne", "garnu", "garcha", "hune", "huncha", "hudaina", "chaincha", "chainxa",
    "chahincha", "chaidaina", "paincha", "paudaina", "khojeko", "sakinchha", "padhna", "padhai",
    "padhne", "kasto", "kaha", "kahile", "kina", "kati", "kun", "dherai", "thorai", "sabai",
    "pani", "tara", "matra", "hajur",
}

# course_name values are formatted like "Certificate in X" / "Diploma in Y" /
# "Bachelor of Z", so a bare degree-level word matches course_name LIKE
# '%word%' against nearly every row at that level, regardless of what the
# question is actually about. Real bug this caught: "What is a No Objection
# Certificate?" (a Nepal-specific policy FAQ entry, nothing to do with course
# browsing) matched "certificate" and returned 8 random Certificate-level
# courses ahead of the correct policy-PDF answer. A student naming an actual
# field ("nursing", "business") is unaffected — only bare level words are
# excluded here, not the field-synonym loop above.
_COURSE_LEVEL_WORDS = {
    "certificate", "certificates", "diploma", "diplomas", "bachelor", "bachelors",
    "master", "masters", "postgraduate", "graduate", "doctoral", "doctorate",
}

# A message made up entirely of these words gets a real greeting reply
# (see _small_talk_reply) instead of a course dump or the flat "no info"
# message.
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

# Mirrors the English greeting sets above, in Romanized Nepali. A separate,
# narrower set (not the full _NEPALI_ROMAN_SIGNAL_WORDS list below) because
# small talk needs the WHOLE message to be small talk — "namaste, canada ma
# nursing chai" has real content ("canada", "nursing") outside this set and
# must not short-circuit into a greeting reply.
_NEPALI_GREETING_ONLY = {
    "namaste", "namaskar", "sanchai", "dhanyabad", "dhanyawad", "hajur",
    "thik", "cha", "chha", "xa", "la", "huncha", "ho", "ramro", "hunxa",
}
_NEPALI_GREETING_OPENERS = {"namaste", "namaskar"}
_NEPALI_GREETING_THANKS = {"dhanyabad", "dhanyawad"}

_WELCOME_REPLY_NE = (
    "Namaste! Ma tapailai study abroad ko bare ma sahayog garna sakchu — kunai field (jastai \"nursing course\") "
    "ya desh (jastai \"UK ma kasto course cha\") sodhnus, hamro record ma je cha tyahi dekhauchu."
)
_THANKS_REPLY_NE = "Swagat cha! Kunai course, university, ya desh ko jankari chahiyo bhane sodhnus."
_ACK_REPLY_NE = "Bujhen — course, university, ya desh ko barema jankari chahiye sodhnus is."

# A heuristic word-list detector, not real language understanding — same
# rule-based approach as the rest of this module. Deliberately picks
# distinctive Nepali-only words (pronouns, copulas, particles, greetings)
# rather than short/ambiguous ones that could collide with English. This is
# a starter vocabulary; expand it as real Nepali-Roman chat traffic reveals
# gaps, the same way _FIELD_SYNONYMS above gets retuned.
_NEPALI_ROMAN_SIGNAL_WORDS = {
    "malai", "hamro", "hamilai", "tapai", "tapaiko", "tapailai", "usko", "unko", "mero", "timro",
    "cha", "chha", "xa", "chaincha", "chainxa", "chahincha", "chaidaina", "huncha", "hudaina", "hunxa",
    "vaneko", "vanne", "garne", "garnu", "garcha", "paincha", "paudaina", "khojeko",
    "padhna", "padhai", "padhne", "sakinchha",
    "kasto", "kaha", "kahile", "kina", "kati", "kun", "hajur",
    "bidesh", "deshharu", "jankari", "sahayog", "kharcha", "paisa", "samaya",
    "namaste", "namaskar", "dhanyabad", "dhanyawad", "sanchai",
}


def _is_nepali_roman(message: str) -> bool:
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    return bool(words & _NEPALI_ROMAN_SIGNAL_WORDS)


def _small_talk_reply(message: str) -> str | None:
    """A message made up entirely of greeting/small-talk words (English or
    Romanized Nepali) gets a real scripted reply instead of falling through
    to the "no info" message, which reads badly for something as simple as
    "hi" or "namaste"."""
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    if not words:
        return None
    if words == (words & _GREETING_ONLY):
        if words & _GREETING_OPENERS:
            return _WELCOME_REPLY
        if words & _GREETING_THANKS:
            return _THANKS_REPLY
        if words & _GREETING_FAREWELL:
            return _FAREWELL_REPLY
        return _ACK_REPLY
    if words == (words & _NEPALI_GREETING_ONLY):
        if words & _NEPALI_GREETING_OPENERS:
            return _WELCOME_REPLY_NE
        if words & _NEPALI_GREETING_THANKS:
            return _THANKS_REPLY_NE
        return _ACK_REPLY_NE
    return None


def _levenshtein(a: str, b: str) -> int:
    """Plain edit distance, no dependency — the candidate list below is only
    ~19 short strings, so an O(len(a)*len(b)) DP table is negligible cost
    per message."""
    if a == b:
        return 0
    if len(a) < len(b):
        a, b = b, a
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + cost)
        previous = current
    return previous[-1]


# Typo tolerance only applies to single-word aliases with enough letters
# that a 1-2 character slip can't collide with an unrelated short word
# ("uk"/"us"/"nz" and multi-word aliases like "united kingdom" are excluded
# — word-level edit distance doesn't reduce cleanly for those anyway).
_FUZZY_COUNTRY_ALIASES = {
    alias: country for alias, country in _COUNTRY_ALIASES.items() if alias.isalpha() and len(alias) >= 4
}


def _fuzzy_country_match(word: str) -> str | None:
    if len(word) < 4:
        return None
    max_distance = 1 if len(word) <= 6 else 2
    for alias, country in _FUZZY_COUNTRY_ALIASES.items():
        if abs(len(word) - len(alias)) > max_distance:
            continue
        if _levenshtein(word, alias) <= max_distance:
            return country
    return None


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

    if not found:
        # No exact alias matched anywhere in the message — try a
        # typo-tolerant pass before giving up. Real students frequently
        # misspell country names ("austrelia", "amrica" — both typed by name
        # in real feedback on this exact bot), and previously that meant
        # zero country signal at all, even though the intent was completely
        # obvious to a human reader. Only runs when nothing matched exactly,
        # to keep the risk of an unrelated word fuzzy-matching a country
        # contained to the case that otherwise finds nothing anyway.
        for word in re.findall(r"[a-zA-Z]+", lower):
            country = _fuzzy_country_match(word)
            if country and country not in found:
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
        if len(w) > 3 and w not in _STOPWORDS and w not in _COURSE_LEVEL_WORDS and w not in candidates:
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


# Regression: the general-sample fallback used to trigger on ANY message
# that wasn't pure small talk — which meant genuine policy questions
# ("do you have scholarships", "how long does visa take", "is there an
# application fee", "can my family come with me") got a random, completely
# irrelevant course dump instead of an honest "I don't have that
# information". That's worse than admitting the gap — it looks like an
# answer but isn't one. The sample now only fires when the message actually
# signals course-browsing intent.
_BROWSE_INTENT_WORDS = {
    "list", "show", "offer", "offers", "available", "options", "browse",
    "see", "courses", "course", "programs", "program", "programe", "universities",
    "university", "budget", "afford", "affordable", "cheap", "cheapest", "cheaper",
}

# Words that signal the student wants something the course catalog has no
# data on at all (visa rules, application process, scholarships, admission
# requirements beyond IELTS/level). Only checked once a country is mentioned
# AND no course keyword matched anything — see _lookup_courses's
# country_sample branch.
_POLICY_INTENT_WORDS = {
    "visa", "process", "apply", "application", "interview", "scholarship",
    "scholarships", "deadline", "requirement", "requirements", "document",
    "documents", "eligibility", "eligible",
}


def has_policy_signal(message: str) -> bool:
    """Shared by generate_answer() (decides whether to show a retrieved
    chunk in the gold/deterministic reply) and local_chat_generation.py
    (decides whether to include that chunk in the model's DATA block at
    all) — the two must agree, or the model is trained on a DATA block
    shape it won't actually see at inference, and vice versa."""
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    return bool(words & _POLICY_INTENT_WORDS)

# A literal "$5000"/"$5,000", or a number anchored to budget-signaling
# context ("budget is 5000", "under 5000 dollars", "afford 3000") — not a
# bare number anywhere in the message, since that risks grabbing a phone
# digit, a year, or an IELTS score. Checked in order; first match wins.
_DOLLAR_PATTERN = re.compile(r"\$\s*(\d[\d,]*)")
_BUDGET_CONTEXT_PATTERN = re.compile(
    r"(?:budget(?:\s+(?:is|of|around|about|roughly))?|afford(?:able)?|under|below|"
    r"less\s+than|within|max(?:imum)?)\s*(?:of|is|around|about)?\s*\$?\s*(\d[\d,]*)",
    re.IGNORECASE,
)


def _extract_budget(message: str) -> float | None:
    for pattern in (_DOLLAR_PATTERN, _BUDGET_CONTEXT_PATTERN):
        match = pattern.search(message)
        if not match:
            continue
        try:
            value = float(match.group(1).replace(",", ""))
        except ValueError:
            continue
        if value >= 100:  # guards against an unrelated small number, e.g. "under 2 minutes"
            return value
    return None


def _prioritized_courses(
    conn: Any,
    countries: list[str] | None,
    keyword: str | None,
    max_ielts: float | None,
    limit: int,
    max_fee_per_year: float | None = None,
) -> list[Any]:
    """When the student hasn't named a specific country, USA/UK/Australia
    (PRIORITY_COUNTRIES — same priority list match_courses() already uses for
    profile-based recommendations) are queried first and shown first; other
    countries only fill remaining slots as the exception, not the default.
    Without this, query_courses()'s plain cheapest-first ordering surfaces
    whichever country happens to have the cheapest matching rows (in
    practice, short certificate/language courses in Romania/Cyprus/Dubai/etc.
    ahead of full degree programs in the countries we actually prioritize)."""
    if countries:
        return query_courses(
            conn, countries=countries, keyword=keyword, max_ielts=max_ielts, max_fee_per_year=max_fee_per_year, limit=limit
        )

    primary = list(
        query_courses(
            conn,
            countries=list(PRIORITY_COUNTRIES),
            keyword=keyword,
            max_ielts=max_ielts,
            max_fee_per_year=max_fee_per_year,
            limit=limit,
        )
    )
    if len(primary) >= limit:
        return primary
    seen_ids = {c["id"] for c in primary}
    extra = query_courses(
        conn, keyword=keyword, max_ielts=max_ielts, max_fee_per_year=max_fee_per_year, limit=limit + len(primary)
    )
    for c in extra:
        if len(primary) >= limit:
            break
        if c["id"] not in seen_ids:
            primary.append(c)
            seen_ids.add(c["id"])
    return primary


def _lookup_courses(message: str, profile: StudentProfile | None) -> tuple[list[Any], str]:
    """Returns (courses, match_type), match_type one of "exact",
    "country_sample", "general_sample" — used to pick honest header wording
    (a general sample should never be introduced as "matching your
    question")."""
    countries = _detect_countries(message) or None
    max_ielts = profile["ielts"] if profile else None
    max_fee = _extract_budget(message)
    conn = get_db()

    candidates = _candidate_keywords(message)
    for keyword in candidates:
        results = _prioritized_courses(conn, countries, keyword, max_ielts, limit=8, max_fee_per_year=max_fee)
        if results:
            return results, "exact"
        for variant in _typo_variants(keyword):
            results = _prioritized_courses(conn, countries, variant, max_ielts, limit=8, max_fee_per_year=max_fee)
            if results:
                return results, "exact"

    words = set(re.findall(r"[a-zA-Z]+", message.lower()))

    # Regression: a message with zero course-keyword match but some other
    # loosely-related word ("explain the visa process for UK" — "UK" name;
    # "scholarship options in UK" — "options" is browse-intent) still fell
    # through to a country_sample or general_sample course dump — it looked
    # like an answer but never addressed what was actually asked. By this
    # point no field/course keyword matched at all (the exact loop above
    # already ran), so policy-flavored language anywhere in the message is a
    # strong signal the catalog genuinely doesn't have what's being asked
    # for; better to say so honestly (falls through to NO_INFO_REPLY) than
    # paper over it with an unrelated course list.
    policy_signal = bool(words & _POLICY_INTENT_WORDS)

    if countries and not policy_signal:
        fallback = query_courses(conn, countries=countries, max_ielts=max_ielts, max_fee_per_year=max_fee, limit=5)
        if fallback:
            return fallback, "country_sample"

    if not policy_signal and ((words & _BROWSE_INTENT_WORDS) or max_fee is not None):
        sample = _prioritized_courses(conn, None, None, max_ielts, limit=6, max_fee_per_year=max_fee)
        if sample:
            return sample, "general_sample"

    return [], "exact"


# Real named universities (db.py's `universities` table — genuine AIEC
# partner institutions, not the generic course catalog) only get looked up
# when the student explicitly asks about universities/colleges by name, not
# on every course-browsing question — "list nursing courses" shouldn't dump
# a university list, but "which universities are in Canada" should.
_UNIVERSITY_INTENT_WORDS = {"university", "universities", "college", "colleges", "institution", "institutions"}

_UNIVERSITY_HEADER = {
    "en": "Here are real partner universities we work with:",
    "ne": "Yeharu hamro real partner universities haru hun:",
}
_NO_UNIVERSITY_DATA = {
    "en": "(we don't have partner university data on file for this country yet)",
    "ne": "(yo desh ko partner university data hamro record ma chaina)",
}


def _lookup_universities(message: str) -> list[Any]:
    """Returns real partner universities matching a detected country, or the
    top globally-ranked partners if no country was named. Empty list if the
    message doesn't actually signal university-specific intent, or if we
    have no real data for the detected country (Japan/South Korea/UK
    currently have none — see seed_universities.py)."""
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    if not (words & _UNIVERSITY_INTENT_WORDS):
        return []

    countries = _detect_countries(message)
    conn = get_db()
    # Capped small (5) — this list gets rendered verbatim in both the chat
    # reply and the fine-tuning DATA block, so it directly drives prompt
    # length/cost, and a chat answer listing 10 universities is unwieldy
    # anyway (the live site's own "Top Picks" section shows a similar count).
    if countries:
        results = []
        for country in countries:
            results.extend(query_universities(conn, country=country, limit=5))
        return results
    return query_universities(conn, limit=5)


@dataclass
class GeneratedAnswer:
    reply: str
    sources: list[dict[str, Any]] = field(default_factory=list)
    coursesReferenced: list[dict[str, Any]] = field(default_factory=list)


NO_INFO_REPLY = (
    "I don't have that on file, sorry — one of our counsellors can help you with this directly. "
    "In the meantime, feel free to ask me about courses, countries, or fees."
)
NO_INFO_REPLY_NE = (
    "Maafi chahanchu, yo jankari hamro record ma chaina. Yesko lagi hamro counsellor sanga sidhai kura garnus vane "
    "ramro huncha. Tyaso samma, course, desh, ya fee ko barema sodhna sakinuhuncha."
)

_COURSE_HEADERS = {
    "exact": {
        "en": "Here's what we have on file that matches your question:",
        "ne": "Tapaile sodheko sanga milne jati hamro record ma yo cha:",
    },
    "country_sample": {
        "en": "We don't have an exact match for that, but here's what's available:",
        "ne": "Ekdam ustai match ta chaina, tara yo haru available cha:",
    },
    "general_sample": {
        "en": "Here's a sample of what we currently offer — let me know a field or country and I can narrow it down:",
        "ne": "Hamro haal ko kehi courses yeti cha — field ya desh bhannus, ma thap specific dekhaunchu:",
    },
}
_BUDGET_HEADER = {
    "en": "Here's what's available within that budget:",
    "ne": "Tapaiko budget bhitra parne yo cha:",
}
_POLICY_LEAD_IN = {"en": "Here's what I found on that:", "ne": "Yo baremaa yeti fela paren:"}

# "compare X vs Y" support (brief section 2.6, "Country comparison"). Needs
# two real countries plus explicit comparison language — two countries
# alone isn't enough signal ("I've studied in the USA and want to try the
# UK now" mentions both but isn't asking for a comparison).
_COMPARISON_WORDS = {"compare", "comparison", "vs", "versus", "better", "difference", "differences"}

_COMPARISON_HEADER = {
    "en": "Here's how those compare based on what we have on file:",
    "ne": "Hamro record ma bhako data anusar yesari compare huncha:",
}
_COMPARISON_NO_DATA = {"en": "no courses on file for this country yet", "ne": "hamro record ma yo desh ko course chaina"}
_COMPARISON_FEE_UNKNOWN = {"en": "fee not listed", "ne": "fee thaha chaina"}
_COMPARISON_IELTS_UNKNOWN = {"en": "IELTS varies by course", "ne": "IELTS course anusar farak farak huncha"}
_COMPARISON_COURSES_LABEL = {"en": "courses on file", "ne": "ota course"}


def _format_country_comparison(stats_by_country: dict[str, Any], countries: list[str], lang: str) -> str:
    lines = []
    for country in countries:
        row = stats_by_country.get(country)
        if row is None:
            lines.append(f"{country} — {_COMPARISON_NO_DATA[lang]}")
            continue
        fee_bit = (
            f"${row['min_fee']:,.0f}-${row['max_fee']:,.0f}/year" if row["min_fee"] is not None else _COMPARISON_FEE_UNKNOWN[lang]
        )
        ielts_bit = f"IELTS {row['min_ielts']}-{row['max_ielts']}" if row["min_ielts"] is not None else _COMPARISON_IELTS_UNKNOWN[lang]
        if lang == "ne":
            lines.append(f"{country} — {row['course_count']} {_COMPARISON_COURSES_LABEL[lang]}, fee {fee_bit} jati, {ielts_bit}")
        else:
            lines.append(f"{country} — {row['course_count']} {_COMPARISON_COURSES_LABEL[lang]}, fees {fee_bit}, {ielts_bit}")
    return "\n".join(lines)


def _comparison_reply(message: str, lang: str) -> GeneratedAnswer | None:
    """Real, computed-from-the-catalog country comparison — course count,
    fee range, IELTS range per country — never a guess or generated
    narrative, so there's nothing here that could be wrong the way a
    generated "USA is better for X" claim could be."""
    countries = _detect_countries(message)
    if len(countries) < 2:
        return None
    words = set(re.findall(r"[a-zA-Z]+", message.lower()))
    if not (words & _COMPARISON_WORDS):
        return None

    stats = get_country_stats(get_db(), countries)
    stats_by_country = {row["country"]: row for row in stats}
    if not stats_by_country:
        return None

    body = _format_country_comparison(stats_by_country, countries, lang)
    return GeneratedAnswer(reply=f"{_COMPARISON_HEADER[lang]}\n{body}", sources=[], coursesReferenced=[])


def generate_answer(latest_message: str, retrieved_chunks: list[Any], profile: StudentProfile | None = None) -> GeneratedAnswer:
    """Retrieval-only chat reply — no generation. Always attempts a
    course-table lookup (cheap, local, no LLM) plus policy-PDF retrieval, and
    combines whichever has results.

    Replies in Romanized Nepali when the student's own message was in
    Romanized Nepali (see _is_nepali_roman) — course names, universities,
    and countries stay as-is either way (they're proper nouns/catalog data,
    not something to translate), only the surrounding sentences change."""
    small_talk = _small_talk_reply(latest_message)
    if small_talk:
        return GeneratedAnswer(reply=small_talk, sources=[], coursesReferenced=[])

    lang = "ne" if _is_nepali_roman(latest_message) else "en"

    comparison = _comparison_reply(latest_message, lang)
    if comparison:
        return comparison

    reply_parts: list[str] = []
    sources: list[dict[str, Any]] = []
    courses_referenced: list[dict[str, Any]] = []

    courses, match_type = _lookup_courses(latest_message, profile)
    # A real policy-document answer is a specific, on-topic response to what
    # was actually asked. Bolting a "general_sample" course dump onto it too
    # (the weakest match type — it only fires because some word in the
    # message loosely signalled browse-intent, e.g. "university" appearing in
    # "what's the difference between a college and a university") reads like
    # two unrelated database exports stapled together, not an answer from a
    # person. "exact"/"country_sample" matches are a genuine response to a
    # real field/country signal, so those still combine with a policy answer
    # for compound questions.
    show_courses = bool(courses) and not (retrieved_chunks and match_type == "general_sample")
    if show_courses:
        # A budget-only message ("my budget is 3000") lands on the generic
        # "general_sample" match type since there's no field/country signal,
        # but the generic browse header ("let me know a field or country...")
        # would ignore the one thing the student did say — swap in a header
        # that actually acknowledges the budget they gave.
        if match_type == "general_sample" and _extract_budget(latest_message) is not None:
            header = _BUDGET_HEADER[lang]
        else:
            header = _COURSE_HEADERS[match_type][lang]
        reply_parts.append(f"{header}\n" + format_courses_for_prompt(courses, lang=lang))
        courses_referenced = [
            {
                "courseName": c["course_name"],
                "university": c["university"],
                "country": c["country"],
                "feePerYear": c["fee_per_year"],
            }
            for c in courses
        ]

    universities = _lookup_universities(latest_message)
    if universities:
        reply_parts.append(f"{_UNIVERSITY_HEADER[lang]}\n" + format_universities_for_prompt(universities, lang=lang))

    # Regression: a retrieved chunk used to be appended unconditionally
    # whenever similarity cleared the (fairly loose) threshold, even when the
    # question was already fully answered by courses/universities above and
    # the chunk was only loosely related — e.g. "list your universities"
    # (fully answered by the university section) pulling in an unrelated
    # I-20-form snippet just because "country" and "document" nudged the
    # embedding close enough. Only show the chunk when the student's own
    # wording actually signals they want policy info, or when courses/
    # universities found nothing else to answer with at all.
    show_chunk = bool(retrieved_chunks) and (has_policy_signal(latest_message) or not (courses or universities))

    if show_chunk:
        top = retrieved_chunks[0]
        # Source PDFs are FAQ-numbered ("292. What is..."); that's a document
        # formatting artifact, not part of the answer, so it's stripped here
        # for display only — the underlying chunk text used for retrieval is
        # untouched. Document name/page are still returned in `sources` for
        # traceability, just not spelled out inline — a counsellor answering
        # in chat wouldn't cite a filename and page number either.
        # The policy PDFs themselves are English-only source documents, so
        # the retrieved answer text stays in English regardless of `lang` —
        # only the lead-in sentence around it is localized. Machine-guessing
        # a Nepali translation of factual visa/fee/policy content would risk
        # misrepresenting it, which is worse than leaving it in English.
        answer_text = re.sub(r"^\d{1,3}\.\s+", "", top.text).strip()
        reply_parts.append(f"{_POLICY_LEAD_IN[lang]}\n{answer_text}")
        seen: dict[str, dict[str, Any]] = {}
        for c in retrieved_chunks:
            seen[f"{c.document}:{c.page}"] = {"document": c.document, "page": c.page}
        sources = list(seen.values())

    if not reply_parts:
        return GeneratedAnswer(reply=NO_INFO_REPLY_NE if lang == "ne" else NO_INFO_REPLY, sources=[], coursesReferenced=[])

    return GeneratedAnswer(reply="\n\n".join(reply_parts), sources=sources, coursesReferenced=courses_referenced)
