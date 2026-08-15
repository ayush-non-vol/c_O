"""Task pools for the Lawbreaker's crime and the Innocents' decoys.

Design goals (from the spec this was built against):
  - Big pools, not a handful of examples, so a few games in a row don't
    teach anyone "the" pattern.
  - Deliberate overlap: several validator *families* (all-lowercase,
    ends-with-punctuation, contains-a-link, contains-an-emoji, is-a-reply,
    even contains-a-specific-word) appear in BOTH pools with different
    parameters. Surface-level pattern matching ("all caps = always the
    crime") stops working; the Officer has to actually read the room,
    which is the whole point of the game.
  - No-repeat-until-exhausted: a ShuffleBag hands out every task once
    before any task repeats, then reshuffles. Two bags (crime, innocent)
    live at module level so they're shared across every game the bot is
    running, not reset per-round.

Every text-based validator is a small pure function that takes a plain
string, so the whole pool can be unit tested without touching discord.py
at all (see tests/test_tasks.py).
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional, Protocol, Sequence

from .constants import TaskContent


# --------------------------------------------------------------------------
# Message-like protocol (duck typing so this module has zero discord.py
# dependency and is trivial to unit test with plain stand-ins).
# --------------------------------------------------------------------------

class MessageLike(Protocol):
    content: str
    reference: Any          # None, or something truthy (discord.MessageReference)
    mentions: Sequence[Any]  # objects with an .id attribute


# --------------------------------------------------------------------------
# Text-level primitives (pure functions: str -> bool)
# --------------------------------------------------------------------------

_WORD_RE = re.compile(r"[A-Za-z']+")
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # pictographs, emoticons, transport, symbols
    "\U00002600-\U000027BF"   # misc symbols & dingbats
    "\U0001F1E6-\U0001F1FF"   # regional indicators (flag letters)
    "]"
)
_CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")  # discord custom emoji syntax
_URL_RE = re.compile(r"https?://\S+")


def _words(text: str) -> list[str]:
    return _WORD_RE.findall(text)


def contains_word(text: str, word: str) -> bool:
    """Message contains `word` as a whole word (case-insensitive)."""
    return any(w.lower() == word.lower() for w in _words(text))


def contains_any_word(text: str, words: Sequence[str]) -> bool:
    """Message contains any one of `words` as a whole word."""
    lowered = {w.lower() for w in _words(text)}
    return any(w.lower() in lowered for w in words)


def contains_phrase(text: str, phrase: str) -> bool:
    """Message contains `phrase` as a substring (case-insensitive)."""
    return phrase.lower() in text.lower()


def is_all_caps(text: str) -> bool:
    """Every letter in the message is uppercase, and there are enough
    letters that this wasn't satisfied by accident (e.g. 'OK')."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.isupper() for c in letters)


def all_lowercase(text: str) -> bool:
    """Every letter in the message is lowercase - no capital letters at
    all, not even a sentence-starting one."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 3 and all(c.islower() for c in letters)


def has_exactly_one_caps_word(text: str) -> bool:
    """Exactly one word (2+ letters) is ALL CAPS - emphasis, not shouting."""
    caps_words = [w for w in _words(text) if len(w) > 1 and w.isupper()]
    return len(caps_words) == 1


def word_count_exact(text: str, n: int) -> bool:
    return len(_words(text)) == n


def word_count_min(text: str, n: int) -> bool:
    return len(_words(text)) >= n


def word_count_max(text: str, n: int) -> bool:
    word_count = len(_words(text))
    return 0 < word_count <= n


def has_emoji(text: str) -> bool:
    return bool(_EMOJI_RE.search(text)) or bool(_CUSTOM_EMOJI_RE.search(text))


def has_specific_emoji(text: str, emoji: str) -> bool:
    return emoji in text


def ends_with_question(text: str) -> bool:
    return text.strip().endswith("?")


def ends_with_exclamation(text: str) -> bool:
    return text.strip().endswith("!")


def contains_number(text: str) -> bool:
    return any(c.isdigit() for c in text)


def starts_with_word(text: str, word: str) -> bool:
    words = _words(text)
    return bool(words) and words[0].lower() == word.lower()


def ends_with_word(text: str, word: str) -> bool:
    words = _words(text)
    return bool(words) and words[-1].lower() == word.lower()


def contains_ellipsis(text: str) -> bool:
    return "..." in text or "\u2026" in text


def missing_letter(text: str, letter: str, min_letters: int = 10) -> bool:
    """Message has at least `min_letters` letters and never uses `letter`.

    The floor keeps a one-word message from trivially "winning" by being
    too short to contain much of anything.
    """
    letters_only = [c for c in text.lower() if c.isalpha()]
    return len(letters_only) >= min_letters and letter.lower() not in letters_only


def contains_link(text: str) -> bool:
    return bool(_URL_RE.search(text))


def repeats_word(text: str, word: str, times: int = 2) -> bool:
    return sum(1 for w in _words(text) if w.lower() == word.lower()) >= times


# --------------------------------------------------------------------------
# Structural/creative primitives - a second wave of validator *shapes*, not
# just new words plugged into the originals above. These lean harder into
# "hard to do without it reading as deliberate," which is the whole point:
# a bigger, more varied pool means style alone gives away less.
# --------------------------------------------------------------------------

_ORDINAL_DIGIT_RE = re.compile(r"\b\d+(st|nd|rd|th)\b", re.IGNORECASE)
_ORDINAL_WORDS = (
    "first", "second", "third", "fourth", "fifth",
    "sixth", "seventh", "eighth", "ninth", "tenth",
)


def contains_ordinal(text: str) -> bool:
    """Message contains an ordinal - '1st'/'2nd'/'3rd'/'4th'... or the
    spelled-out word (first through tenth)."""
    if _ORDINAL_DIGIT_RE.search(text):
        return True
    return any(w.lower() in _ORDINAL_WORDS for w in _words(text))


def starts_and_ends_with_same_word(text: str) -> bool:
    """The message's first and last word are the same, case-insensitive -
    surprisingly hard to pull off without it sounding staged."""
    words = _words(text)
    return len(words) >= 2 and words[0].lower() == words[-1].lower()


def contains_alliteration(text: str, min_words: int = 3) -> bool:
    """`min_words` or more CONSECUTIVE words start with the same letter -
    Sally Sells Seashells energy."""
    words = _words(text)
    streak = best = 1
    for prev, curr in zip(words, words[1:]):
        if prev[:1].lower() == curr[:1].lower():
            streak += 1
            best = max(best, streak)
        else:
            streak = 1
    return best >= min_words and bool(words)


def contains_doubled_word(text: str) -> bool:
    """Any word (2+ letters, so single-letter words like 'a' or 'I'
    naturally repeating don't trivially count) appears twice in a row -
    "no no", "really really" - any word at all, not one specific one
    (contrast with repeats_word, which checks a fixed word)."""
    words = _words(text)
    return any(len(a) > 1 and a.lower() == b.lower() for a, b in zip(words, words[1:]))


def contains_all_vowels(text: str) -> bool:
    """The message contains all five vowels (a, e, i, o, u) somewhere -
    doesn't have to be one word, just present across the whole thing."""
    letters = {c for c in text.lower() if c.isalpha()}
    return {"a", "e", "i", "o", "u"}.issubset(letters)


_HASHTAG_RE = re.compile(r"(?<!<)#\w+")  # negative lookbehind dodges Discord's <#channelid> mention syntax


def contains_hashtag(text: str) -> bool:
    return bool(_HASHTAG_RE.search(text))


_PARENTHETICAL_RE = re.compile(r"\([^()]+\)")


def contains_parenthetical(text: str) -> bool:
    """Message includes a parenthetical aside (like this one)."""
    return bool(_PARENTHETICAL_RE.search(text))


def contains_quotation(text: str) -> bool:
    """Message quotes something in double quotes - straight ("like
    this") or curly ("like this"). Deliberately skips single quotes,
    since those are indistinguishable from an apostrophe/contraction
    without much more work."""
    for open_q, close_q in (('"', '"'), ("\u201C", "\u201D")):
        start = text.find(open_q)
        if start == -1:
            continue
        end = text.find(close_q, start + 1)
        if end != -1 and end > start + 1:
            return True
    return False


def contains_semicolon(text: str) -> bool:
    """Message uses a semicolon - a mark almost nobody reaches for in
    casual chat without meaning to, which is exactly what makes it a good
    "not easy to blend in" task."""
    return ";" in text


def word_lengths_strictly_increasing(text: str, min_words: int = 4) -> bool:
    """`min_words` or more words in a row, each strictly longer (by
    letter count) than the one before - a real structural challenge to
    pull off without it reading as obviously deliberate."""
    words = _words(text)
    if len(words) < min_words:
        return False
    streak = best = 1
    for prev, curr in zip(words, words[1:]):
        if len(curr) > len(prev):
            streak += 1
            best = max(best, streak)
        else:
            streak = 1
    return best >= min_words


_MONTHS = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)


