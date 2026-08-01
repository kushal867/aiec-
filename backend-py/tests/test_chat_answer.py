from app.services.chat_answer import _candidate_keywords, _detect_countries, generate_answer


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
        assert "I don't have grounded information" not in result.reply


# --- regression: "hi"/"thanks"/"bye" fell through to the generic "no
# grounded information" message instead of a real scripted reply ---
def test_greetings_get_scripted_replies_not_no_info_message(seeded_courses):
    for message in ["hi", "hello", "thanks", "thank you", "thank you very much", "bye"]:
        result = generate_answer(message, [], None)
        assert "I don't have grounded information" not in result.reply
        assert len(result.coursesReferenced) == 0


def test_greetings_do_not_dump_random_courses(seeded_courses):
    result = generate_answer("ok", [], None)
    assert result.coursesReferenced == []


# Non-greeting messages deliberately fall back to a general course sample
# rather than "no info" — there's no way to distinguish a vague course
# question ("what do you have?") from unrelated text without real language
# understanding, and the design choice is to err toward showing something
# real over a dead end (see chat_answer.py's _lookup_courses docstring).
# "No info" is only reachable when the catalog itself has nothing to show —
# verified here against a genuinely empty DB (test_db, not seeded_courses).
def test_truly_empty_catalog_falls_back_to_no_info_gracefully(test_db):
    result = generate_answer("xyzzyx qwerty", [], None)
    assert result.coursesReferenced == []
    assert "I don't have grounded information" in result.reply
