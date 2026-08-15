"""Unit tests for game/tasks.py. Pure logic - no live Discord connection,
no discord.py import even required for most of these, so they're safe and
fast to run before ever wiring a validator up to a real message event.

Run directly:   python tests/test_tasks.py
Or with pytest: pytest tests/
"""

import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game.constants import TaskContent  # noqa: E402
from game.tasks import (  # noqa: E402
    CRIME_TASKS,
    CRIME_TASKS_18PLUS,
    INNOCENT_TASKS,
    INNOCENT_TASKS_18PLUS,
    ShuffleBag,
    Task,
    all_lowercase,
    check_is_reply,
    check_mentions_any,
    check_mentions_target,
    contains_all_vowels,
    contains_alliteration,
    contains_any_word,
    contains_contraction,
    contains_day_of_week,
    contains_doubled_word,
    contains_ellipsis,
    contains_hashtag,
    contains_interjection,
    contains_link,
    contains_month,
    contains_number,
    contains_ordinal,
    contains_parenthetical,
    contains_phrase,
    contains_quotation,
    contains_repeated_punctuation,
    contains_semicolon,
    contains_sequential_numbers,
    contains_text_abbreviation,
    contains_two_different_emoji,
    contains_word,
    draw_crime_task,
    draw_innocent_tasks,
    ends_with_exclamation,
    ends_with_question,
    ends_with_word,
    first_and_last_letter_match,
    has_emoji,
    has_exactly_one_caps_word,
    has_specific_emoji,
    is_all_caps,
    make_mention_any_task,
    make_mention_specific_task,
    missing_letter,
    repeats_word,
    starts_and_ends_with_same_word,
    starts_with_word,
    word_count_exact,
    word_count_max,
    word_count_min,
    word_lengths_strictly_increasing,
)


def fake_message(content, reference=None, mentions=None):
    return SimpleNamespace(content=content, reference=reference, mentions=mentions or [])


def fake_user(user_id):
    return SimpleNamespace(id=user_id)


# --------------------------------------------------------------------------
# Text primitives
# --------------------------------------------------------------------------

def test_contains_word():
    assert contains_word("I love pineapple on pizza", "pineapple")
    assert contains_word("PINEAPPLE is great", "pineapple")  # case-insensitive
    assert not contains_word("I love pineapples on pizza", "pineapple")  # not a whole-word match
    assert not contains_word("nothing here", "pineapple")


def test_contains_any_word():
    assert contains_any_word("my dog is great", ("dog", "cat", "bird"))
    assert not contains_any_word("my hamster is great", ("dog", "cat", "bird"))


def test_contains_phrase():
    assert contains_phrase("just saying, that's wild", "just saying")
    assert contains_phrase("JUST SAYING", "just saying")
    assert not contains_phrase("saying just wild things", "just saying")


def test_is_all_caps():
    assert is_all_caps("THIS IS LOUD")
    assert not is_all_caps("This Is Not")
    assert not is_all_caps("OK")  # too short to count (< 3 letters)
    assert not is_all_caps("123 456")  # no letters at all


def test_all_lowercase():
    assert all_lowercase("this is quiet and normal")
    assert not all_lowercase("This is not")
    assert not all_lowercase("AB")  # too short


def test_has_exactly_one_caps_word():
    assert has_exactly_one_caps_word("this is REALLY good")
    assert not has_exactly_one_caps_word("this is REALLY REALLY good")  # two
    assert not has_exactly_one_caps_word("this is fine")  # zero
    assert not has_exactly_one_caps_word("I am here")  # lone "I" shouldn't count


def test_word_counts():
    assert word_count_exact("one two three four five six seven", 7)
    assert not word_count_exact("one two three", 7)
    assert word_count_min("one two three four five six seven eight nine ten eleven twelve", 12)
    assert word_count_max("hi there", 3)
    assert not word_count_max("", 3)  # empty message shouldn't satisfy a "short message" task


def test_emoji_checks():
    assert has_emoji("nice \U0001F34D")
    assert has_emoji("custom emoji <a:wave:12345>")
    assert not has_emoji("no emoji here")
    assert has_specific_emoji("nice \U0001F34D", "\U0001F34D")
    assert not has_specific_emoji("nice \U0001F389", "\U0001F34D")


def test_punctuation_checks():
    assert ends_with_question("are you sure?")
    assert not ends_with_question("are you sure")
    assert ends_with_exclamation("wow!")
    assert contains_ellipsis("well...")
    assert contains_ellipsis("well\u2026")
    assert not contains_ellipsis("well.")


def test_contains_number():
    assert contains_number("brb 5 min")
    assert not contains_number("brb soon")