def contains_month(text: str) -> bool:
    return any(w.lower() in _MONTHS for w in _words(text))


_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def contains_day_of_week(text: str) -> bool:
    return any(w.lower() in _DAYS for w in _words(text))


_SEQUENTIAL_NUMBERS_RE = re.compile(r"\b(\d+)\D+(\d+)\D+(\d+)\b")


def contains_sequential_numbers(text: str, direction: str = "down") -> bool:
    """Message contains 3 numbers in a row that count up or down by
    exactly 1 each time - '3, 2, 1' / '3...2...1' (direction="down") or
    '1, 2, 3' (direction="up")."""
    for a, b, c in _SEQUENTIAL_NUMBERS_RE.findall(text):
        a, b, c = int(a), int(b), int(c)
        if direction == "down" and a - b == 1 and b - c == 1:
            return True
        if direction == "up" and b - a == 1 and c - b == 1:
            return True
    return False


def first_and_last_letter_match(text: str) -> bool:
    """The very first and very last LETTER of the message (ignoring
    punctuation/whitespace/emoji) are the same, case-insensitive."""
    letters = [c for c in text if c.isalpha()]
    return len(letters) >= 4 and letters[0].lower() == letters[-1].lower()


_TEXT_ABBREVIATIONS = (
    "lol", "omg", "brb", "idk", "tbh", "fr", "ngl", "imo", "btw", "smh", "rn", "irl", "ikr",
)


def contains_text_abbreviation(text: str) -> bool:
    return any(w.lower() in _TEXT_ABBREVIATIONS for w in _words(text))


_CONTRACTION_RE = re.compile(r"\b[A-Za-z]+'(t|s|re|ve|ll|d|m)\b", re.IGNORECASE)


def contains_contraction(text: str) -> bool:
    """Message uses a contraction - don't, can't, I've, they're, and so on."""
    return bool(_CONTRACTION_RE.search(text))


def contains_repeated_punctuation(text: str, char: str = "!", times: int = 3) -> bool:
    """The same punctuation character shows up `times` or more in a row -
    "!!!" rather than just one "!"."""
    return (char * times) in text


def contains_two_different_emoji(text: str) -> bool:
    """At least two DIFFERENT emoji - not the same one used twice."""
    found = set(_EMOJI_RE.findall(text)) | set(_CUSTOM_EMOJI_RE.findall(text))
    return len(found) >= 2


_INTERJECTIONS = (
    "yikes", "oof", "ouch", "whoa", "ugh", "argh", "phew", "yay", "woo", "huh", "hmm", "meh", "eek", "gah",
)


def contains_interjection(text: str) -> bool:
    return any(w.lower() in _INTERJECTIONS for w in _words(text))


# --------------------------------------------------------------------------
# Message-object-level primitives (need more than the raw text)
# --------------------------------------------------------------------------

def check_is_reply(message: MessageLike) -> bool:
    return message.reference is not None


def check_mentions_target(message: MessageLike, target_id: int) -> bool:
    return any(getattr(u, "id", None) == target_id for u in message.mentions)


def check_mentions_any(message: MessageLike, allowed_ids: frozenset[int]) -> bool:
    return any(getattr(u, "id", None) in allowed_ids for u in message.mentions)


# --------------------------------------------------------------------------
# Task type
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Task:
    id: str
    description: str
    check: Callable[[MessageLike], bool]
    category: str  # for testing/debugging only - never shown to players


def _text_task(task_id: str, description: str, category: str,
                fn: Callable[..., bool], **kwargs) -> Task:
    def check(message: MessageLike) -> bool:
        return fn(message.content, **kwargs)
    return Task(id=task_id, description=description, check=check, category=category)


# --------------------------------------------------------------------------
# Vocab shared across both pools on purpose - the same word can be a crime
# trigger in one game and an innocent decoy in the next.
# --------------------------------------------------------------------------

COLORS = ("red", "blue", "green", "yellow", "purple", "orange", "black", "white", "pink")
ANIMALS = ("dog", "cat", "bird", "fish", "bear", "wolf", "rabbit", "turtle", "owl")

# Vocab for the 18+ pool below - dating-app/relationship-status slang and
# "gossip" adjectives. Same idea as COLORS/ANIMALS: a shared word list used
# by a contains_any_word task on each side of the 18+ pool.
DATING_WORDS = ("crush", "ex", "soulmate", "situationship", "smitten", "single", "taken", "cuffed")
DRAMA_WORDS = ("scandal", "drama", "messy", "chaos", "juicy", "wild", "shady", "spicy")

# Sentinel ids: these don't carry a real check. When drawn, the assignment
# code (see state.py) swaps them out for a freshly-built Task via the
# factory functions below, using that round's actual participants.
MENTION_SPECIFIC_SENTINEL = "DYNAMIC_MENTION_SPECIFIC"
MENTION_ANY_SENTINEL = "DYNAMIC_MENTION_ANY"


# --------------------------------------------------------------------------
# Crime pool (the Lawbreaker's secret task)
# --------------------------------------------------------------------------

