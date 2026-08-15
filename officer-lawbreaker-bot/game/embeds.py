"""Embed builders and the small visual theme they share, kept separate
from the Cog so the player-facing look-and-feel is easy to find and tweak
without wading through command-handling code.

Where useful this leans on Discord's own native dynamic timestamps
(<t:unix:R> etc.) instead of hand-rolled "live" displays - the client
renders and keeps those current for free, no polling or repeated message
edits required.
"""

from __future__ import annotations

from typing import Optional

import discord

from .constants import Mode, Role, TaskContent
from .modes import (
    ALIGNMENT_LAWBREAKER,
    ALIGNMENT_MYSTERY,
    ALIGNMENT_NEUTRAL,
    ALIGNMENT_OFFICER,
    MODE_EMOJI,
    MODE_INFO,
    ROLE_INFO,
    ROLE_SECTIONS,
)
from .scoring import Session
from .state import Game, PlayerState
from .timing import render_progress_bar


class Emoji:
    LOBBY = "\U0001F4CB"        # 📋
    OFFICER = "\U0001F575\uFE0F"  # 🕵️
    LAWBREAKER = "\U0001F3AD"   # 🎭
    INNOCENT = "\U0001F9CD"     # 🧍
    TIMER = "\u23F3"            # ⏳
    ALARM = "\u23F0"            # ⏰
    SHOOT = "\U0001F52B"        # 🔫
    SUCCESS = "\u2705"          # ✅
    FAIL = "\u274C"             # ❌
    SIREN = "\U0001F6A8"        # 🚨
    LOCKED = "\U0001F512"       # 🔒

    # Extra roles - kept in sync with modes.ROLE_INFO's emoji values so a
    # role DM and the /roles listing always show the same icon for a role.
    DETECTIVE = "\U0001F50E"     # 🔎
    SNITCH = "\U0001F400"        # 🐀
    VIGILANTE = "\U0001F3AF"     # 🎯
    DOUBLE_AGENT = "\U0001F978"  # 🥸
    MIMIC = "\U0001FA9E"         # 🪞

    SCORE = "\U0001F3C6"         # 🏆


class Theme:
    LOBBY = discord.Color.blurple()
    OFFICER = discord.Color.blue()
    LAWBREAKER = discord.Color.dark_red()
    INNOCENT = discord.Color.green()
    NEUTRAL = discord.Color.greyple()
    MYSTERY = discord.Color.purple()  # the Mimic - unknown allegiance until the reveal
    SCORE = discord.Color.gold()


FOOTER_TEXT = "Officer & Lawbreaker"

_TASK_CONTENT_EMOJI: dict[TaskContent, str] = {
    TaskContent.SFW: "\U0001F7E2",         # 🟢
    TaskContent.EIGHTEEN_PLUS: "\U0001F51E",  # 🔞
    TaskContent.MIXED: "\U0001F500",       # 🔀
}


def _task_content_label(content: TaskContent) -> str:
    return f"{_TASK_CONTENT_EMOJI[content]} {content.value}"