def test_starts_ends_word():
    assert starts_with_word("Honestly I have no idea", "honestly")
    assert not starts_with_word("I honestly have no idea", "honestly")
    assert ends_with_word("I'll figure it out though", "though")
    assert not ends_with_word("though I'll figure it out", "though")


def test_missing_letter():
    assert missing_letter("this message has plenty of letters", "z")
    assert not missing_letter("short", "z")  # under the length floor
    assert not missing_letter("wonderful weather we are having", "w")


def test_contains_link():
    assert contains_link("check this out https://example.com/page")
    assert not contains_link("no links in this message at all")


def test_repeats_word():
    assert repeats_word("literally, I am literally dying", "literally", times=2)
    assert not repeats_word("literally dying", "literally", times=2)


# --------------------------------------------------------------------------
# New structural/creative primitives - the second wave of validator
# *shapes*, not just new words plugged into the originals above.
# --------------------------------------------------------------------------

def test_contains_ordinal():
    assert contains_ordinal("I came in 1st place")
    assert contains_ordinal("I came in first place")
    assert contains_ordinal("the 21st century")
    assert not contains_ordinal("nothing ordinal here")


def test_starts_and_ends_with_same_word():
    assert starts_and_ends_with_same_word("really I mean it, really")
    assert starts_and_ends_with_same_word("Really? I mean it, REALLY.")  # case-insensitive
    assert not starts_and_ends_with_same_word("no match here at all")
    assert not starts_and_ends_with_same_word("onlyoneword")


def test_contains_alliteration():
    assert contains_alliteration("Sally sells seashells by the seashore")
    assert contains_alliteration("big bold bears bounce badly")
    assert not contains_alliteration("totally random words here")
    assert not contains_alliteration("")


def test_contains_doubled_word():
    assert contains_doubled_word("no no I did not do that")
    assert contains_doubled_word("really really tired today")
    assert not contains_doubled_word("a a is one letter, does not count")
    assert not contains_doubled_word("nothing repeats here")


def test_contains_all_vowels():
    assert contains_all_vowels("I am facetiously educated")  # facetiously alone has a e i o u
    assert not contains_all_vowels("no vowels covered here")


def test_contains_hashtag():
    assert contains_hashtag("check out #throwback today")
    assert not contains_hashtag("go check <#123456789012345> please")  # Discord channel mention, not a hashtag
    assert not contains_hashtag("nothing tagged")


def test_contains_parenthetical():
    assert contains_parenthetical("this is cool (trust me) right")
    assert not contains_parenthetical("no parens here")


def test_contains_quotation():
    assert contains_quotation('she said "hello there" to me')
    assert contains_quotation("curly quotes work too \u201Clike this\u201D")
    assert not contains_quotation("it's just an apostrophe")
    assert not contains_quotation("no quotes at all")


def test_contains_semicolon():
    assert contains_semicolon("I came; I saw; I left")
    assert not contains_semicolon("no semicolons here")


def test_word_lengths_strictly_increasing():
    assert word_lengths_strictly_increasing("I am so very incredibly overwhelmingly ecstatic")
    assert not word_lengths_strictly_increasing("the cat sat on the mat")
    assert not word_lengths_strictly_increasing("short words only here now")


def test_contains_month():
    assert contains_month("lets meet in march sometime")
    assert not contains_month("no month mentioned")


def test_contains_day_of_week():
    assert contains_day_of_week("see you on friday")
    assert not contains_day_of_week("no day mentioned")


def test_contains_sequential_numbers():
    assert contains_sequential_numbers("ready, 3, 2, 1, go!", direction="down")
    assert contains_sequential_numbers("counting 1, 2, 3 up we go", direction="up")
    assert not contains_sequential_numbers("5, 9, 2 random numbers", direction="down")
    assert not contains_sequential_numbers("1, 2, 3 counting up", direction="down")


def test_first_and_last_letter_match():
    assert first_and_last_letter_match("Awesome day today, definitely A")
    assert not first_and_last_letter_match("no match at the ends")


def test_contains_text_abbreviation():
    assert contains_text_abbreviation("lol that is so true")
    assert not contains_text_abbreviation("nothing abbreviated")


def test_contains_contraction():
    assert contains_contraction("I don't think so")
    assert not contains_contraction("I do not think so")


def test_contains_repeated_punctuation():
    assert contains_repeated_punctuation("wait what!!! really")
    assert not contains_repeated_punctuation("wait what! really")


def test_contains_two_different_emoji():
    assert contains_two_different_emoji("so happy right now \U0001F600\U0001F389")
    assert not contains_two_different_emoji("so happy \U0001F600\U0001F600")
    assert not contains_two_different_emoji("just one \U0001F600 here")


def test_contains_interjection():
    assert contains_interjection("yikes that was close")
    assert not contains_interjection("nothing exclamatory")