CRIME_TASKS: list[Task] = [
    _text_task("crime_word_pineapple", "Work the word **pineapple** into one of your messages.", "word", contains_word, word="pineapple"),
    _text_task("crime_word_kazoo", "Work the word **kazoo** into one of your messages.", "word", contains_word, word="kazoo"),
    _text_task("crime_word_volcano", "Work the word **volcano** into one of your messages.", "word", contains_word, word="volcano"),
    _text_task("crime_word_trombone", "Work the word **trombone** into one of your messages.", "word", contains_word, word="trombone"),
    _text_task("crime_word_flamingo", "Work the word **flamingo** into one of your messages.", "word", contains_word, word="flamingo"),
    _text_task("crime_word_pickle", "Work the word **pickle** into one of your messages.", "word", contains_word, word="pickle"),
    _text_task("crime_word_jellybean", "Work the word **jellybean** into one of your messages.", "word", contains_word, word="jellybean"),
    _text_task("crime_phrase_just_saying", "Work the phrase **\"just saying\"** into one of your messages.", "phrase", contains_phrase, phrase="just saying"),
    _text_task("crime_phrase_no_offense", "Work the phrase **\"no offense\"** into one of your messages.", "phrase", contains_phrase, phrase="no offense"),
    _text_task("crime_phrase_trust_me", "Work the phrase **\"trust me\"** into one of your messages.", "phrase", contains_phrase, phrase="trust me"),
    _text_task("crime_all_caps", "Send one message written ENTIRELY IN CAPS.", "format", is_all_caps),
    _text_task("crime_all_lowercase", "Send one message with no capital letters at all - not even the first word.", "format", all_lowercase),
    _text_task("crime_ends_question", "End one of your messages with a question mark.", "punctuation", ends_with_question),
    _text_task("crime_ends_exclaim", "End one of your messages with an exclamation point.", "punctuation", ends_with_exclamation),
    _text_task("crime_ellipsis", "Work a \"...\" into one of your messages.", "punctuation", contains_ellipsis),
    _text_task("crime_starts_honestly", "Start a message with the word **honestly**.", "structure", starts_with_word, word="honestly"),
    _text_task("crime_ends_though", "End a message with the word **though**.", "structure", ends_with_word, word="though"),
    _text_task("crime_repeat_literally", "Use the word **literally** twice in the same message.", "structure", repeats_word, word="literally", times=2),
    _text_task("crime_no_w", "Send a message of at least 10 letters that never uses the letter **W**.", "constraint", missing_letter, letter="w", min_letters=10),
    _text_task("crime_link", "Share any link (a URL) in the channel.", "content", contains_link),
    _text_task("crime_number", "Work any number into one of your messages.", "content", contains_number),
    _text_task("crime_wordcount_7", "Send a message that's exactly 7 words long.", "structure", word_count_exact, n=7),
    _text_task("crime_wordcount_long", "Send a message that's at least 20 words long.", "structure", word_count_min, n=20),
    _text_task("crime_wordcount_short", "Send a message that's 3 words or fewer.", "structure", word_count_max, n=3),
    _text_task("crime_emoji_any", "Use any emoji in one of your messages.", "content", has_emoji),
    _text_task("crime_emoji_pineapple", "Use the \U0001F34D emoji in one of your messages.", "content", has_specific_emoji, emoji="\U0001F34D"),
    Task("crime_reply", "Reply directly to any message this round (use Discord's reply feature).", check_is_reply, "structure"),
    _text_task("crime_color", "Work any color into one of your messages.", "word", contains_any_word, words=COLORS),
    # New vocabulary, added alongside the original set for more variety.
    _text_task("crime_word_spaghetti", "Work the word **spaghetti** into one of your messages.", "word", contains_word, word="spaghetti"),
    _text_task("crime_word_raccoon", "Work the word **raccoon** into one of your messages.", "word", contains_word, word="raccoon"),
    _text_task("crime_word_wizard", "Work the word **wizard** into one of your messages.", "word", contains_word, word="wizard"),
    _text_task("crime_word_banana", "Work the word **banana** into one of your messages.", "word", contains_word, word="banana"),
    _text_task("crime_word_narwhal", "Work the word **narwhal** into one of your messages.", "word", contains_word, word="narwhal"),
    _text_task("crime_word_cupcake", "Work the word **cupcake** into one of your messages.", "word", contains_word, word="cupcake"),
    _text_task("crime_word_tornado", "Work the word **tornado** into one of your messages.", "word", contains_word, word="tornado"),
    _text_task("crime_word_gremlin", "Work the word **gremlin** into one of your messages.", "word", contains_word, word="gremlin"),
    _text_task("crime_word_kraken", "Work the word **kraken** into one of your messages.", "word", contains_word, word="kraken"),
    _text_task("crime_word_sasquatch", "Work the word **sasquatch** into one of your messages.", "word", contains_word, word="sasquatch"),
    _text_task("crime_phrase_not_gonna_lie", "Work the phrase **\"not gonna lie\"** into one of your messages.", "phrase", contains_phrase, phrase="not gonna lie"),
    _text_task("crime_phrase_hear_me_out", "Work the phrase **\"hear me out\"** into one of your messages.", "phrase", contains_phrase, phrase="hear me out"),
    _text_task("crime_phrase_plot_twist", "Work the phrase **\"plot twist\"** into one of your messages.", "phrase", contains_phrase, phrase="plot twist"),
    _text_task("crime_phrase_between_us", "Work the phrase **\"between us\"** into one of your messages.", "phrase", contains_phrase, phrase="between us"),
    _text_task("crime_phrase_off_the_record", "Work the phrase **\"off the record\"** into one of your messages.", "phrase", contains_phrase, phrase="off the record"),
    _text_task("crime_phrase_mark_my_words", "Work the phrase **\"mark my words\"** into one of your messages.", "phrase", contains_phrase, phrase="mark my words"),
    # New validator shapes, not just new words - these lean harder into
    # "hard to pull off without it reading as deliberate."
    _text_task("crime_ordinal", "Work an ordinal into a message - \"1st\", \"3rd\", or spelled out like \"first\".", "word", contains_ordinal),
    _text_task("crime_bookend", "Start AND end the same message with the same word.", "structure", starts_and_ends_with_same_word),
    _text_task("crime_alliteration", "Send 3 words in a row that all start with the same letter.", "structure", contains_alliteration),
    _text_task("crime_doubled_word", "Say any word twice in a row, back to back - \"no no\", \"really really\", your call.", "structure", contains_doubled_word),
    _text_task("crime_all_vowels", "Send a message that uses every vowel - A, E, I, O, and U - somewhere in it.", "constraint", contains_all_vowels),
    _text_task("crime_hashtag", "Use a #hashtag in one of your messages.", "format", contains_hashtag),
    _text_task("crime_parenthetical", "Add a parenthetical aside (like this) to one of your messages.", "format", contains_parenthetical),
    _text_task("crime_quotation", "\"Quote\" something in one of your messages, in actual quotation marks.", "format", contains_quotation),
    _text_task("crime_semicolon", "Work a semicolon into one of your messages; yes, really.", "punctuation", contains_semicolon),
    _text_task("crime_increasing_lengths", "Send 4 words in a row that each get longer than the last.", "structure", word_lengths_strictly_increasing),
    _text_task("crime_month", "Mention any month of the year.", "word", contains_month),
    _text_task("crime_day", "Mention any day of the week.", "word", contains_day_of_week),
    _text_task("crime_countdown", "Count down by ones somewhere in a message - \"3, 2, 1\" or similar.", "content", contains_sequential_numbers, direction="down"),
    _text_task("crime_countup", "Count up by ones somewhere in a message - \"1, 2, 3\" or similar.", "content", contains_sequential_numbers, direction="up"),
    _text_task("crime_bookend_letter", "Start and end the whole message with the same letter.", "constraint", first_and_last_letter_match),
    _text_task("crime_abbreviation", "Use a text abbreviation like lol, omg, or tbh.", "word", contains_text_abbreviation),
    _text_task("crime_contraction", "Use a contraction - don't, can't, I've, whatever fits.", "word", contains_contraction),
    _text_task("crime_repeated_punct", "End a message with three exclamation points in a row - like this!!!", "punctuation", contains_repeated_punctuation),
    _text_task("crime_two_emoji", "Use two different emoji in the same message.", "content", contains_two_different_emoji),
    _text_task("crime_interjection", "React with an interjection - yikes, whoa, ugh, your pick.", "word", contains_interjection),
    Task(MENTION_SPECIFIC_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
    Task(MENTION_SPECIFIC_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
]


# --------------------------------------------------------------------------
# Innocent pool (decoys). Several entries share a validator family with a
# Crime entry above on purpose - see module docstring.
# --------------------------------------------------------------------------

INNOCENT_TASKS: list[Task] = [
    _text_task("innocent_word_umbrella", "Work the word **umbrella** into one of your messages.", "word", contains_word, word="umbrella"),
    _text_task("innocent_word_waffle", "Work the word **waffle** into one of your messages.", "word", contains_word, word="waffle"),
    _text_task("innocent_word_banjo", "Work the word **banjo** into one of your messages.", "word", contains_word, word="banjo"),
    _text_task("innocent_word_otter", "Work the word **otter** into one of your messages.", "word", contains_word, word="otter"),
    _text_task("innocent_word_pineapple", "Work the word **pineapple** into one of your messages.", "word", contains_word, word="pineapple"),
    _text_task("innocent_word_flamingo", "Work the word **flamingo** into one of your messages.", "word", contains_word, word="flamingo"),
    _text_task("innocent_word_jellybean", "Work the word **jellybean** into one of your messages.", "word", contains_word, word="jellybean"),
    _text_task("innocent_phrase_my_bad", "Work the phrase **\"my bad\"** into one of your messages.", "phrase", contains_phrase, phrase="my bad"),
    _text_task("innocent_phrase_for_real", "Work the phrase **\"for real\"** into one of your messages.", "phrase", contains_phrase, phrase="for real"),
    _text_task("innocent_phrase_low_key", "Work the phrase **\"low key\"** into one of your messages.", "phrase", contains_phrase, phrase="low key"),
    _text_task("innocent_one_caps_word", "Capitalize exactly ONE word in a message, for emphasis.", "format", has_exactly_one_caps_word),
    _text_task("innocent_all_lowercase", "Send one message with no capital letters at all - not even the first word.", "format", all_lowercase),
    _text_task("innocent_ends_question", "End one of your messages with a question mark.", "punctuation", ends_with_question),
    _text_task("innocent_ends_exclaim", "End one of your messages with an exclamation point.", "punctuation", ends_with_exclamation),
    _text_task("innocent_ellipsis", "Work a \"...\" into one of your messages.", "punctuation", contains_ellipsis),
    _text_task("innocent_starts_actually", "Start a message with the word **actually**.", "structure", starts_with_word, word="actually"),
    _text_task("innocent_ends_right", "End a message with the word **right**.", "structure", ends_with_word, word="right"),
    _text_task("innocent_repeat_kindof", "Use the phrase **kind of** twice in the same message.", "structure", repeats_word, word="kind", times=2),
    _text_task("innocent_no_b", "Send a message of at least 10 letters that never uses the letter **B**.", "constraint", missing_letter, letter="b", min_letters=10),
    _text_task("innocent_link", "Share any link (a URL) in the channel.", "content", contains_link),
    _text_task("innocent_number", "Work any number into one of your messages.", "content", contains_number),
    _text_task("innocent_wordcount_4", "Send a message that's exactly 4 words long.", "structure", word_count_exact, n=4),
    _text_task("innocent_wordcount_long", "Send a message that's at least 12 words long.", "structure", word_count_min, n=12),
    _text_task("innocent_wordcount_short", "Send a message that's 2 words or fewer.", "structure", word_count_max, n=2),
    _text_task("innocent_emoji_any", "Use any emoji in one of your messages.", "content", has_emoji),
    _text_task("innocent_emoji_party", "Use the \U0001F389 emoji in one of your messages.", "content", has_specific_emoji, emoji="\U0001F389"),
    Task("innocent_reply", "Reply directly to any message this round (use Discord's reply feature).", check_is_reply, "structure"),
    _text_task("innocent_animal", "Work any animal into one of your messages.", "word", contains_any_word, words=ANIMALS),
    # New vocabulary - "wizard" and "banana" are deliberately the same
    # words as two of the crime pool's new ones, same camouflage idea as
    # pineapple/flamingo/jellybean above.
    _text_task("innocent_word_wizard", "Work the word **wizard** into one of your messages.", "word", contains_word, word="wizard"),
    _text_task("innocent_word_banana", "Work the word **banana** into one of your messages.", "word", contains_word, word="banana"),
    _text_task("innocent_word_dinosaur", "Work the word **dinosaur** into one of your messages.", "word", contains_word, word="dinosaur"),
    _text_task("innocent_word_hamster", "Work the word **hamster** into one of your messages.", "word", contains_word, word="hamster"),
    _text_task("innocent_word_marshmallow", "Work the word **marshmallow** into one of your messages.", "word", contains_word, word="marshmallow"),
    _text_task("innocent_word_tumbleweed", "Work the word **tumbleweed** into one of your messages.", "word", contains_word, word="tumbleweed"),
    _text_task("innocent_word_accordion", "Work the word **accordion** into one of your messages.", "word", contains_word, word="accordion"),
    _text_task("innocent_word_mustache", "Work the word **mustache** into one of your messages.", "word", contains_word, word="mustache"),
    _text_task("innocent_word_disco", "Work the word **disco** into one of your messages.", "word", contains_word, word="disco"),
    _text_task("innocent_word_unicorn", "Work the word **unicorn** into one of your messages.", "word", contains_word, word="unicorn"),
    _text_task("innocent_phrase_call_it_a_hunch", "Work the phrase **\"call it a hunch\"** into one of your messages.", "phrase", contains_phrase, phrase="call it a hunch"),
    _text_task("innocent_phrase_two_cents", "Work the phrase **\"just my two cents\"** into one of your messages.", "phrase", contains_phrase, phrase="just my two cents"),
    _text_task("innocent_phrase_end_of_the_day", "Work the phrase **\"at the end of the day\"** into one of your messages.", "phrase", contains_phrase, phrase="at the end of the day"),
    _text_task("innocent_phrase_read_the_room", "Work the phrase **\"read the room\"** into one of your messages.", "phrase", contains_phrase, phrase="read the room"),
    _text_task("innocent_phrase_big_if_true", "Work the phrase **\"big if true\"** into one of your messages.", "phrase", contains_phrase, phrase="big if true"),
    _text_task("innocent_phrase_long_story_short", "Work the phrase **\"long story short\"** into one of your messages.", "phrase", contains_phrase, phrase="long story short"),
    # Same new validator shapes as the crime pool, for the same reason
    # format/punctuation/structure entries are shared above: the check
    # itself shouldn't give away which side of the round it came from.
    _text_task("innocent_ordinal", "Work an ordinal into a message - \"1st\", \"3rd\", or spelled out like \"first\".", "word", contains_ordinal),
    _text_task("innocent_bookend", "Start AND end the same message with the same word.", "structure", starts_and_ends_with_same_word),
    _text_task("innocent_alliteration", "Send 3 words in a row that all start with the same letter.", "structure", contains_alliteration),
    _text_task("innocent_doubled_word", "Say any word twice in a row, back to back - \"no no\", \"really really\", your call.", "structure", contains_doubled_word),
    _text_task("innocent_all_vowels", "Send a message that uses every vowel - A, E, I, O, and U - somewhere in it.", "constraint", contains_all_vowels),
    _text_task("innocent_hashtag", "Use a #hashtag in one of your messages.", "format", contains_hashtag),
    _text_task("innocent_parenthetical", "Add a parenthetical aside (like this) to one of your messages.", "format", contains_parenthetical),
    _text_task("innocent_quotation", "\"Quote\" something in one of your messages, in actual quotation marks.", "format", contains_quotation),
    _text_task("innocent_semicolon", "Work a semicolon into one of your messages; yes, really.", "punctuation", contains_semicolon),
    _text_task("innocent_increasing_lengths", "Send 4 words in a row that each get longer than the last.", "structure", word_lengths_strictly_increasing),
    _text_task("innocent_month", "Mention any month of the year.", "word", contains_month),
    _text_task("innocent_day", "Mention any day of the week.", "word", contains_day_of_week),
    _text_task("innocent_countdown", "Count down by ones somewhere in a message - \"3, 2, 1\" or similar.", "content", contains_sequential_numbers, direction="down"),
    _text_task("innocent_countup", "Count up by ones somewhere in a message - \"1, 2, 3\" or similar.", "content", contains_sequential_numbers, direction="up"),
    _text_task("innocent_bookend_letter", "Start and end the whole message with the same letter.", "constraint", first_and_last_letter_match),
    _text_task("innocent_abbreviation", "Use a text abbreviation like lol, omg, or tbh.", "word", contains_text_abbreviation),
    _text_task("innocent_contraction", "Use a contraction - don't, can't, I've, whatever fits.", "word", contains_contraction),
    _text_task("innocent_repeated_punct", "End a message with three exclamation points in a row - like this!!!", "punctuation", contains_repeated_punctuation),
    _text_task("innocent_two_emoji", "Use two different emoji in the same message.", "content", contains_two_different_emoji),
    _text_task("innocent_interjection", "React with an interjection - yikes, whoa, ugh, your pick.", "word", contains_interjection),
    Task(MENTION_ANY_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
    Task(MENTION_ANY_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
]


# --------------------------------------------------------------------------
# 18+ pools - opt-in via /config content:18+ (or content:mixed, which draws
# from both). "18+" here means adult-party-game energy: embarrassing
# confessions, dating-app drama, corny flirting - the same vibe as games
# like Truth or Drink or the tamer end of Cards Against Humanity. Nothing
# explicit, no real names/targets required, nothing anyone couldn't say out
# loud at a party. Same validators, same camouflage principle as the SFW
# pool above (see module docstring) - a few exact trigger words
# ("crush"/"ex"/"midnight kiss") are shared verbatim across both 18+ pools
# on purpose, same as "pineapple"/"flamingo"/"jellybean" are above.
# --------------------------------------------------------------------------

CRIME_TASKS_18PLUS: list[Task] = [
    _text_task("crime18_word_crush", "Casually admit you have a crush on someone in the chat right now - don't say who.", "word", contains_word, word="crush"),
    _text_task("crime18_word_ex", "Bring up your ex with zero context and move on like you didn't.", "word", contains_word, word="ex"),
    _text_task("crime18_phrase_midnight_kiss", "Bring up a **midnight kiss** story from any New Year's Eve.", "phrase", contains_phrase, phrase="midnight kiss"),
    _text_task("crime18_word_soulmate", "Call something - or someone - your **soulmate**, completely straight-faced.", "word", contains_word, word="soulmate"),
    _text_task("crime18_word_smitten", "Describe yourself as **smitten** over something totally mundane.", "word", contains_word, word="smitten"),
    _text_task("crime18_word_vegas", "Say **\"what happens in Vegas...\"** and just trail off.", "word", contains_word, word="vegas"),
    _text_task("crime18_phrase_no_comment", "Respond to something with **\"no comment\"**, said a little too suspiciously.", "phrase", contains_phrase, phrase="no comment"),
    _text_task("crime18_word_complicated", "Describe your love life as **complicated**. No further details.", "word", contains_word, word="complicated"),
    _text_task("crime18_phrase_long_story", "Call something a **\"long story\"** and then absolutely do not tell it.", "phrase", contains_phrase, phrase="long story"),
    _text_task("crime18_phrase_walk_of_shame", "Reference a **\"walk of shame\"** with zero further explanation.", "phrase", contains_phrase, phrase="walk of shame"),
    _text_task("crime18_phrase_red_flag", "Casually call something a **\"red flag\"** - judging-panel voice optional.", "phrase", contains_phrase, phrase="red flag"),
    _text_task("crime18_phrase_worst_date", "Bring up your **\"worst date ever\"** without saying what actually happened.", "phrase", contains_phrase, phrase="worst date"),
    _text_task("crime18_phrase_swipe_right", "Mention swiping right on someone, real or hypothetical.", "phrase", contains_phrase, phrase="swipe right"),
    _text_task("crime18_drama_word", "Describe your week using one of: scandal, drama, messy, chaos, juicy, wild, shady, spicy.", "word", contains_any_word, words=DRAMA_WORDS),
    _text_task("crime18_all_caps", "Announce something about your love life IN ALL CAPS like it's breaking news.", "format", is_all_caps),
    _text_task("crime18_all_lowercase", "Confess something a little embarrassing in all lowercase, like you're hoping nobody notices.", "format", all_lowercase),
    _text_task("crime18_ends_question", "Ask someone a suspiciously personal question.", "punctuation", ends_with_question),
    _text_task("crime18_ends_exclaim", "React to some juicy gossip (real or invented) with way too much excitement!", "punctuation", ends_with_exclamation),
    _text_task("crime18_ellipsis", "Trail off mid-confession with a suspicious \"...\"", "punctuation", contains_ellipsis),
    _text_task("crime18_starts_honestly", "Start a message with **honestly** right before you overshare.", "structure", starts_with_word, word="honestly"),
    _text_task("crime18_starts_ngl", "Start a message with **\"ngl\"** right before a confession.", "structure", starts_with_word, word="ngl"),
    _text_task("crime18_ends_though", "End a message with **though** right after admitting something questionable.", "structure", ends_with_word, word="though"),
    _text_task("crime18_repeat_no", "Deny something twice in the same message (\"no, no...\").", "structure", repeats_word, word="no", times=2),
    _text_task("crime18_no_e", "Confess something without using the letter **E** - it'll come out extra awkward. (12+ letters)", "constraint", missing_letter, letter="e", min_letters=12),
    _text_task("crime18_link", "Send a \"source\" link that definitely does not prove your point.", "content", contains_link),
    _text_task("crime18_number", "Casually drop a suspiciously specific number - exes, dates, whatever you want people to wonder about.", "content", contains_number),
    _text_task("crime18_wordcount_5", "Confess something in exactly 5 words.", "structure", word_count_exact, n=5),
    _text_task("crime18_wordcount_long", "Overshare for at least 15 words straight.", "structure", word_count_min, n=15),
    _text_task("crime18_wordcount_short", "Answer \"any regrets?\" in 3 words or fewer.", "structure", word_count_max, n=3),
    _text_task("crime18_emoji_smirk", "Use \U0001F60F in a message like you're hiding something.", "content", has_specific_emoji, emoji="\U0001F60F"),
    Task("crime18_reply", "Reply directly to someone's message this round like you're calling them out.", check_is_reply, "structure"),
    # More vocabulary in the same confession/dating-drama register.
    _text_task("crime18_word_chemistry", "Use the word **chemistry** about someone (or something), completely unprompted.", "word", contains_word, word="chemistry"),
    _text_task("crime18_word_spark", "Say there's a **spark**, no further explanation.", "word", contains_word, word="spark"),
    _text_task("crime18_word_heartbreaker", "Call someone a **heartbreaker**, deadpan.", "word", contains_word, word="heartbreaker"),
    _text_task("crime18_word_keeper", "Call someone (or something) **a keeper**.", "word", contains_word, word="keeper"),
    _text_task("crime18_word_catch", "Call someone **a catch**, completely straight-faced.", "word", contains_word, word="catch"),
    _text_task("crime18_word_tension", "Casually mention some **tension** without explaining whose.", "word", contains_word, word="tension"),
    _text_task("crime18_word_magnetic", "Describe someone as **magnetic**, no further comment.", "word", contains_word, word="magnetic"),
    _text_task("crime18_word_infatuated", "Admit to being **infatuated** with something completely mundane.", "word", contains_word, word="infatuated"),
    _text_task("crime18_phrase_yellow_flag", "Call something a **\"yellow flag\"** - not quite a dealbreaker, just noted.", "phrase", contains_phrase, phrase="yellow flag"),
    _text_task("crime18_phrase_friend_zone", "Mention the **\"friend zone\"** with zero elaboration.", "phrase", contains_phrase, phrase="friend zone"),
    _text_task("crime18_phrase_third_date", "Reference a **\"third date\"** rule of some kind, made up or not.", "phrase", contains_phrase, phrase="third date"),
    _text_task("crime18_phrase_double_text", "Admit to a **\"double text\"**, no context needed.", "phrase", contains_phrase, phrase="double text"),
    _text_task("crime18_phrase_left_on_read", "Mention getting **\"left on read\"**, real or hypothetical.", "phrase", contains_phrase, phrase="left on read"),
    _text_task("crime18_phrase_hard_pass", "Call something a **\"hard pass\"**, judgmental tone optional.", "phrase", contains_phrase, phrase="hard pass"),
    # Same new validator shapes as the SFW pool, reused with spicier
    # wrapper text - the check itself is identical, only the framing
    # changes, same design as everything else in this pool.
    _text_task("crime18_ordinal", "Mention which date number this would be - \"1st\", \"3rd\", whatever fits the story.", "word", contains_ordinal),
    _text_task("crime18_bookend", "Start and end the same message with the same word - bonus points if it's someone's name.", "structure", starts_and_ends_with_same_word),
    _text_task("crime18_alliteration", "Send 3 words in a row that all start with the same letter, soap-opera-narrator voice optional.", "structure", contains_alliteration),
    _text_task("crime18_doubled_word", "Say a word twice in a row like you're trying to convince yourself - \"fine fine\", \"sure sure\".", "structure", contains_doubled_word),
    _text_task("crime18_all_vowels", "Sneak all five vowels - A, E, I, O, U - into one message about your love life.", "constraint", contains_all_vowels),
    _text_task("crime18_hashtag", "Turn your love life into a #hashtag.", "format", contains_hashtag),
    _text_task("crime18_parenthetical", "Add a parenthetical confession (like this one) to a message.", "format", contains_parenthetical),
    _text_task("crime18_quotation", "\"Quote\" something someone allegedly said about your love life.", "format", contains_quotation),
    _text_task("crime18_semicolon", "Work a semicolon into a message about your love life; make it dramatic.", "punctuation", contains_semicolon),
    _text_task("crime18_increasing_lengths", "Send 4 words in a row that each get longer, building up to a confession.", "structure", word_lengths_strictly_increasing),
    _text_task("crime18_month", "Bring up a month that means something to your love life.", "word", contains_month),
    _text_task("crime18_day", "Mention a day of the week like it's loaded with meaning.", "word", contains_day_of_week),
    _text_task("crime18_countdown", "Count down (\"3, 2, 1\") like you're bracing yourself for a text back.", "content", contains_sequential_numbers, direction="down"),
    _text_task("crime18_bookend_letter", "Start and end a message with the same letter, like it was fated.", "constraint", first_and_last_letter_match),
    _text_task("crime18_abbreviation", "Use a text abbreviation - lol, omg, tbh - about something juicy.", "word", contains_text_abbreviation),
    _text_task("crime18_repeated_punct", "React to some gossip with three exclamation points - like this!!!", "punctuation", contains_repeated_punctuation),
    _text_task("crime18_two_emoji", "Use two different emoji reacting to your own love life.", "content", contains_two_different_emoji),
    Task(MENTION_SPECIFIC_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
    Task(MENTION_SPECIFIC_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
]


INNOCENT_TASKS_18PLUS: list[Task] = [
    _text_task("innocent18_word_crush", "Casually admit you have a crush on someone in the chat right now - don't say who.", "word", contains_word, word="crush"),
    _text_task("innocent18_word_ex", "Bring up your ex with zero context and move on like you didn't.", "word", contains_word, word="ex"),
    _text_task("innocent18_phrase_midnight_kiss", "Bring up a **midnight kiss** story from any New Year's Eve.", "phrase", contains_phrase, phrase="midnight kiss"),
    _text_task("innocent18_word_flirt", "Use the word **flirt** like it's just a normal Tuesday.", "word", contains_word, word="flirt"),
    _text_task("innocent18_word_single", "Announce you're **single**, whether or not it's true.", "word", contains_word, word="single"),
    _text_task("innocent18_word_taken", "Mention being **taken**, zero elaboration.", "word", contains_word, word="taken"),
    _text_task("innocent18_word_cuffed", "Use the word **cuffed** (as in cuffing season), totally unprompted.", "word", contains_word, word="cuffed"),
    _text_task("innocent18_phrase_green_flag", "Call something a **\"green flag\"** - dating-show-judge voice encouraged.", "phrase", contains_phrase, phrase="green flag"),
    _text_task("innocent18_phrase_my_type", "Describe something as **\"my type\"** - doesn't have to make sense.", "phrase", contains_phrase, phrase="my type"),
    _text_task("innocent18_phrase_dating_app", "Mention a **dating app** with no further context.", "phrase", contains_phrase, phrase="dating app"),
    _text_task("innocent18_phrase_hard_launch", "Use the phrase **\"hard launch\"** about literally anything.", "phrase", contains_phrase, phrase="hard launch"),
    _text_task("innocent18_phrase_soft_launch", "Use the phrase **\"soft launch\"** about literally anything.", "phrase", contains_phrase, phrase="soft launch"),
    _text_task("innocent18_dating_word", "Work one of these into a message: crush, ex, soulmate, situationship, smitten, single, taken, cuffed.", "word", contains_any_word, words=DATING_WORDS),
    _text_task("innocent18_one_caps_word", "Capitalize exactly ONE word for maximum drama.", "format", has_exactly_one_caps_word),
    _text_task("innocent18_all_caps", "Announce something about your love life IN ALL CAPS like it's breaking news.", "format", is_all_caps),
    _text_task("innocent18_all_lowercase", "Confess something a little embarrassing in all lowercase, like you're hoping nobody notices.", "format", all_lowercase),
    _text_task("innocent18_ends_question", "Ask someone a suspiciously personal question.", "punctuation", ends_with_question),
    _text_task("innocent18_ends_exclaim", "React to some juicy gossip (real or invented) with way too much excitement!", "punctuation", ends_with_exclamation),
    _text_task("innocent18_ellipsis", "Trail off mid-confession with a suspicious \"...\"", "punctuation", contains_ellipsis),
    _text_task("innocent18_starts_actually", "Start a message with **actually** right before you overshare.", "structure", starts_with_word, word="actually"),
    _text_task("innocent18_ends_right", "End a message with **right** after saying something questionable, like you need the validation.", "structure", ends_with_word, word="right"),
    _text_task("innocent18_repeat_kinda", "Say **\"kinda\"** twice in the same message, like you're hedging on a confession.", "structure", repeats_word, word="kinda", times=2),
    _text_task("innocent18_no_i", "Confess something without using the letter **I** - awkward, but do it anyway. (12+ letters)", "constraint", missing_letter, letter="i", min_letters=12),
    _text_task("innocent18_link", "Send a \"source\" link that definitely does not prove your point.", "content", contains_link),
    _text_task("innocent18_number", "Casually drop a suspiciously specific number - exes, dates, whatever you want people to wonder about.", "content", contains_number),
    _text_task("innocent18_wordcount_4", "Confess something in exactly 4 words.", "structure", word_count_exact, n=4),
    _text_task("innocent18_wordcount_long", "Overshare for at least 12 words straight.", "structure", word_count_min, n=12),
    _text_task("innocent18_wordcount_short", "Answer \"any regrets?\" in 2 words or fewer.", "structure", word_count_max, n=2),
    _text_task("innocent18_emoji_eyes", "Use \U0001F440 in a message like you just saw something.", "content", has_specific_emoji, emoji="\U0001F440"),
    Task("innocent18_reply", "Reply directly to someone's message this round like you're calling them out.", check_is_reply, "structure"),
    # "chemistry" and "spark" are the same two words as the crime18 pool -
    # same camouflage idea as crush/ex/midnight kiss above.
    _text_task("innocent18_word_chemistry", "Use the word **chemistry** about someone (or something), completely unprompted.", "word", contains_word, word="chemistry"),
    _text_task("innocent18_word_spark", "Say there's a **spark**, no further explanation.", "word", contains_word, word="spark"),
    _text_task("innocent18_word_butterflies", "Mention **butterflies** - the nervous kind, not the bug kind.", "word", contains_word, word="butterflies"),
    _text_task("innocent18_word_obsessed", "Declare yourself **obsessed** with something completely mundane.", "word", contains_word, word="obsessed"),
    _text_task("innocent18_word_yearning", "Use the word **yearning** like it's a normal Tuesday feeling.", "word", contains_word, word="yearning"),
    _text_task("innocent18_word_starstruck", "Describe yourself as **starstruck** over something ordinary.", "word", contains_word, word="starstruck"),
    _text_task("innocent18_word_lovestruck", "Use the word **lovestruck** about literally anything.", "word", contains_word, word="lovestruck"),
    _text_task("innocent18_word_pining", "Admit to **pining** over something trivial.", "word", contains_word, word="pining"),
    _text_task("innocent18_phrase_text_back", "Casually mention waiting on a **\"text back\"**.", "phrase", contains_phrase, phrase="text back"),
    _text_task("innocent18_phrase_seeing_someone", "Say you're **\"seeing someone\"**, true or not.", "phrase", contains_phrase, phrase="seeing someone"),
    _text_task("innocent18_phrase_keeping_options_open", "Say you're **\"keeping your options open\"**.", "phrase", contains_phrase, phrase="keeping your options open"),
    _text_task("innocent18_phrase_catching_feelings", "Admit to **\"catching feelings\"**, zero elaboration.", "phrase", contains_phrase, phrase="catching feelings"),
    _text_task("innocent18_phrase_moving_too_fast", "Say something is **\"moving too fast\"**, context optional.", "phrase", contains_phrase, phrase="moving too fast"),
    _text_task("innocent18_phrase_not_looking", "Say you're **\"not looking for anything serious\"** right now.", "phrase", contains_phrase, phrase="not looking for anything serious"),
    _text_task("innocent18_ordinal", "Mention which date number this would be - \"1st\", \"3rd\", whatever fits the story.", "word", contains_ordinal),
    _text_task("innocent18_bookend", "Start and end the same message with the same word - bonus points if it's someone's name.", "structure", starts_and_ends_with_same_word),
    _text_task("innocent18_alliteration", "Send 3 words in a row that all start with the same letter, soap-opera-narrator voice optional.", "structure", contains_alliteration),
    _text_task("innocent18_doubled_word", "Say a word twice in a row like you're trying to convince yourself - \"fine fine\", \"sure sure\".", "structure", contains_doubled_word),
    _text_task("innocent18_all_vowels", "Sneak all five vowels - A, E, I, O, U - into one message about your love life.", "constraint", contains_all_vowels),
    _text_task("innocent18_hashtag", "Turn your love life into a #hashtag.", "format", contains_hashtag),
    _text_task("innocent18_parenthetical", "Add a parenthetical confession (like this one) to a message.", "format", contains_parenthetical),
    _text_task("innocent18_quotation", "\"Quote\" something someone allegedly said about your love life.", "format", contains_quotation),
    _text_task("innocent18_semicolon", "Work a semicolon into a message about your love life; make it dramatic.", "punctuation", contains_semicolon),
    _text_task("innocent18_increasing_lengths", "Send 4 words in a row that each get longer, building up to a confession.", "structure", word_lengths_strictly_increasing),
    _text_task("innocent18_month", "Bring up a month that means something to your love life.", "word", contains_month),
    _text_task("innocent18_day", "Mention a day of the week like it's loaded with meaning.", "word", contains_day_of_week),
    _text_task("innocent18_countup", "Count up (\"1, 2, 3\") like you're building the courage to hit send.", "content", contains_sequential_numbers, direction="up"),
    _text_task("innocent18_bookend_letter", "Start and end a message with the same letter, like it was fated.", "constraint", first_and_last_letter_match),
    _text_task("innocent18_contraction", "Use a contraction while being cagey about your love life.", "word", contains_contraction),
    _text_task("innocent18_repeated_punct", "React to some gossip with three exclamation points - like this!!!", "punctuation", contains_repeated_punctuation),
    _text_task("innocent18_two_emoji", "Use two different emoji reacting to your own love life.", "content", contains_two_different_emoji),
    Task(MENTION_ANY_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
    Task(MENTION_ANY_SENTINEL, "placeholder - replaced at assignment time", lambda m: False, "mention"),
]


# --------------------------------------------------------------------------
# Dynamic task factories - built at assignment time with real round data,
# swapped in for the sentinels above.
# --------------------------------------------------------------------------

def make_mention_specific_task(target_id: int, target_display: str) -> Task:
    task_id = f"crime_mention_{target_id}"
    description = f"Mention **{target_display}** (@ them) in one of your messages."
    return Task(task_id, description, lambda m: check_mentions_target(m, target_id), "mention")


def make_mention_any_task(allowed_ids: Iterable[int]) -> Task:
    frozen = frozenset(allowed_ids)
    return Task(
        "innocent_mention_any",
        "Mention (@ ) any other player in the round - doesn't have to be anyone specific.",
        lambda m: check_mentions_any(m, frozen),
        "mention",
    )


# --------------------------------------------------------------------------
# ShuffleBag: hands out every item once, in random order, before any item
# repeats. Refills (and reshuffles) automatically once exhausted.
# --------------------------------------------------------------------------

class ShuffleBag:
    def __init__(self, items: Sequence[Task], rng: Optional[random.Random] = None):
        if not items:
            raise ValueError("ShuffleBag needs at least one item")
        self._items: list[Task] = list(items)
        self._rng = rng or random.Random()
        self._bag: list[Task] = []

    def _refill(self) -> None:
        self._bag = self._items[:]
        self._rng.shuffle(self._bag)

    def _pop_refilling(self) -> Task:
        """pop(), refilling+reshuffling first if the bag is currently
        empty. Every draw in this class goes through this - including
        each retry inside draw_many's duplicate-skip loop below - so a
        pop can never be attempted against an empty list, no matter how
        many extra items a batch ends up consuming to dodge a duplicate."""
        if not self._bag:
            self._refill()
        return self._bag.pop()

    def draw(self) -> Task:
        """Draw one task. Refills+reshuffles automatically when empty."""
        return self._pop_refilling()

    @staticmethod
    def _dedup_key(item: Task) -> Any:
        """The value draw_many() treats as this item's "identity" for
        uniqueness purposes: a Task's .id if it has one, else the item
        itself. The fallback keeps ShuffleBag usable with plain hashable
        items (ints, strings, ...) exactly as before this method started
        caring about ids - see this module's own tests, which exercise
        both a bag of Tasks and a bag of plain ints.
        """
        return getattr(item, "id", item)

    def draw_many(self, n: int) -> list[Task]:
        """Draw n tasks, guaranteed unique **by id** within this call.

        A pool may deliberately hold two Task objects with the same id
        (e.g. a dynamic-task sentinel gets two "slots" so it's twice as
        likely to come up on any single draw() - see MENTION_ANY_SENTINEL
        in INNOCENT_TASKS). That's fine for draw(), which only ever
        returns one item at a time, but a batch is handed to multiple
        players in the *same* round, so two of them silently ending up
        with the identical id (and, after the dynamic swap, the identical
        task) would be a real bug, not just a coincidence - this method
        checks by id, not by list position, so that can't happen.

        A duplicate is skipped in favor of the next item, refilling first
        if that means running the bag empty - which can happen well before
        this batch's "natural" share of the bag runs out, since dodging
        even one duplicate consumes an extra item beyond the naive n-items
        budget. That's exactly why every pop here goes through
        _pop_refilling() rather than assuming the bag already holds enough
        for the rest of this call.
        """
        distinct_ids = len({self._dedup_key(t) for t in self._items})
        if n > distinct_ids:
            raise ValueError(
                f"Cannot draw {n} tasks with unique ids from a pool with only "
                f"{distinct_ids} distinct ids (out of {len(self._items)} items)"
            )

        drawn: list[Task] = []
        seen_ids: set[Any] = set()
        for _ in range(n):
            item = self._pop_refilling()
            while self._dedup_key(item) in seen_ids:
                item = self._pop_refilling()
            drawn.append(item)
            seen_ids.add(self._dedup_key(item))
        return drawn


# Module-level, shared across every game the bot is running - this is what
# makes "reshuffle only once exhausted" mean something across concurrent
# and back-to-back games rather than just within one round.
#
# One bag per (pool, content) combination. MIXED isn't a third pool of its
# own content - it's CRIME_TASKS + CRIME_TASKS_18PLUS shuffled together, so
# a Mixed-content round can hand out either flavor to either player,
# unpredictably, task by task.
CRIME_BAG = ShuffleBag(CRIME_TASKS)
INNOCENT_BAG = ShuffleBag(INNOCENT_TASKS)
CRIME_BAG_18PLUS = ShuffleBag(CRIME_TASKS_18PLUS)
INNOCENT_BAG_18PLUS = ShuffleBag(INNOCENT_TASKS_18PLUS)
CRIME_BAG_MIXED = ShuffleBag(CRIME_TASKS + CRIME_TASKS_18PLUS)
INNOCENT_BAG_MIXED = ShuffleBag(INNOCENT_TASKS + INNOCENT_TASKS_18PLUS)

_CRIME_BAGS: dict[TaskContent, ShuffleBag] = {
    TaskContent.SFW: CRIME_BAG,
    TaskContent.EIGHTEEN_PLUS: CRIME_BAG_18PLUS,
    TaskContent.MIXED: CRIME_BAG_MIXED,
}
_INNOCENT_BAGS: dict[TaskContent, ShuffleBag] = {
    TaskContent.SFW: INNOCENT_BAG,
    TaskContent.EIGHTEEN_PLUS: INNOCENT_BAG_18PLUS,
    TaskContent.MIXED: INNOCENT_BAG_MIXED,
}


def draw_crime_task(content: TaskContent = TaskContent.SFW) -> Task:
    """Draw the Lawbreaker's task from the given content pool (SFW by
    default, so any existing caller that doesn't pass `content` keeps
    getting exactly the v1 behavior). May come back as the mention
    sentinel - callers with access to real guild/member data should check
    the id against MENTION_SPECIFIC_SENTINEL and swap it via
    make_mention_specific_task() before showing it to anyone.
    """
    return _CRIME_BAGS[content].draw()


def draw_innocent_tasks(n: int, content: TaskContent = TaskContent.SFW) -> list[Task]:
    """Draw n Innocent (and Innocent-shaped: Detective/Snitch/Vigilante/
    Double Agent/Mimic all get their decoy task from this same pool) tasks
    from the given content pool. Entries may come back as the mention-any
    sentinel - swap via make_mention_any_task() the same way as above.
    """
    return _INNOCENT_BAGS[content].draw_many(n)
