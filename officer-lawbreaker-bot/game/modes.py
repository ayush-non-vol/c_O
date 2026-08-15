"""Mode -> role-pool logic, plus the descriptive copy shown by /modes and
/roles and used in role-DM embeds.

Design goals:
  - Classic is unchanged v1 behavior: extra_roles_for_mode(Mode.CLASSIC, n)
    always returns [], for any n. A lobby that never touches /config plays
    exactly the game this bot always played.
  - Every other mode degrades gracefully in a small lobby instead of
    requiring a bigger minimum. Picking Chaos with 3 players just quietly
    behaves closer to Classic (few or no extra roles fit) rather than
    erroring out - the "recommended for N+ players" text is guidance, not
    an enforced floor, same as the reference bot's own mode descriptions.
  - Every extra role plays like an Innocent in chat (same decoy-task draw,
    same silent on_message check) - the ability is bonus info/flavor layered
    on top in the role DM and the end-of-round recap, never something that
    changes how they're assigned or how their task is checked. That's what
    keeps a bigger role pool from needing a bigger rewrite of the round
    logic itself.
"""

from __future__ import annotations

import random
from typing import Optional

from .constants import Mode, Role

# --------------------------------------------------------------------------
# Mode -> extra role pool
# --------------------------------------------------------------------------

# Which extra roles a mode can possibly include, before the player-count
# gates and the available-slots cap below are applied. Order matters for
# CLASSIC/WILDCARD/CHAOS (first-eligible-first, so which subset of a longer
# candidate list actually gets used is deterministic for a given player
# count) - CRIMSON shuffles its list instead, which is the whole point of
# that mode: unpredictable, not tiered.
_WILDCARD_GATES: list[tuple[Role, int]] = [
    (Role.DETECTIVE, 4),
    (Role.SNITCH, 6),
]
_CHAOS_GATES: list[tuple[Role, int]] = [
    (Role.DETECTIVE, 3),
    (Role.SNITCH, 3),
    (Role.DOUBLE_AGENT, 6),
    (Role.VIGILANTE, 8),
]
_CRIMSON_BASE: list[Role] = [Role.DETECTIVE, Role.SNITCH, Role.VIGILANTE, Role.DOUBLE_AGENT]
# Deliberately 6, not 7: at 6 players there are only 4 available slots for
# a 5-role candidate pool (the 4 base roles + Mimic), so the shuffle can
# genuinely exclude any one of them, Mimic included - that's what makes
# "you won't know what's in play" true right at the threshold. Raise this
# past MAX_PLAYERS - 2 and the pool always fits without truncation, which
# would make Mimic's inclusion guaranteed (not shuffled) the moment it's
# eligible - the opposite of what this mode is for.
_CRIMSON_MIMIC_MIN_PLAYERS = 6


