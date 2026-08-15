"""Tunable constants and small enums shared across the game package.

Keeping these in one place means the numbers you're most likely to want to
tweak (player counts, round length bounds) are easy to find without digging
through game logic.
"""

from enum import Enum, auto


class Phase(Enum):
    LOBBY = auto()            # /join open, waiting for the host to /startgame
    ROLE_ASSIGNMENT = auto()  # roles/tasks being handed out (brief, DM fan-out)
    ACTIVE_ROUND = auto()     # timer running, messages being checked against tasks
    RESOLUTION = auto()       # round just ended, reveal embed being posted
    END = auto()              # terminal state; game is removed from the manager right after


class Role(Enum):
    OFFICER = "Officer"
    LAWBREAKER = "Lawbreaker"
    INNOCENT = "Innocent"

    # Extra roles, unlocked by Mode (see modes.py's extra_roles_for_mode).
    # All five behave like an Innocent in chat - same decoy-task mechanic,
    # same silent on_message check - so nothing about how they're assigned
    # or checked gives them away. The ability is *bonus* info/flavor layered
    # on top, delivered in their role DM and (partly) revealed at the end.
    DETECTIVE = "Detective"        # Wildcard+ - gets a 2-name lead, one of which is the Lawbreaker
    SNITCH = "Snitch"              # Wildcard+ - one-time /tip: has the crime landed yet?
    VIGILANTE = "Vigilante"        # Chaos+ - private /hunch guess, bragging rights only
    DOUBLE_AGENT = "Double Agent"  # Chaos+ - knows the Lawbreaker, can complete their crime for them
    MIMIC = "Mimic"                # Crimson only - secretly rooting for a side, revealed at the end


class Mode(Enum):
    """Which role set a lobby is playing with. Classic is the default and
    exactly matches v1's behavior - nothing changes for a lobby that never
    touches /config. See game/modes.py for the pool-selection logic and the
    copy shown in /modes and /roles."""
    CLASSIC = "Classic"
    WILDCARD = "Wildcard"
    CHAOS = "Chaos"
    CRIMSON = "Crimson"


class TaskContent(Enum):
    """Which task pool a lobby draws from. SFW is the default - 18+ and
    Mixed are opt-in via /config so a lobby never sees spicier content
    without the host asking for it first."""
    SFW = "SFW"
    EIGHTEEN_PLUS = "18+"
    MIXED = "Mixed"


# Lobby size. 3 is the logical floor (Officer + Lawbreaker + at least one
# Innocent - without an Innocent there's nothing for the Lawbreaker to hide
# among). 10 is a soft ceiling for v1, which runs a single Officer/Lawbreaker
# pair; past that a game gets noisy without the doc's suggested 2nd
# Officer/Lawbreaker scaling, which isn't implemented here yet. The extra
# roles unlocked by Mode share this same range - see modes.py for how each
# mode scales its role pool down gracefully for a small lobby instead of
# requiring a bigger minimum.
MIN_PLAYERS = 3
MAX_PLAYERS = 10

# Round length, in minutes. The host sets this per-game with /startgame.
ROUND_MINUTES_MIN = 2
ROUND_MINUTES_MAX = 24 * 60  # 24 hours
DEFAULT_ROUND_MINUTES = 5
