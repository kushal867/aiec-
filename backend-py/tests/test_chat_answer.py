from app.services.chat_answer import (
    NO_INFO_REPLY,
    NO_INFO_REPLY_NE,
    _candidate_keywords,
    _detect_countries,
    _extract_budget,
    _is_nepali_roman,
    generate_answer,
)
from app.services.retrieval import RetrievedChunk


# --- regression: "for the health" returned nothing until _looks_course_related
# was replaced with an always-attempt lookup + synonym expansion ---
def test_health_synonym_matches_healthcare_course(seeded_courses):
    result = generate_answer("for the health", [], None)
    assert len(result.coursesReferenced) > 0
    assert any("Healthcare" in c["courseName"] for c in result.coursesReferenced)


# --- regression: lowercase "it" (pronoun) must never trigger an IT lookup,
# only capitalized "IT" (the field) should ---
def test_capitalized_it_matches_information_technology(seeded_courses):
    result = generate_answer("i want to read the IT", [], None)
    assert any("Information Technology" in c["courseName"] for c in result.coursesReferenced)


def test_lowercase_it_pronoun_does_not_false_trigger(seeded_courses):
    candidates = _candidate_keywords("I like biology, is it good for me?")
    assert "information technology" not in candidates
    assert "computer" not in candidates


# --- regression: "america"/"the states" etc weren't recognized, only the
# literal DB string "USA" was ---
def test_country_aliases_resolve_to_db_value():
    assert _detect_countries("what universities in america") == ["USA"]
    assert _detect_countries("studying in the united kingdom") == ["UK"]
    assert _detect_countries("options in the states") == ["USA"]


def test_short_country_aliases_do_not_false_trigger_inside_words():
    assert _detect_countries("I trust this process") == []
    assert _detect_countries("using this system daily") == []


# --- regression: real, common misspellings of country names ("austrelia",
# "amrica" — both typed verbatim in real feedback on this bot) got zero
# country signal at all, so the reply either ignored the student's stated
# country entirely or fell through to "I don't have that on file" for a
# country-only message — despite the intent being obvious to a human
# reader. Typo tolerance only kicks in when no exact alias matched anywhere
# in the message, so it can't override/dilute a message that already named
# a country correctly. ---
def test_country_typos_still_resolve_to_the_right_country():
    assert _detect_countries("austrelia") == ["Australia"]
    assert _detect_countries("austraila") == ["Australia"]
    assert _detect_countries("i want to study in austrelia") == ["Australia"]
    assert _detect_countries("nursing courses in amrica") == ["USA"]
    assert _detect_countries("canda") == ["Canada"]
    assert _detect_countries("what about germny") == ["Germany"]


# --- regression guard: the typo-tolerance pass must not introduce false
# positives on ordinary policy questions with zero country signal — this is
# exactly the class of message that a prior regression (general-sample
# fallback firing on anything) already broke once before. ---
def test_country_typo_tolerance_does_not_false_trigger_on_policy_questions():
    for q in ["do you have scholarships", "how long does visa take", "can my family come with me", "hi how are you"]:
        assert _detect_countries(q) == [], f"{q!r} should not fuzzy-match a country"


def test_america_alias_returns_real_usa_course(seeded_courses):
    result = generate_answer("what are the universities in america", [], None)
    assert any(c["country"] == "USA" for c in result.coursesReferenced)


# --- regression: "programe" (typo for "program") returned nothing ---
def test_typo_tolerance_strips_trailing_e(seeded_courses):
    result = generate_answer("what are the programe list the,", [], None)
    assert any("Program" in c["courseName"] for c in result.coursesReferenced)


# --- regression: generic browse requests ("list the universities") returned
# the flat "no info" reply instead of a real sample ---
def test_generic_browse_request_returns_a_sample_not_dead_end(seeded_courses):
    result = generate_answer("list the universities", [], None)
    assert len(result.coursesReferenced) > 0