# --------------------------------------------------------------------------
# Message-object primitives
# --------------------------------------------------------------------------

def test_check_is_reply():
    assert check_is_reply(fake_message("sure", reference=object()))
    assert not check_is_reply(fake_message("sure", reference=None))


def test_check_mentions_target():
    msg = fake_message("hey you", mentions=[fake_user(111), fake_user(222)])
    assert check_mentions_target(msg, 111)
    assert not check_mentions_target(msg, 333)


def test_check_mentions_any():
    msg = fake_message("hey you", mentions=[fake_user(111)])
    assert check_mentions_any(msg, frozenset({111, 222}))
    assert not check_mentions_any(msg, frozenset({222, 333}))


# --------------------------------------------------------------------------
# Dynamic task factories
# --------------------------------------------------------------------------

def test_make_mention_specific_task():
    task = make_mention_specific_task(555, "Alex")
    assert "Alex" in task.description
    assert task.check(fake_message("hi", mentions=[fake_user(555)]))
    assert not task.check(fake_message("hi", mentions=[fake_user(999)]))


def test_make_mention_any_task():
    task = make_mention_any_task([111, 222])
    assert task.check(fake_message("hi", mentions=[fake_user(111)]))
    assert not task.check(fake_message("hi", mentions=[fake_user(999)]))


# --------------------------------------------------------------------------
# ShuffleBag
# --------------------------------------------------------------------------

def test_shufflebag_no_repeat_until_exhausted():
    bag = ShuffleBag(["a", "b", "c", "d"])
    drawn = [bag.draw() for _ in range(4)]
    assert sorted(drawn) == ["a", "b", "c", "d"]  # exactly one of each, in some order
    # Fifth draw starts a fresh (reshuffled) cycle - still only from the pool.
    fifth = bag.draw()
    assert fifth in {"a", "b", "c", "d"}


def test_shufflebag_draw_many_is_unique_within_batch():
    bag = ShuffleBag(list(range(10)))
    batch = bag.draw_many(6)
    assert len(batch) == len(set(batch)) == 6


def test_shufflebag_draw_many_deduplicates_by_id_even_when_the_pool_repeats_one():
    # Mirrors how MENTION_ANY_SENTINEL intentionally appears twice in
    # INNOCENT_TASKS (to double its odds on any single draw()) - a batch
    # draw must never hand out both copies, since a batch goes to
    # multiple players in the same round who each need a genuinely
    # different task.
    pool = [
        Task("shared", "first copy", lambda m: False, "test"),
        Task("shared", "second copy", lambda m: False, "test"),
        Task("a", "a", lambda m: False, "test"),
        Task("b", "b", lambda m: False, "test"),
        Task("c", "c", lambda m: False, "test"),
    ]
    bag = ShuffleBag(pool)
    for _ in range(300):
        batch = bag.draw_many(4)
        ids = [t.id for t in batch]
        assert len(ids) == len(set(ids)), f"duplicate id in a single batch: {ids}"


def test_shufflebag_draw_many_rejects_a_batch_bigger_than_distinct_ids():
    # 3 items but only 2 distinct ids - draw_many(3) must fail even
    # though draw_many would have happily returned 3 *items* pre-fix.
    pool = [
        Task("shared", "first copy", lambda m: False, "test"),
        Task("shared", "second copy", lambda m: False, "test"),
        Task("a", "a", lambda m: False, "test"),
    ]
    bag = ShuffleBag(pool)
    try:
        bag.draw_many(3)
        raise AssertionError("expected ValueError - only 2 distinct ids available")
    except ValueError:
        pass
    assert len(bag.draw_many(2)) == 2  # exactly the distinct-id ceiling should still work


def test_shufflebag_draw_many_rejects_oversized_request():
    bag = ShuffleBag(["a", "b"])
    try:
        bag.draw_many(5)
        raise AssertionError("expected ValueError for a batch bigger than the pool")
    except ValueError:
        pass


# --------------------------------------------------------------------------
# Pool integrity - guards the "large and not trivially patternable" goal
# --------------------------------------------------------------------------

def test_pool_ids_are_unique_within_each_pool():
    # The two mention sentinels intentionally repeat within CRIME_TASKS /
    # INNOCENT_TASKS (multiple "slots" for the same dynamic draw), so only
    # assert uniqueness among the non-sentinel entries.
    for pool in (CRIME_TASKS, INNOCENT_TASKS, CRIME_TASKS_18PLUS, INNOCENT_TASKS_18PLUS):
        real_ids = [t.id for t in pool if not t.id.startswith("DYNAMIC_")]
        assert len(real_ids) == len(set(real_ids)), "duplicate task id in a pool"


