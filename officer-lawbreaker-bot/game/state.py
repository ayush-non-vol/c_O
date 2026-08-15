"""Per-channel game state and the lobby -> role/task assignment step.

One Game per channel, held by GameManager. Everything is in-memory (a
process restart wipes any game in progress) - the same tradeoff the design
doc flagged for v1: simple and correct, at the cost of durability. Fine for
a project like this; swap in SQLite later if that ever matters.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Callable, Optional

from .constants import DEFAULT_ROUND_MINUTES, Mode, Phase, Role, TaskContent
from .modes import detective_lead_size, extra_roles_for_mode
from .tasks import (
    MENTION_ANY_SENTINEL,
    MENTION_SPECIFIC_SENTINEL,
    Task,
    draw_crime_task,
    draw_innocent_tasks,
    make_mention_any_task,
    make_mention_specific_task,
)

if TYPE_CHECKING:
    import discord


@dataclass
class PlayerState:
    user_id: int
    display_name: str
    role: Optional[Role] = None
    task: Optional[Task] = None
    task_complete: bool = False
    completed_at: Optional[datetime] = None


@dataclass
class Game:
    channel_id: int
    guild_id: int
    host_id: int
    players: dict[int, PlayerState] = field(default_factory=dict)  # insertion order = join order
    phase: Phase = Phase.LOBBY
    officer_id: Optional[int] = None
    lawbreaker_id: Optional[int] = None
    round_minutes: int = DEFAULT_ROUND_MINUTES
    round_ends_at: Optional[datetime] = None
    resolved: bool = False
    timer_task: Optional[asyncio.Task] = None
    warning_task: Optional[asyncio.Task] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    lobby_message: Optional["discord.Message"] = None

    # Host-configurable via /config, lobby phase only. Defaults exactly
    # match v1 behavior for a lobby that never touches /config.
    mode: Mode = Mode.CLASSIC
    task_content: TaskContent = TaskContent.SFW

    # Set at role-assignment time, only when that mode's extra roles
    # include this one (extra_roles_for_mode) - stay None otherwise, which
    # every command handler treats as "that role isn't in this round."
    detective_id: Optional[int] = None
    detective_lead: Optional[tuple[int, ...]] = None  # order shuffled; always includes lawbreaker_id - see modes.detective_lead_size for how many names
    snitch_id: Optional[int] = None
    snitch_tip_used: bool = False
    vigilante_id: Optional[int] = None
    vigilante_guess_id: Optional[int] = None  # None until /hunch is used at least once
    double_agent_id: Optional[int] = None
    # True exactly when the Double Agent's own task completion is what
    # flipped the Lawbreaker's task_complete (as opposed to the Lawbreaker
    # completing it themselves) - see on_message's interference branch in
    # cog.py. Read by build_resolution_embed so the Lawbreaker's own line
    # says so directly, instead of only being explained in the separate
    # "Special roles" section further down the same embed.
    lawbreaker_covered_by_double_agent: bool = False
    mimic_id: Optional[int] = None
    mimic_roots_for: Optional[str] = None  # "Officer" or "Lawbreaker"


class GameManager:
    """One active game per channel."""

    def __init__(self) -> None:
        self._games: dict[int, Game] = {}

    def get(self, channel_id: int) -> Optional[Game]:
        return self._games.get(channel_id)

    def create(self, channel_id: int, guild_id: int, host_id: int, host_display: str) -> Game:
        game = Game(channel_id=channel_id, guild_id=guild_id, host_id=host_id)
        game.players[host_id] = PlayerState(user_id=host_id, display_name=host_display)
        self._games[channel_id] = game
        return game

    def remove(self, channel_id: int) -> None:
        self._games.pop(channel_id, None)


def assign_roles_and_tasks(game: Game, display_name_resolver: Callable[[int], str]) -> None:
    """Shuffle players into roles and hand out tasks, mutating `game` in
    place. Officer and Lawbreaker are always assigned first, exactly as in
    v1; which extra roles (if any) fill the remaining seats then comes from
    game.mode via extra_roles_for_mode - everyone left over is a plain
    Innocent, same as always.

    Every non-Officer player (Lawbreaker, Innocent, or any extra role) gets
    their task from the same draw mechanic and looks identical in chat -
    the extra roles are bonus info/flavor layered on top in
    _assign_special_role_data, never a different task shape. That's what
    lets a bigger role pool plug in here without changing on_message at all.

    display_name_resolver(user_id) -> str is only needed for the "mention a
    specific person" crime task, which has to show the Lawbreaker a name.
    Keeping it as an injected callback (rather than importing discord here)
    keeps this function easy to unit test with a plain lambda.
    """
    ids = list(game.players.keys())
    random.shuffle(ids)
    officer_id, lawbreaker_id, *rest_ids = ids

    game.officer_id = officer_id
    game.lawbreaker_id = lawbreaker_id
    game.players[officer_id].role = Role.OFFICER

    crime_task = draw_crime_task(game.task_content)
    if crime_task.id == MENTION_SPECIFIC_SENTINEL:
        target_id = random.choice([uid for uid in ids if uid != lawbreaker_id])
        crime_task = make_mention_specific_task(target_id, display_name_resolver(target_id))
    game.players[lawbreaker_id].role = Role.LAWBREAKER
    game.players[lawbreaker_id].task = crime_task

    extra_roles = extra_roles_for_mode(game.mode, len(ids))
    special_ids = rest_ids[: len(extra_roles)]
    innocent_ids = rest_ids[len(extra_roles):]

    all_ids = frozenset(ids)
    decoy_targets = special_ids + innocent_ids
    decoy_tasks = draw_innocent_tasks(len(decoy_targets), game.task_content) if decoy_targets else []
    for uid, task in zip(decoy_targets, decoy_tasks):
        if task.id == MENTION_ANY_SENTINEL:
            task = make_mention_any_task(all_ids - {uid})
        game.players[uid].task = task

    for uid in innocent_ids:
        game.players[uid].role = Role.INNOCENT

    for uid, role in zip(special_ids, extra_roles):
        game.players[uid].role = role
        _assign_special_role_data(game, uid, role, all_ids)


def _assign_special_role_data(game: Game, uid: int, role: Role, all_ids: frozenset[int]) -> None:
    """Fill in whatever extra bookkeeping a given extra role needs beyond
    "has this role, has this decoy task" - the lead for a Detective, the
    hidden allegiance for a Mimic, and so on. Split out from
    assign_roles_and_tasks so each role's setup is easy to find and extend.
    """
    if role == Role.DETECTIVE:
        game.detective_id = uid
        # The decoy pool is every player except the Detective and the
        # Lawbreaker - the Officer is just one more candidate in there,
        # with no special treatment, so whether the Officer ends up named
        # in the lead is purely down to the same random draw as anyone
        # else: sometimes in, sometimes not.
        decoy_pool = list(all_ids - {uid, game.lawbreaker_id})
        lead_size = min(detective_lead_size(len(all_ids)), len(all_ids) - 1)
        num_decoys = min(lead_size - 1, len(decoy_pool))
        decoys = random.sample(decoy_pool, num_decoys)
        lead = [game.lawbreaker_id, *decoys]
        random.shuffle(lead)
        game.detective_lead = tuple(lead)
    elif role == Role.SNITCH:
        game.snitch_id = uid
    elif role == Role.VIGILANTE:
        game.vigilante_id = uid
    elif role == Role.DOUBLE_AGENT:
        game.double_agent_id = uid
    elif role == Role.MIMIC:
        game.mimic_id = uid
        game.mimic_roots_for = random.choice(["Officer", "Lawbreaker"])