# --- regression: fashion/game/automobile were missing from the synonym table ---
def test_fashion_and_automobile_synonyms(seeded_courses):
    fashion = generate_answer("fashion design courses", [], None)
    assert any("Fashion" in c["courseName"] for c in fashion.coursesReferenced)

    car = generate_answer("car engineering programs", [], None)
    assert any("Automobile" in c["courseName"] for c in car.coursesReferenced)


# --- regression: casual/slang greetings ("good morning", "yo what's up",
# "sup", "nvm") got a random course dump instead of a real greeting reply —
# only the narrow "hi"/"hello"/"hey" set was recognized ---
def test_casual_greetings_do_not_get_a_random_course_dump(seeded_courses):
    for message in ["good morning", "yo whats up", "sup", "nvm"]:
        result = generate_answer(message, [], None)
        assert result.coursesReferenced == [], f"{message!r} should not dump random courses"
        assert NO_INFO_REPLY not in result.reply


# --- regression: "hi"/"thanks"/"bye" fell through to the generic "no info"
# message instead of a real scripted reply ---
def test_greetings_get_scripted_replies_not_no_info_message(seeded_courses):
    for message in ["hi", "hello", "thanks", "thank you", "thank you very much", "bye"]:
        result = generate_answer(message, [], None)
        assert NO_INFO_REPLY not in result.reply
        assert len(result.coursesReferenced) == 0


def test_greetings_do_not_dump_random_courses(seeded_courses):
    result = generate_answer("ok", [], None)
    assert result.coursesReferenced == []


# Messages with explicit browse intent ("list", "show", "available",
# "options", "universities"...) fall back to a general course sample rather
# than "no info" when no specific field/country matched — genuinely
# unrelated text does not (see the regression test below for why that
# distinction matters).
def test_truly_empty_catalog_falls_back_to_no_info_gracefully(test_db):
    result = generate_answer("xyzzyx qwerty", [], None)
    assert result.coursesReferenced == []
    assert NO_INFO_REPLY in result.reply


# --- regression: the general-sample fallback used to trigger on ANY
# non-greeting message, so genuine policy questions ("do you have
# scholarships", "how long does visa take", "is there an application fee",
# "can my family come with me") got a random, totally irrelevant course
# dump instead of an honest "I don't have that information" — which is
# actively worse than admitting the gap, since it looks like an answer but
# isn't one. These have zero course/country signal and no policy PDFs are
# ingested, so they must honestly say so. ---
def test_policy_questions_with_no_course_signal_get_honest_no_info(seeded_courses):
    policy_questions = [
        "do you have scholarships",
        "is there any interview required",
        "how long does visa take",
        "is there application fee",
        "can my family come with me",
        "whats the deadline to apply",
        "do i need to submit passport",
        "can i work while studying",
        "what if i fail ielts",
    ]
    for q in policy_questions:
        result = generate_answer(q, [], None)
        assert result.coursesReferenced == [], f"{q!r} should not get a random course dump"
        assert NO_INFO_REPLY in result.reply


# --- regression: course browsing (no country named in the message) sorted
# cheapest-first across all 16 countries with no priority weighting at all,
# so cheap short courses in exception countries (Romania, Cyprus, Dubai...)
# regularly outranked full programs in USA/UK/Australia — the countries this
# business actually prioritizes. Those three should fill as many of the
# result slots as are available before anything else appears. ---
def test_general_browse_prioritizes_priority_countries_over_cheaper_alternatives(seeded_courses):
    result = generate_answer("list the universities", [], None)
    countries = [c["country"] for c in result.coursesReferenced]
    priority = {"USA", "UK", "Australia"}
    # The fixture has exactly 5 priority-country rows (1 USA, 2 UK, 2 Australia);
    # all 5 must appear, and ahead of the cheaper Ireland/Japan rows that would
    # otherwise sort first on price alone.
    assert sum(1 for c in countries if c in priority) == 5
    assert all(c in priority for c in countries[:5])