def test_pools_are_reasonably_large():
    assert len(CRIME_TASKS) >= 60
    assert len(INNOCENT_TASKS) >= 60
    assert len(CRIME_TASKS_18PLUS) >= 55
    assert len(INNOCENT_TASKS_18PLUS) >= 55


def test_pools_overlap_in_style():
    crime_categories = {t.category for t in CRIME_TASKS}
    innocent_categories = {t.category for t in INNOCENT_TASKS}
    shared = crime_categories & innocent_categories
    # Several validator families (format/punctuation/structure/content/word/
    # mention) should appear on both sides - that's what stops "all caps =
    # always the crime" style pattern-matching from working.
    assert len(shared) >= 5, f"expected substantial category overlap, got {shared}"


def test_18plus_pools_overlap_in_style_too():
    crime_categories = {t.category for t in CRIME_TASKS_18PLUS}
    innocent_categories = {t.category for t in INNOCENT_TASKS_18PLUS}
    shared = crime_categories & innocent_categories
    assert len(shared) >= 5, f"expected substantial category overlap, got {shared}"


def test_sfw_pools_share_a_few_exact_camouflage_words():
    # Mirrors the 18+ pools' own version of this test - pineapple/
    # flamingo/jellybean (original set) and wizard/banana (added later)
    # all appear verbatim in both CRIME_TASKS and INNOCENT_TASKS.
    crime_ids = {t.id for t in CRIME_TASKS}
    innocent_ids = {t.id for t in INNOCENT_TASKS}
    shared_words = {"pineapple", "flamingo", "jellybean", "wizard", "banana"}
    for word in shared_words:
        assert f"crime_word_{word}" in crime_ids
        assert f"innocent_word_{word}" in innocent_ids


def test_18plus_pools_share_a_few_exact_camouflage_words():
    # Mirrors the SFW pools' own trick (e.g. "pineapple" appears verbatim
    # in both) - a handful of exact trigger words appear in both the 18+
    # crime and innocent pools so seeing that word doesn't tell an Officer
    # which side of the round it came from.
    crime_ids = {t.id for t in CRIME_TASKS_18PLUS}
    innocent_ids = {t.id for t in INNOCENT_TASKS_18PLUS}
    shared_words = {"crush", "ex"}
    for word in shared_words:
        assert f"crime18_word_{word}" in crime_ids
        assert f"innocent18_word_{word}" in innocent_ids
    assert "crime18_phrase_midnight_kiss" in crime_ids
    assert "innocent18_phrase_midnight_kiss" in innocent_ids


def test_18plus_tasks_check_functions_all_run_without_error():
    # Not a content-safety check (that's a human-review question) - just a
    # guard that every validator wired up in the 18+ pools actually runs
    # cleanly against a realistic message, the same sanity check the SFW
    # pools get implicitly from every other test in this file exercising
    # their validators directly.
    sample = fake_message("honestly ngl this is kind of a long story but no comment either way, right?")
    for pool in (CRIME_TASKS_18PLUS, INNOCENT_TASKS_18PLUS):
        for t in pool:
            t.check(sample)  # must not raise


def test_draw_crime_task_defaults_to_sfw():
    # No content argument - mirrors any pre-existing caller from before
    # TaskContent existed.
    sfw_ids = {t.id for t in CRIME_TASKS}
    for _ in range(20):
        assert draw_crime_task().id in sfw_ids


def test_draw_crime_task_respects_content_argument():
    sfw_ids = {t.id for t in CRIME_TASKS}
    plus_ids = {t.id for t in CRIME_TASKS_18PLUS}
    for _ in range(20):
        assert draw_crime_task(TaskContent.SFW).id in sfw_ids
        assert draw_crime_task(TaskContent.EIGHTEEN_PLUS).id in plus_ids


def test_draw_crime_task_mixed_covers_both_pools():
    sfw_ids = {t.id for t in CRIME_TASKS}
    plus_ids = {t.id for t in CRIME_TASKS_18PLUS}
    seen_sfw = seen_plus = False
    for _ in range(200):
        tid = draw_crime_task(TaskContent.MIXED).id
        seen_sfw = seen_sfw or tid in sfw_ids
        seen_plus = seen_plus or tid in plus_ids
    assert seen_sfw and seen_plus, "expected Mixed to draw from both pools across 200 tries"


def test_draw_innocent_tasks_respects_content_argument():
    plus_ids = {t.id for t in INNOCENT_TASKS_18PLUS}
    tasks = draw_innocent_tasks(5, TaskContent.EIGHTEEN_PLUS)
    assert len(tasks) == 5
    for t in tasks:
        assert t.id in plus_ids


if __name__ == "__main__":
    tests = [(name, fn) for name, fn in list(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
