"""Session scoring: a session outlives any single Game, accumulating
per-player points across however many rounds get played in a channel
between /startsession and /endsession. One session per channel - same
shape as state.GameManager's one-game-per-channel model, just longer-
lived, and entirely independent of it (a session survives across
however many Games get created and discarded while it's open).

Scoring is deliberately individual, never team-based: a session never
rewards "your side won," only what a player personally pulled off that
round. The resolution embed already gives the team result a full
recap, so the session board exists to answer a different question -
who's actually been playing well, round after round, regardless of
which side ended up winning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .state import Game

# Point values, named rather than buried in score_round's body so a
# future host-configurable point scale just means reading these off
# Session instead of rewriting the scoring logic itself.
TASK_COMPLETE_POINTS = 1
OFFICER_CORRECT_CATCH_POINTS = 2
LAWBREAKER_EVADED_POINTS = 2
VIGILANTE_CORRECT_HUNCH_POINTS = 1
DOUBLE_AGENT_COVER_POINTS = 1
MIMIC_CORRECT_ROOT_POINTS = 1


@dataclass
class Session:
    channel_id: int
    started_by: int
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    scores: dict[int, int] = field(default_factory=dict)  # user_id -> running total; insertion order = first-seen order
    games_played: int = 0

    def add_round(self, points: dict[int, int]) -> None:
        """Fold one round's per-player points (see score_round) into the
        running totals. Called once per resolved game, right before the
        Game object is discarded in cog.py's resolve_round - a session
        never sees a Game directly, only what score_round extracted from
        it, so it has no idea what "task" or "role" even mean.
        """
        for uid, pts in points.items():
            self.scores[uid] = self.scores.get(uid, 0) + pts
        self.games_played += 1

    def standings(self) -> list[tuple[int, int]]:
        """(user_id, total points), highest first. sorted() is stable, so
        ties keep whoever's been on the board longer ahead."""
        return sorted(self.scores.items(), key=lambda row: -row[1])


class SessionManager:
    """One active session per channel, independent of GameManager - a
    session outlives any single Game."""

    def __init__(self) -> None:
        self._sessions: dict[int, Session] = {}

    def get(self, channel_id: int) -> Optional[Session]:
        return self._sessions.get(channel_id)

    def create(self, channel_id: int, started_by: int) -> Session:
        session = Session(channel_id=channel_id, started_by=started_by)
        self._sessions[channel_id] = session
        return session

    def remove(self, channel_id: int) -> None:
        self._sessions.pop(channel_id, None)


def score_round(game: Game, winner: str, shot_user_id: Optional[int]) -> dict[int, int]:
    """Individual points earned by each player in `game` this round, keyed
    by user_id. Called from resolve_round, right before the Game object
    is discarded - this is the only place round outcomes ever get read
    for scoring purposes.

    Deliberately never scores "was on the winning side" - only what a
    player personally did: finished their own task, the Officer naming
    the right person, the Lawbreaker getting away with it, a Vigilante's
    hunch landing, a Double Agent's cover holding, a Mimic's bet paying
    off. Every player in the game gets an entry, 0 included, so playing
    a round (even one you score nothing in) puts you on the board.
    """
    points: dict[int, int] = {}

    for uid, pstate in game.players.items():
        earned = 0

        if uid == game.officer_id:
            if shot_user_id == game.lawbreaker_id:
                earned += OFFICER_CORRECT_CATCH_POINTS
        elif uid == game.lawbreaker_id:
            if pstate.task_complete:
                earned += TASK_COMPLETE_POINTS
            # Only counts as evading if there was an actual (wrong) shot
            # to dodge - timing out with the crime never even finished
            # isn't really "evading" anything, just an empty round.
            if shot_user_id is not None and shot_user_id != game.lawbreaker_id:
                earned += LAWBREAKER_EVADED_POINTS
        else:
            # Innocent and every extra role share the same task-based
            # baseline, then whichever extra role had a personal call to
            # make can earn a bonus on top of it for getting it right.
            if pstate.task_complete:
                earned += TASK_COMPLETE_POINTS
            if uid == game.vigilante_id and game.vigilante_guess_id == game.lawbreaker_id:
                earned += VIGILANTE_CORRECT_HUNCH_POINTS
            if uid == game.double_agent_id and game.lawbreaker_covered_by_double_agent:
                earned += DOUBLE_AGENT_COVER_POINTS
            if uid == game.mimic_id and game.mimic_roots_for is not None and game.mimic_roots_for.lower() == winner:
                earned += MIMIC_CORRECT_ROOT_POINTS

        points[uid] = earned

    return points