def build_role_embed(game: Game, pstate: PlayerState) -> discord.Embed:
    """The private role-reveal DM. Every extra role gets its ability
    explained here (and only here/the end-of-round recap - nothing about
    it is ever posted publicly mid-round)."""
    role = pstate.role
    task = pstate.task

    if role == Role.OFFICER:
        embed = discord.Embed(
            title=f"{Emoji.OFFICER} You're the Officer",
            description=(
                "Watch the round and figure out who the Lawbreaker is. "
                f"Use `/shoot` when you're ready to accuse someone - you "
                "only get one shot, so make it count."
            ),
            color=Theme.OFFICER,
        )
    elif role == Role.LAWBREAKER:
        embed = discord.Embed(
            title=f"{Emoji.LAWBREAKER} You're the Lawbreaker",
            description=(
                f"**Your task:** {task.description}\n\n"
                "Work it into the conversation naturally - the Officer is "
                "watching for anything that looks forced."
            ),
            color=Theme.LAWBREAKER,
        )
    elif role == Role.DETECTIVE:
        lead_names = [game.players[pid].display_name for pid in game.detective_lead]
        if len(lead_names) == 1:
            names_list = f"**{lead_names[0]}**"
        else:
            names_list = ", ".join(f"**{n}**" for n in lead_names[:-1]) + f", or **{lead_names[-1]}**"
        embed = discord.Embed(
            title=f"{Emoji.DETECTIVE} You're the Detective",
            description=(
                f"You've got a lead. The real Lawbreaker is one of these "
                f"{len(lead_names)}: {names_list}.\n\n"
                f"**Your own task:** {task.description}\n\n"
                "Work your task in naturally like everyone else - and see "
                "if you can find a subtle way to share your lead with the "
                "Officer without giving away that you're the Detective."
            ),
            color=Theme.INNOCENT,
        )
    elif role == Role.SNITCH:
        embed = discord.Embed(
            title=f"{Emoji.SNITCH} You're the Snitch",
            description=(
                "You've got one favor to call in. Anytime during the round, "
                "run `/tip` to privately find out whether the Lawbreaker's "
                "crime has already landed. One-time use, so time it well.\n\n"
                f"**Your own task:** {task.description}"
            ),
            color=Theme.INNOCENT,
        )
    elif role == Role.VIGILANTE:
        embed = discord.Embed(
            title=f"{Emoji.VIGILANTE} You're the Vigilante",
            description=(
                "You've got your own hunch to play. Anytime during the "
                "round, run `/hunch` to privately lock in who YOU think "
                "the Lawbreaker is - it won't affect the Officer's shot or "
                "end the round, but it'll be revealed (to everyone) "
                "whether you called it right once the case closes. Change "
                "your hunch as many times as you want until time's up.\n\n"
                f"**Your own task:** {task.description}"
            ),
            color=Theme.INNOCENT,
        )
    elif role == Role.DOUBLE_AGENT:
        lawbreaker_name = game.players[game.lawbreaker_id].display_name
        embed = discord.Embed(
            title=f"{Emoji.DOUBLE_AGENT} You're the Double Agent",
            description=(
                f"You're working with the Lawbreaker - **{lawbreaker_name}** "
                "is the one with the real crime to pull off, and you're "
                "covering for them.\n\n"
                f"**Your own decoy task:** {task.description}\n\n"
                "Here's the trick: if YOU complete your task, that's "
                "enough cover that the Lawbreaker's crime counts as done "
                "too - even if they haven't finished it themselves. Blend "
                "in and don't tip anyone off."
            ),
            color=Theme.LAWBREAKER,
        )
    elif role == Role.MIMIC:
        embed = discord.Embed(
            title=f"{Emoji.MIMIC} You're the Mimic",
            description=(
                "Nobody knows this but you - not even the Officer or "
                f"Lawbreaker: you're secretly rooting for the "
                f"**{game.mimic_roots_for}** to win this round. There's "
                "nothing to actually do about it, just watch how it plays "
                "out. It'll be revealed once the case closes.\n\n"
                f"**Your own task:** {task.description}"
            ),
            color=Theme.MYSTERY,
        )
    else:  # Role.INNOCENT
        embed = discord.Embed(
            title=f"{Emoji.INNOCENT} You're an Innocent",
            description=(
                f"**Your task:** {task.description}\n\n"
                "Work it into the conversation naturally - the Officer is "
                "watching for anything that looks forced."
            ),
            color=Theme.INNOCENT,
        )

    if game.round_ends_at is not None:
        end_ts = int(game.round_ends_at.timestamp())
        embed.add_field(name="Round ends", value=f"<t:{end_ts}:R>", inline=True)
    if game.mode != Mode.CLASSIC:
        embed.add_field(name="Mode", value=f"{MODE_EMOJI[game.mode]} {game.mode.value}", inline=True)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_lobby_embed(game: Game, max_players: int) -> discord.Embed:
    """The live lobby card - one message per lobby, edited in place as
    people join and leave rather than resending."""
    names = "\n".join(f"- {p.display_name}" for p in game.players.values()) or "*(empty)*"
    created_ts = int(game.created_at.timestamp())
    embed = discord.Embed(
        title=f"{Emoji.LOBBY} Officer & Lawbreaker - Lobby",
        description=f"`/join` to hop in. Host runs `/startgame` when ready.\nOpened <t:{created_ts}:R>.",
        color=Theme.LOBBY,
    )
    embed.add_field(name=f"Players ({len(game.players)}/{max_players})", value=names, inline=False)
    embed.add_field(name="Host", value=f"<@{game.host_id}>", inline=True)
    embed.add_field(name="Mode", value=f"{MODE_EMOJI[game.mode]} {game.mode.value}", inline=True)
    embed.add_field(name="Tasks", value=_task_content_label(game.task_content), inline=True)
    if game.task_content != TaskContent.SFW:
        embed.add_field(
            name="Heads up",
            value="This lobby's tasks may include 18+ (non-explicit) party-game prompts. `/leave` if that's not your scene.",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_lobby_closed_embed(game: Game, max_players: int, headline: str, color: discord.Color) -> discord.Embed:
    """A frozen snapshot of the lobby for terminal states: emptied out,
    cancelled, or locked in because the game started."""
    names = "\n".join(f"- {p.display_name}" for p in game.players.values()) or "*(empty)*"
    embed = discord.Embed(
        title=f"{Emoji.LOBBY} Officer & Lawbreaker - Lobby",
        description=headline,
        color=color,
    )
    embed.add_field(name=f"Final roster ({len(game.players)}/{max_players})", value=names, inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_round_start_embed(game: Game) -> discord.Embed:
    end_ts = int(game.round_ends_at.timestamp())
    mode_line = ""
    if game.mode != Mode.CLASSIC or game.task_content != TaskContent.SFW:
        mode_line = (
            f"{MODE_EMOJI[game.mode]} **{game.mode.value}** mode - "
            f"{_task_content_label(game.task_content)} tasks.\n\n"
        )
    embed = discord.Embed(
        title=f"{Emoji.TIMER} The round has begun",
        description=(
            f"**{len(game.players)}** players, **{game.round_minutes}** minute(s) on the clock.\n"
            f"Ends <t:{end_ts}:R> (<t:{end_ts}:t>).\n\n"
            f"{mode_line}"
            "Officer, use `/shoot` whenever you're ready. Everyone else - "
            "good luck staying casual."
        ),
        color=Theme.LOBBY,
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _task_status_note(pstate: PlayerState) -> str:
    """A short 'done'/'not done' note for the resolution embed - used for
    every non-Lawbreaker task line so completion status is visible there
    too, not just for the Lawbreaker's crime."""
    icon = Emoji.SUCCESS if pstate.task_complete else Emoji.FAIL
    status = "done" if pstate.task_complete else "not done"
    return f"{icon} {status}"


def build_resolution_embed(
    game: Game, shot_user_id: Optional[int], winner: str, round_points: Optional[dict[int, int]] = None,
) -> discord.Embed:
    lawbreaker = game.players[game.lawbreaker_id]

    if winner == "officer":
        title = f"{Emoji.SIREN} Case closed - Officer wins!"
        color = Theme.OFFICER
    else:
        title = f"{Emoji.LAWBREAKER} The Lawbreaker got away with it!"
        color = Theme.LAWBREAKER

    embed = discord.Embed(title=title, color=color)

    if shot_user_id is not None:
        embed.add_field(name="The shot", value=f"{Emoji.SHOOT} Officer accused <@{shot_user_id}>", inline=False)
    else:
        embed.add_field(name="The shot", value="Time ran out before the Officer took one.", inline=False)

    crime_icon = Emoji.SUCCESS if lawbreaker.task_complete else Emoji.FAIL
    crime_status = "completed" if lawbreaker.task_complete else "did **not** complete"
    covered_note = " *(covered by the Double Agent - see below)*" if game.lawbreaker_covered_by_double_agent else ""
    embed.add_field(
        name=f"{Emoji.LAWBREAKER} The Lawbreaker",
        value=f"<@{game.lawbreaker_id}> - {crime_icon} {crime_status} their task{covered_note}\n*{lawbreaker.task.description}*",
        inline=False,
    )
    embed.add_field(name=f"{Emoji.OFFICER} The Officer", value=f"<@{game.officer_id}>", inline=False)

    innocents = [p for p in game.players.values() if p.role == Role.INNOCENT]
    if innocents:
        lines = [f"<@{p.user_id}> - {_task_status_note(p)} - *{p.task.description}*" for p in innocents]
        embed.add_field(name=f"{Emoji.INNOCENT} Innocents' tasks", value="\n".join(lines), inline=False)

    special_lines: list[str] = []
    if game.detective_id is not None:
        detective = game.players[game.detective_id]
        special_lines.append(
            f"{Emoji.DETECTIVE} **Detective** <@{game.detective_id}> - {_task_status_note(detective)} - "
            f"*{detective.task.description}*"
        )
    if game.snitch_id is not None:
        snitch = game.players[game.snitch_id]
        used = "used their tip" if game.snitch_tip_used else "never cashed in their tip"
        special_lines.append(
            f"{Emoji.SNITCH} **Snitch** <@{game.snitch_id}> ({used}) - {_task_status_note(snitch)} - "
            f"*{snitch.task.description}*"
        )
    if game.vigilante_id is not None:
        vigilante = game.players[game.vigilante_id]
        if game.vigilante_guess_id is not None:
            correct = game.vigilante_guess_id == game.lawbreaker_id
            verdict = f"{Emoji.SUCCESS} called it" if correct else f"{Emoji.FAIL} wrong call"
            hunch = f"guessed <@{game.vigilante_guess_id}> - {verdict}"
        else:
            hunch = "never locked in a hunch"
        special_lines.append(
            f"{Emoji.VIGILANTE} **Vigilante** <@{game.vigilante_id}> ({hunch}) - {_task_status_note(vigilante)} - "
            f"*{vigilante.task.description}*"
        )
    if game.double_agent_id is not None:
        agent = game.players[game.double_agent_id]
        cover_note = "covered for the crime" if game.lawbreaker_covered_by_double_agent else "never had to step in"
        special_lines.append(
            f"{Emoji.DOUBLE_AGENT} **Double Agent** <@{game.double_agent_id}> was secretly working "
            f"with the Lawbreaker ({cover_note}) - {_task_status_note(agent)} - *{agent.task.description}*"
        )
    if game.mimic_id is not None:
        mimic = game.players[game.mimic_id]
        paid_off = game.mimic_roots_for is not None and game.mimic_roots_for.lower() == winner
        verdict = "their gamble paid off! \U0001F389" if paid_off else "their gamble didn't pay off."
        special_lines.append(
            f"{Emoji.MIMIC} **Mimic** <@{game.mimic_id}> was secretly rooting for the "
            f"{game.mimic_roots_for} - {verdict} ({_task_status_note(mimic)} on their own task - "
            f"*{mimic.task.description}*)"
        )

    if special_lines:
        embed.add_field(name="Special roles this round", value="\n".join(special_lines), inline=False)

    if round_points is not None:
        # Only ever present when a session is running in this channel -
        # see resolve_round in cog.py. Sorted so the round's stand-out
        # performance is the first thing you see, same as the standalone
        # leaderboard.
        ranked = sorted(round_points.items(), key=lambda row: -row[1])
        lines = [f"<@{uid}> **+{pts}**" for uid, pts in ranked]
        embed.add_field(name=f"{Emoji.SCORE} Session points this round", value="\n".join(lines), inline=False)

    embed.set_footer(text=FOOTER_TEXT)
    embed.timestamp = discord.utils.utcnow()
    return embed


_STANDINGS_MEDALS = ("\U0001F947", "\U0001F948", "\U0001F949")  # 🥇 🥈 🥉, top 3 only


def build_leaderboard_embed(session: Session, final: bool) -> discord.Embed:
    """The session's point standings - used both for a mid-session
    `/leaderboard` check and for the closing summary `/endsession` sends
    right before the session is torn down (final=True picks the title
    and phrasing for that closing-summary case).
    """
    title = f"{Emoji.SCORE} Final session standings" if final else f"{Emoji.SCORE} Session standings so far"
    standings = session.standings()

    if not standings:
        body = "No points on the board yet - they'll start showing up once a game resolves."
    else:
        lines = []
        for i, (uid, pts) in enumerate(standings):
            rank = _STANDINGS_MEDALS[i] if i < len(_STANDINGS_MEDALS) else f"{i + 1}."
            point_word = "point" if pts == 1 else "points"
            lines.append(f"{rank} <@{uid}> - **{pts}** {point_word}")
        body = "\n".join(lines)

    game_word = "game" if session.games_played == 1 else "games"
    embed = discord.Embed(
        title=title,
        description=f"{body}\n\n*{session.games_played} {game_word} played this session.*",
        color=Theme.SCORE,
    )
    embed.set_footer(text=FOOTER_TEXT)
    embed.timestamp = discord.utils.utcnow()
    return embed


def build_round_progress_line(game: Game) -> str:
    """A one-line status string for /gamestatus: a block progress bar plus
    Discord's own live-updating relative timestamp."""
    total_seconds = game.round_minutes * 60
    remaining = max((game.round_ends_at - discord.utils.utcnow()).total_seconds(), 0.0)
    elapsed_fraction = 1.0 - (remaining / total_seconds) if total_seconds > 0 else 1.0
    bar = render_progress_bar(elapsed_fraction)
    end_ts = int(game.round_ends_at.timestamp())
    mins, secs = divmod(int(remaining), 60)
    return f"{Emoji.TIMER} `{bar}` {int(elapsed_fraction * 100)}%\nAbout **{mins}m {secs}s** left - ends <t:{end_ts}:R>"


def build_modes_embed() -> discord.Embed:
    """/modes - lists every mode and how to set it, mirroring the style of
    an in-lobby "available game modes" reference card."""
    embed = discord.Embed(
        title=f"{Emoji.LOBBY} Available Modes",
        description="Host only, lobby phase only: `/config mode:<mode>` to set one before `/startgame`.",
        color=Theme.LOBBY,
    )
    for mode in Mode:
        info = MODE_INFO[mode]
        embed.add_field(
            name=f"{MODE_EMOJI[mode]} {mode.value}",
            value=f"{info['blurb']}\n*Recommended: {info['recommended']}*",
            inline=False,
        )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def _pack_lines_into_fields(embed: discord.Embed, base_name: str, lines: list[str], limit: int = 900) -> None:
    """Add `lines` to `embed` as one or more fields, splitting before any
    field would cross `limit` chars (900, not Discord's actual 1024, for
    headroom). Keeps this safe by construction as ROLE_INFO blurbs grow or
    roles are added, rather than a fixed field count that could silently
    start overflowing later."""
    chunks: list[list[str]] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        added = len(line) + 1  # +1 for the joining newline
        if current and current_len + added > limit:
            chunks.append(current)
            current, current_len = [], 0
        current.append(line)
        current_len += added
    if current:
        chunks.append(current)

    for i, chunk in enumerate(chunks):
        suffix = f" ({i + 1}/{len(chunks)})" if len(chunks) > 1 else ""
        embed.add_field(name=f"{base_name}{suffix}", value="\n".join(chunk), inline=False)


def build_roles_embed() -> discord.Embed:
    """/roles - every role grouped by which mode unlocks it, each with a
    one-line ability blurb."""
    embed = discord.Embed(
        title=f"{Emoji.INNOCENT} Roles",
        description=(
            f"{ALIGNMENT_OFFICER} sides with the Officer  ·  "
            f"{ALIGNMENT_LAWBREAKER} sides with the Lawbreaker  ·  "
            f"{ALIGNMENT_NEUTRAL} no side of its own  ·  "
            f"{ALIGNMENT_MYSTERY} unknown until the reveal"
        ),
        color=Theme.LOBBY,
    )
    for section_name, roles in ROLE_SECTIONS:
        lines = []
        for role in roles:
            info = ROLE_INFO[role]
            lines.append(f"{info['alignment']} {info['emoji']} **{role.value}** - {info['blurb']}")
        embed.add_field(name=f"{section_name}", value="\n".join(lines), inline=False)
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_about_embed() -> discord.Embed:
    """/about - the elevator pitch, for someone who's never seen this bot
    before. Deliberately short; /howtoplay is the tutorial, /modes and
    /roles are the reference material."""
    embed = discord.Embed(
        title=f"{Emoji.OFFICER} Officer & Lawbreaker",
        description=(
            "A Discord-native social deduction game: one **Lawbreaker** "
            "has a secret task to sneak into ordinary chat, one "
            "**Officer** gets a single shot to catch them, and everyone "
            "else is running interference - as an **Innocent**, or as "
            "something with a bit more going on, depending on the mode.\n\n"
            "Run `/howtoplay` for the full walkthrough, or jump straight "
            "into `/join`."
        ),
        color=Theme.LOBBY,
    )
    embed.add_field(
        name="Make it your own",
        value=(
            "The host can pick a **mode** (`/config mode:`) to bring more "
            "roles into play as the lobby grows - see `/modes` and "
            "`/roles` - and a **task content** rating (`/config content:`): "
            "SFW, 18+ (non-explicit party-game prompts), or Mixed."
        ),
        inline=False,
    )
    embed.add_field(
        name="Commands",
        value=(
            "`/join` `/leave` `/gamestatus` `/config` `/startgame` "
            "`/shoot` `/tip` `/hunch` `/endgame`\n"
            "`/howtoplay` · `/modes` · `/roles` · `/about`"
        ),
        inline=False,
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed


def build_howtoplay_embed() -> discord.Embed:
    """/howtoplay - the tutorial. The "roles at a glance" field is built
    from the same ROLE_INFO data /roles uses (just formatted tighter, and
    with the player-count detail trimmed off each unlock tag) rather than
    a second hand-written copy of each role's ability, so the two commands
    can't quietly drift apart as roles change."""
    embed = discord.Embed(
        title=f"{Emoji.LOBBY} How to Play",
        description=(
            "The short version: everyone's got something to hide, one "
            "person is hunting, and the chat itself is the whole game."
        ),
        color=Theme.LOBBY,
    )
    embed.add_field(
        name="1\uFE0F\u20E3 Get a lobby going",
        value=(
            "`/join` to hop in - first joiner becomes host. Once there "
            "are at least 3 of you, the host runs `/startgame` "
            "(optionally setting `round_minutes`)."
        ),
        inline=False,
    )
    embed.add_field(
        name="2\uFE0F\u20E3 Check your DMs",
        value=(
            "Everyone gets a private task. Work it into normal chat "
            "without making it obvious - the bot checks silently in the "
            "background, and nobody else can see whether you've done it."
        ),
        inline=False,
    )
    embed.add_field(
        name="3\uFE0F\u20E3 The Officer hunts",
        value=(
            "Whenever ready, the Officer runs `/shoot` to accuse someone - "
            "one shot only, with a confirm step so there's no "
            "fat-fingering it."
        ),
        inline=False,
    )
    embed.add_field(
        name=f"{Emoji.SIREN} How it ends",
        value=(
            "- Officer shoots the Lawbreaker \u2192 **Officer wins**\n"
            "- Officer shoots the wrong person \u2192 **Lawbreaker wins**\n"
            "- Time runs out, crime done \u2192 **Lawbreaker wins**\n"
            "- Time runs out, crime NOT done \u2192 **Officer wins**"
        ),
        inline=False,
    )

    role_lines = []
    for role in Role:
        info = ROLE_INFO[role]
        tier = info["unlocked_by"].split(" (")[0]
        tag = "" if tier == "Core" else f" *({tier})*"
        role_lines.append(f"{info['emoji']} **{role.value}**{tag} - {info['blurb']}")
    _pack_lines_into_fields(embed, f"{Emoji.LAWBREAKER} Roles at a glance", role_lines)

    embed.add_field(
        name="\U0001F3A8 Modes & task content",
        value=(
            "Host sets these pre-game with `/config`: `mode` picks which "
            "extra roles are possible (see `/modes`), `content` picks the "
            "task flavor - SFW (default), 18+ (non-explicit party-game "
            "prompts), or Mixed (see `/roles`)."
        ),
        inline=False,
    )
    embed.set_footer(text=FOOTER_TEXT)
    return embed