def detective_lead_size(n_players: int) -> int:
    """How many names go in the Detective's lead in total (the guaranteed
    Lawbreaker plus everyone else named alongside them), scaling with
    lobby size so a bigger game's lead still narrows things down
    meaningfully instead of staying a flat two names forever: 3 at 5
    players, 4 at 6, 5 at 8, 6 at 10+, following n_players // 2 + 1.

    The caller (state.py's _assign_special_role_data) is responsible for
    capping the result at n_players - 1 - the Detective can't be named in
    their own lead, so a lead can never name more distinct people than
    exist besides them.
    """
    return (n_players // 2) + 1


def extra_roles_for_mode(mode: Mode, n_players: int, rng: Optional[random.Random] = None) -> list[Role]:
    """Which extra roles (beyond the mandatory Officer + Lawbreaker) this
    lobby's mode wants to hand out, given n_players total in the lobby.

    Always a list of *distinct* Role values, always short enough to leave
    at least 0 plain Innocents (i.e. len(result) <= n_players - 2). Pass
    `rng` (a random.Random) to make Crimson's shuffle reproducible in
    tests; production code can leave it as None.
    """
    rng = rng or random.Random()
    available_slots = max(n_players - 2, 0)
    if available_slots == 0 or mode == Mode.CLASSIC:
        return []

    if mode == Mode.WILDCARD:
        candidates = [role for role, min_players in _WILDCARD_GATES if n_players >= min_players]
    elif mode == Mode.CHAOS:
        candidates = [role for role, min_players in _CHAOS_GATES if n_players >= min_players]
    elif mode == Mode.CRIMSON:
        candidates = list(_CRIMSON_BASE)
        if n_players >= _CRIMSON_MIMIC_MIN_PLAYERS:
            candidates.append(Role.MIMIC)
        rng.shuffle(candidates)
    else:  # pragma: no cover - exhaustive over the Mode enum today
        candidates = []

    return candidates[:available_slots]


# --------------------------------------------------------------------------
# Descriptive copy - /modes, /roles, and role-DM embeds all pull from here
# instead of hand-rolling their own text, so the two commands and the DMs
# can't drift out of sync with each other.
# --------------------------------------------------------------------------

MODE_EMOJI: dict[Mode, str] = {
    Mode.CLASSIC: "\U0001F600\U0001F942",   # 😀🥂
    Mode.WILDCARD: "\U0001F0CF",            # 🃏
    Mode.CHAOS: "\U0001F300",               # 🌀
    Mode.CRIMSON: "\U0001FA78",             # 🩸
}

MODE_INFO: dict[Mode, dict[str, str]] = {
    Mode.CLASSIC: {
        "blurb": "The original game - one Officer, one Lawbreaker, everyone else Innocent. Nothing extra in play.",
        "recommended": "Any size (3+ players)",
    },
    Mode.WILDCARD: {
        "blurb": "Adds a Detective (gets a lead pointing at the Lawbreaker) and, once the lobby's big enough, a Snitch (one-time tip on whether the crime's landed).",
        "recommended": "4+ players (6+ to also see the Snitch)",
    },
    Mode.CHAOS: {
        "blurb": "Detective and Snitch are in from the start. Bigger lobbies add a Double Agent secretly helping the Lawbreaker, and a Vigilante running their own private hunch.",
        "recommended": "6+ players for the full set",
    },
    Mode.CRIMSON: {
        "blurb": "The unpredictable one - a shuffled mix of Detective, Snitch, Vigilante, Double Agent, and the mysterious Mimic. Which ones actually show up (and whether the Mimic shows up at all) changes game to game.",
        "recommended": "6+ players (the more players, the more of the five that fit)",
    },
}

# (emoji, alignment marker, unlocked-by, ability blurb). Alignment markers
# mirror a common social-deduction convention: dark red = works against the
# Officer, blue = works with (or as) the Officer, white = no side of its
# own, question mark = unknown until the reveal.
ALIGNMENT_LAWBREAKER = "\U0001F53A"  # 🔺
ALIGNMENT_OFFICER = "\U0001F538"     # 🔸
ALIGNMENT_NEUTRAL = "\u2B1C"         # ⬜
ALIGNMENT_MYSTERY = "\u2753"         # ❓

ROLE_INFO: dict[Role, dict[str, str]] = {
    Role.OFFICER: {
        "emoji": "\U0001F575\uFE0F",
        "alignment": ALIGNMENT_OFFICER,
        "unlocked_by": "Core",
        "blurb": "Watches the round and gets one `/shoot` to accuse the Lawbreaker.",
    },
    Role.LAWBREAKER: {
        "emoji": "\U0001F3AD",
        "alignment": ALIGNMENT_LAWBREAKER,
        "unlocked_by": "Core",
        "blurb": "Has a secret crime to work into chat naturally without getting caught.",
    },
    Role.INNOCENT: {
        "emoji": "\U0001F9CD",
        "alignment": ALIGNMENT_NEUTRAL,
        "unlocked_by": "Core",
        "blurb": "Has a decoy task that looks exactly like the Lawbreaker's - pure camouflage, no ability of its own.",
    },
    Role.DETECTIVE: {
        "emoji": "\U0001F50E",
        "alignment": ALIGNMENT_OFFICER,
        "unlocked_by": "Wildcard+",
        "blurb": "Gets a lead at round start naming a few players - always including the Lawbreaker. Grows with the lobby (3 names at 5 players, up to 6 at 10) so it stays a genuine narrowing, not a giveaway.",
    },
    Role.SNITCH: {
        "emoji": "\U0001F400",
        "alignment": ALIGNMENT_OFFICER,
        "unlocked_by": "Wildcard+ (6+ players)",
        "blurb": "One-time `/tip` to privately check whether the Lawbreaker's crime has landed yet.",
    },
    Role.VIGILANTE: {
        "emoji": "\U0001F3AF",
        "alignment": ALIGNMENT_OFFICER,
        "unlocked_by": "Chaos+ (8+ players)",
        "blurb": "Locks in a private `/hunch` on who the Lawbreaker is - doesn't affect the round, just bragging rights when it's revealed at the end.",
    },
    Role.DOUBLE_AGENT: {
        "emoji": "\U0001F978",
        "alignment": ALIGNMENT_LAWBREAKER,
        "unlocked_by": "Chaos+ (6+ players)",
        "blurb": "Secretly knows the Lawbreaker. Completing their own decoy task also auto-completes the Lawbreaker's crime.",
    },
    Role.MIMIC: {
        "emoji": "\U0001FA9E",
        "alignment": ALIGNMENT_MYSTERY,
        "unlocked_by": "Crimson only (6+ players, not guaranteed)",
        "blurb": "Secretly rooting for one side to win. Nobody finds out which - including the Officer and Lawbreaker - until the case closes.",
    },
}

# Grouped for /roles - Core always shown, then one section per mode
# tier, each listing only the roles newly unlocked at that tier.
ROLE_SECTIONS: list[tuple[str, list[Role]]] = [
    ("Core (every mode)", [Role.OFFICER, Role.LAWBREAKER, Role.INNOCENT]),
    ("Wildcard+", [Role.DETECTIVE, Role.SNITCH]),
    ("Chaos+", [Role.VIGILANTE, Role.DOUBLE_AGENT]),
    ("Crimson only", [Role.MIMIC]),
]