# --- regression: policy-PDF replies quoted the raw source filename and page
# number inline ('From our records ("Frequently Asked Questions - AI -
# AIEC.pdf", p.28): ...') and the FAQ's own numbering ("292. ...") leaked
# straight into the answer text — reads like a database dump, not a person
# answering a question. The filename/page are still returned in `sources`
# for traceability; they just don't belong in the chat reply itself. ---
def test_faq_reply_strips_numbering_and_technical_citation(test_db):
    chunk = RetrievedChunk(
        id=1,
        text="292. What is the difference between a college and a university? Colleges generally "
        "focus on undergraduate or vocational education, while universities offer undergraduate, "
        "postgraduate, and research programs.",
        document="Frequently Asked Questions - AI - AIEC.pdf",
        page=28,
        chunkIndex=0,
        similarity=0.9,
    )
    result = generate_answer("what is the difference between a college and a university", [chunk], None)
    assert "292." not in result.reply
    assert ".pdf" not in result.reply
    assert "p.28" not in result.reply
    assert "What is the difference between a college and a university?" in result.reply
    assert result.sources == [{"document": "Frequently Asked Questions - AI - AIEC.pdf", "page": 28}]


# --- regression: a real policy-document answer got an unrelated general
# course sample stapled onto it whenever a loosely browse-intent word (here,
# "university") appeared anywhere in the question — the exact scenario a
# student hit asking "what is the difference between a college and a
# university" and getting a random 6-course dump ahead of the actual answer.
# A genuine field/country match (exact/country_sample) should still combine
# with a policy answer for real compound questions; only the weak generic
# fallback gets suppressed when there's already a real answer. ---
def test_policy_answer_suppresses_unrelated_general_sample_course_dump(seeded_courses):
    chunk = RetrievedChunk(
        id=1,
        text="What is the difference between a college and a university? Colleges generally focus on "
        "undergraduate or vocational education, while universities offer undergraduate, postgraduate, "
        "and research programs.",
        document="Frequently Asked Questions - AI - AIEC.pdf",
        page=28,
        chunkIndex=0,
        similarity=0.9,
    )
    result = generate_answer("what is the difference between a college and a university", [chunk], None)
    assert result.coursesReferenced == []
    assert "Here's a sample of what we currently offer" not in result.reply


# --- Romanized Nepali support: students commonly type in Nepali using
# English letters ("Nepali Roman"), not just English. A heuristic word-list
# detector (not real language understanding, same rule-based approach as
# everything else here) flags this and switches the scripted reply text —
# course/university/country data itself is never translated. ---
def test_is_nepali_roman_detects_common_signal_words():
    assert _is_nepali_roman("malai australia ma nursing padhna man cha")
    assert _is_nepali_roman("namaste, k xa hajur")
    assert not _is_nepali_roman("hi, what courses do you offer")
    assert not _is_nepali_roman("I want to study nursing in Australia")


def test_nepali_greeting_gets_nepali_scripted_reply(seeded_courses):
    result = generate_answer("namaste", [], None)
    assert "Namaste!" in result.reply
    assert result.coursesReferenced == []

    result = generate_answer("dhanyabad", [], None)
    assert "Swagat cha" in result.reply


def test_nepali_course_query_replies_in_nepali_with_correct_courses(seeded_courses):
    result = generate_answer("malai australia ma nursing padhna man cha", [], None)
    assert "Tapaile sodheko sanga milne jati" in result.reply
    assert "chahincha" in result.reply  # localized IELTS phrasing, not "IELTS 7.0+"
    assert any("Nursing" in c["courseName"] and c["country"] == "Australia" for c in result.coursesReferenced)


def test_nepali_no_match_gets_nepali_no_info_reply(test_db):
    result = generate_answer("malai yesko barema kehi thaha chaina hola", [], None)
    assert result.reply == NO_INFO_REPLY_NE
    assert result.reply != NO_INFO_REPLY


# --- regression: a stated budget in the message was silently ignored —
# "courses under 5000 dollars" showed the same unfiltered sample as a plain
# "what courses do you offer", and a budget-only message with no field or
# country signal ("my budget is 3000") fell all the way through to the flat
# "I don't have that on file" reply, since "budget" wasn't recognized as
# browse intent at all. ---
def test_budget_extraction_recognizes_common_phrasings():
    assert _extract_budget("what courses are under 5000 dollars") == 5000.0
    assert _extract_budget("my budget is 3000") == 3000.0
    assert _extract_budget("$8000 nursing course") == 8000.0
    assert _extract_budget("under $15,000") == 15000.0
    assert _extract_budget("affordable nursing courses") is None
    # small numbers anchored to "under" that clearly aren't a dollar figure
    # must not be misread as a budget
    assert _extract_budget("call me back under 5 minutes") is None
    assert _extract_budget("I am 25 years old") is None


def test_budget_only_message_returns_courses_within_budget_instead_of_no_info(seeded_courses):
    result = generate_answer("my budget is 5000", [], None)
    assert result.coursesReferenced != []
    assert all(c["feePerYear"] <= 5000 for c in result.coursesReferenced)
    assert "Here's what's available within that budget:" in result.reply


def test_budget_narrows_a_field_specific_query_too(seeded_courses):
    # Without a budget, nursing search should include the $25,000 Australia
    # course; with a $16,000 cap it must not.
    unfiltered = generate_answer("nursing courses", [], None)
    assert any(c["feePerYear"] == 25000 for c in unfiltered.coursesReferenced)

    capped = generate_answer("nursing courses under $16000", [], None)
    assert capped.coursesReferenced != []
    assert all(c["feePerYear"] <= 16000 for c in capped.coursesReferenced)


# --- new: "compare X vs Y" (brief 2.6, "country comparison") — real
# aggregate stats computed straight from the course table, never a guess.
# Fixture has 2 Australia rows (fees 15000/25000, IELTS 5.5/7.0) and 2 UK
# rows (fees 14000/18000, IELTS 6.5/6.5). ---
def test_country_comparison_returns_real_aggregate_stats(seeded_courses):
    result = generate_answer("compare studying in australia vs uk", [], None)
    assert result.coursesReferenced == []
    assert "Australia — 2 courses on file, fees $15,000-$25,000/year, IELTS 5.5-7.0" in result.reply
    assert "UK — 2 courses on file, fees $14,000-$18,000/year, IELTS 6.5-6.5" in result.reply


def test_comparison_requires_explicit_comparison_language(seeded_courses):
    # Two countries mentioned, but nothing signals a comparison was wanted —
    # must not hijack an ordinary message into a stats table.
    result = generate_answer("i studied in the usa and now want to try uk", [], None)
    assert "Here's how those compare" not in result.reply


def test_nepali_comparison_request_replies_in_nepali(seeded_courses):
    result = generate_answer("australia vs uk compare garne, kun ramro cha", [], None)
    assert "yesari compare huncha" in result.reply
    assert "Australia —" in result.reply and "UK —" in result.reply


# --- regression: a country mention with no course-keyword match ("explain
# the visa process for UK") returned a UK course-list dump that never
# addressed the actual question — looked like an answer but wasn't one, the
# same failure mode as the general_sample regression above. Must fall
# through to the honest "no info" reply instead, even though UK courses do
# exist in the fixture. ---
def test_policy_question_with_country_gets_honest_no_info_not_course_dump(seeded_courses):
    for q in ["explain the visa process for uk", "what is the application process for australia", "scholarship options in uk"]:
        result = generate_answer(q, [], None)
        assert result.coursesReferenced == [], f"{q!r} should not get a course dump"
        assert NO_INFO_REPLY in result.reply


def test_ordinary_country_query_without_policy_words_still_returns_courses(seeded_courses):
    result = generate_answer("what is available in the uk", [], None)
    assert result.coursesReferenced != []
    assert all(c["country"] == "UK" for c in result.coursesReferenced)
