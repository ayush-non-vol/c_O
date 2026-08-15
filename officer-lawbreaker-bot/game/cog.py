"""The Cog: slash commands, the round timer + warning ping, resolution,
and the message listener that checks tasks silently in the background.

UI notes:
  - The lobby is a single message, edited in place as people join/leave
    (see _sync_lobby_message) rather than re-sent every time - one
    always-current card instead of a growing pile of embeds.
  - Role delivery DMs fan out concurrently (asyncio.gather) instead of one
    at a time, so a 10-player lobby doesn't wait on 10 sequential DMs.
  - Anything time-related leans on Discord's own dynamic timestamps
    (<t:unix:R>) so countdowns stay live in the client for free, with no
    polling or repeated edits needed on our end.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .constants import (
    DEFAULT_ROUND_MINUTES,
    MAX_PLAYERS,
    MIN_PLAYERS,
    ROUND_MINUTES_MAX,
    ROUND_MINUTES_MIN,
    Mode,
    Phase,
    Role,
    TaskContent,
)
from .embeds import (
    Emoji,
    Theme,
    build_about_embed,
    build_howtoplay_embed,
    build_leaderboard_embed,
    build_lobby_closed_embed,
    build_lobby_embed,
    build_modes_embed,
    build_resolution_embed,
    build_role_embed,
    build_roles_embed,
    build_round_progress_line,
    build_round_start_embed,
)
from .modes import MODE_EMOJI
from .scoring import SessionManager, score_round
from .state import Game, GameManager, PlayerState, assign_roles_and_tasks
from .timing import warning_offset_seconds
from .views import HunchSelectView, RevealRoleView, ShootSelectView

log = logging.getLogger(__name__)


async def _send_role_dm_or_fallback(member: discord.Member, channel: discord.abc.Messageable,
                                     embed: discord.Embed) -> None:
    """DM the role privately; if DMs are closed (error 50007 and friends),
    fall back to an in-channel button whose click is a fresh interaction
    from that exact user, so the reveal can still be ephemeral.
    """
    try:
        await member.send(embed=embed)
    except discord.HTTPException:
        log.info("Couldn't DM %s (%s) - falling back to in-channel reveal button.", member, member.id)
        view = RevealRoleView(target_id=member.id, embed=embed)
        await channel.send(
            content=f"{member.mention}, I couldn't DM you - click below to see your role privately.",
            view=view,
        )


class OfficerLawbreakerCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.manager = GameManager()
        self.sessions = SessionManager()

    # ------------------------------------------------------------------
    # Lobby
    # ------------------------------------------------------------------

    async def _sync_lobby_message(self, game: Game, channel: discord.abc.Messageable) -> None:
        """Keep the one public lobby card current. Edits in place; if the
        edit fails (message deleted, etc.) it quietly sends a fresh one so
        the lobby doesn't lose its live display."""
        embed = build_lobby_embed(game, MAX_PLAYERS)
        if game.lobby_message is not None:
            try:
                await game.lobby_message.edit(embed=embed)
                return
            except discord.HTTPException:
                game.lobby_message = None
        try:
            game.lobby_message = await channel.send(embed=embed)
        except discord.HTTPException:
            log.warning("Could not send/refresh the lobby card in channel %s.", game.channel_id)

    @app_commands.command(name="join", description="Join the lobby in this channel (starts one if there isn't one).")
    async def join(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)

        if game is None:
            game = self.manager.create(
                interaction.channel_id, interaction.guild_id,
                interaction.user.id, interaction.user.display_name,
            )
            await interaction.response.send_message(
                content=f"{Emoji.SIREN} {interaction.user.mention} opened a new lobby!",
                embed=build_lobby_embed(game, MAX_PLAYERS),
            )
            game.lobby_message = await interaction.original_response()
            return

        if game.phase != Phase.LOBBY:
            await interaction.response.send_message(
                "A game's already in progress in this channel - can't join right now.", ephemeral=True,
            )
            return
        if interaction.user.id in game.players:
            await interaction.response.send_message("You're already in the lobby.", ephemeral=True)
            return
        if len(game.players) >= MAX_PLAYERS:
            await interaction.response.send_message("Lobby's full.", ephemeral=True)
            return

        game.players[interaction.user.id] = PlayerState(
            user_id=interaction.user.id, display_name=interaction.user.display_name,
        )
        await interaction.response.send_message(
            f"{Emoji.SUCCESS} **{interaction.user.display_name}** joined. ({len(game.players)}/{MAX_PLAYERS})",
        )
        await self._sync_lobby_message(game, interaction.channel)

    @app_commands.command(name="leave", description="Leave the lobby (only before the game starts).")
    async def leave(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None or interaction.user.id not in game.players:
            await interaction.response.send_message("You're not in a lobby in this channel.", ephemeral=True)
            return
        if game.phase != Phase.LOBBY:
            await interaction.response.send_message(
                "Can't leave once a game's underway - ask the host (or a mod) to `/endgame` if it needs to stop.",
                ephemeral=True,
            )
            return

        leaving_id = interaction.user.id
        leaving_name = interaction.user.display_name
        del game.players[leaving_id]

        if not game.players:
            self.manager.remove(interaction.channel_id)
            await interaction.response.send_message(f"{leaving_name} left. Lobby's empty, so it's closed.")
            if game.lobby_message is not None:
                try:
                    await game.lobby_message.edit(
                        embed=build_lobby_closed_embed(game, MAX_PLAYERS, "Lobby closed - everyone left.", Theme.NEUTRAL),
                    )
                except discord.HTTPException:
                    pass
            return

        if game.host_id == leaving_id:
            game.host_id = next(iter(game.players))  # promote the earliest remaining joiner
            await interaction.response.send_message(
                f"{leaving_name} left and was the host - <@{game.host_id}> is now the host.",
            )
            await self._sync_lobby_message(game, interaction.channel)
            return

        await interaction.response.send_message(
            f"**{leaving_name}** left the lobby. ({len(game.players)}/{MAX_PLAYERS})",
        )
        await self._sync_lobby_message(game, interaction.channel)

    @app_commands.command(name="gamestatus", description="Check the lobby or round status in this channel.")
    async def gamestatus(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None:
            await interaction.response.send_message("No game running here - `/join` to start one.", ephemeral=True)
            return
        if game.phase == Phase.LOBBY:
            await interaction.response.send_message(embed=build_lobby_embed(game, MAX_PLAYERS), ephemeral=True)
            return
        if game.phase == Phase.ACTIVE_ROUND and game.round_ends_at:
            await interaction.response.send_message(build_round_progress_line(game), ephemeral=True)
            return
        await interaction.response.send_message(f"Phase: {game.phase.name}", ephemeral=True)

    # ------------------------------------------------------------------
    # Mode / task-content configuration, and the /modes, /roles, /about,
    # /howtoplay info cards. /config is lobby-phase-only and host-only,
    # same permission model as /startgame - this is a pre-game setting,
    # not something that changes mid-round. The info commands need no
    # game state at all and work anywhere, anytime.
    # ------------------------------------------------------------------

    @app_commands.command(name="config", description="Host only: set this lobby's mode and/or task content before starting.")
    @app_commands.describe(
        mode="Which role set to play with - see /modes for details.",
        content="Which flavor of tasks to draw from - see /roles for what each mode unlocks.",
    )
    @app_commands.choices(
        mode=[app_commands.Choice(name=f"{MODE_EMOJI[m]} {m.value}", value=m.name) for m in Mode],
        content=[
            app_commands.Choice(name="SFW - family-friendly only", value=TaskContent.SFW.name),
            app_commands.Choice(name="18+ - adult party-game prompts, non-explicit", value=TaskContent.EIGHTEEN_PLUS.name),
            app_commands.Choice(name="Mixed - either, drawn at random per player", value=TaskContent.MIXED.name),
        ],
    )
    async def config(
        self,
        interaction: discord.Interaction,
        mode: Optional[str] = None,
        content: Optional[str] = None,
    ) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None:
            await interaction.response.send_message("No lobby here yet - `/join` first.", ephemeral=True)
            return
        if game.phase != Phase.LOBBY:
            await interaction.response.send_message("Can't change settings once the game has started.", ephemeral=True)
            return
        if interaction.user.id != game.host_id:
            await interaction.response.send_message("Only the host can change lobby settings.", ephemeral=True)
            return
        if mode is None and content is None:
            await interaction.response.send_message(
                "Pass `mode` and/or `content` to change something - `/modes` and `/roles` list what's available.",
                ephemeral=True,
            )
            return

        changes: list[str] = []
        if mode is not None:
            game.mode = Mode[mode]
            changes.append(f"Mode set to **{game.mode.value}**.")
        if content is not None:
            game.task_content = TaskContent[content]
            changes.append(f"Task content set to **{game.task_content.value}**.")

        response = " ".join(changes)
        if content is not None and game.task_content != TaskContent.SFW:
            response += "\n\u26A0\uFE0F This lobby's tasks may include 18+ (non-explicit) party-game prompts - heads up before anyone else `/join`s."

        await interaction.response.send_message(response)
        await self._sync_lobby_message(game, interaction.channel)

    @app_commands.command(name="modes", description="List the available game modes and how to set one.")
    async def modes(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_modes_embed(), ephemeral=True)

    @app_commands.command(name="roles", description="List every role, what unlocks it, and what it does.")
    async def roles(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_roles_embed(), ephemeral=True)

    @app_commands.command(name="about", description="What this bot is and how to get started.")
    async def about(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_about_embed(), ephemeral=True)

    @app_commands.command(name="howtoplay", description="A step-by-step walkthrough, including every role's ability.")
    async def howtoplay(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=build_howtoplay_embed(), ephemeral=True)

    # ------------------------------------------------------------------
    # Start / role assignment
    # ------------------------------------------------------------------

    @app_commands.command(name="startgame", description="Start the game with the current lobby.")
    @app_commands.describe(
        round_minutes=f"Round length in minutes ({ROUND_MINUTES_MIN}-{ROUND_MINUTES_MAX}). Default {DEFAULT_ROUND_MINUTES}.",
    )
    async def startgame(
        self,
        interaction: discord.Interaction,
        round_minutes: Optional[app_commands.Range[int, ROUND_MINUTES_MIN, ROUND_MINUTES_MAX]] = None,
    ) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None:
            await interaction.response.send_message("No lobby here yet - `/join` first.", ephemeral=True)
            return
        if game.phase != Phase.LOBBY:
            await interaction.response.send_message("This game already started.", ephemeral=True)
            return
        if interaction.user.id != game.host_id:
            await interaction.response.send_message("Only the host can start the game.", ephemeral=True)
            return
        if len(game.players) < MIN_PLAYERS:
            await interaction.response.send_message(
                f"Need at least {MIN_PLAYERS} players - only {len(game.players)} so far.", ephemeral=True,
            )
            return

        game.round_minutes = round_minutes or DEFAULT_ROUND_MINUTES
        game.phase = Phase.ROLE_ASSIGNMENT
        await interaction.response.send_message(
            f"{Emoji.LOCKED} Starting! Round length: **{game.round_minutes} minute(s)**. "
            "Assigning roles now - check your DMs...",
        )
        if game.lobby_message is not None:
            try:
                await game.lobby_message.edit(
                    embed=build_lobby_closed_embed(
                        game, MAX_PLAYERS, f"{Emoji.LOCKED} Game in progress - roster locked in.", Theme.NEUTRAL,
                    ),
                )
            except discord.HTTPException:
                pass
        await self._assign_and_start_round(game, interaction)

    async def _assign_and_start_round(self, game: Game, interaction: discord.Interaction) -> None:
        guild = interaction.guild

        def resolve_display_name(user_id: int) -> str:
            player = game.players.get(user_id)
            return player.display_name if player else str(user_id)

        assign_roles_and_tasks(game, resolve_display_name)
        game.round_ends_at = discord.utils.utcnow() + timedelta(minutes=game.round_minutes)

        # Flip to ACTIVE_ROUND and start the clock *before* any DMs go
        # out, not after. Every player's role+task is already fully
        # assigned above (that part is synchronous), but DM delivery below
        # is a network round-trip per player and can take a real moment
        # for a full lobby - on_message only processes messages once
        # phase == ACTIVE_ROUND, so leaving the flip until after all DMs
        # land meant a player who gets their own DM quickly and
        # immediately works their task into chat could have that message
        # silently ignored while slower deliveries were still in flight:
        # task genuinely never marked complete, no "task complete" DM
        # (there was nothing to send one for), and correctly - if
        # confusingly - shown as incomplete at round end, since it truly
        # never registered. Starting the clock here instead closes that
        # window entirely.
        game.phase = Phase.ACTIVE_ROUND
        game.timer_task = asyncio.create_task(self._round_timer(game))
        game.warning_task = asyncio.create_task(self._round_warning(game))

        async def deliver(uid: int, pstate: PlayerState) -> None:
            member = guild.get_member(uid)
            if member is None:
                try:
                    member = await guild.fetch_member(uid)
                except discord.HTTPException:
                    log.warning("Could not resolve member %s in guild %s for role delivery.", uid, guild.id)
                    return
            embed = build_role_embed(game, pstate)
            await _send_role_dm_or_fallback(member, interaction.channel, embed)

        # Concurrent, not sequential - a 10-player lobby shouldn't wait on
        # 10 DMs one after another. return_exceptions so one bad delivery
        # doesn't take the rest down with it.
        results = await asyncio.gather(
            *(deliver(uid, pstate) for uid, pstate in game.players.items()),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, Exception):
                log.error("Role delivery task failed: %r", result)

        log.info(
            "Round started in channel %s: %d players, %d minute(s), ends at %s.",
            game.channel_id, len(game.players), game.round_minutes, game.round_ends_at,
        )
        await interaction.followup.send(embed=build_round_start_embed(game))

    async def _round_timer(self, game: Game) -> None:
        try:
            delay = (game.round_ends_at - discord.utils.utcnow()).total_seconds()
            await asyncio.sleep(max(delay, 0))
        except asyncio.CancelledError:
            return
        await self.resolve_round(game, shot_user_id=None)

    async def _round_warning(self, game: Game) -> None:
        """A single 'down to the wire' ping shortly before time runs out -
        scaled to the round length so it means the same thing whether the
        round is 2 minutes or 24 hours."""
        offset = warning_offset_seconds(game.round_minutes * 60)
        try:
            delay = (game.round_ends_at - discord.utils.utcnow()).total_seconds() - offset
            if delay <= 0:
                return
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        if game.resolved:
            return
        channel = self.bot.get_channel(game.channel_id)
        if channel is not None:
            end_ts = int(game.round_ends_at.timestamp())
            try:
                await channel.send(f"{Emoji.ALARM} Down to the wire - round ends <t:{end_ts}:R>!")
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------
    # Shoot
    # ------------------------------------------------------------------

    @app_commands.command(name="shoot", description="Officer only: accuse a player of being the Lawbreaker.")
    async def shoot(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None or game.phase != Phase.ACTIVE_ROUND:
            await interaction.response.send_message("There's no active round here right now.", ephemeral=True)
            return
        if interaction.user.id != game.officer_id:
            await interaction.response.send_message("Only the Officer can do that.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=p.display_name, value=str(uid), emoji="\U0001F464")
            for uid, p in game.players.items() if uid != game.officer_id
        ]

        async def resolve_callback(target_id: int) -> None:
            await self.resolve_round(game, shot_user_id=target_id)

        view = ShootSelectView(options, resolve_callback)
        await interaction.response.send_message(
            f"{Emoji.SHOOT} Who do you want to shoot? Choose carefully - there's no undo once you confirm.",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    # ------------------------------------------------------------------
    # Special role actions - Snitch's /tip and Vigilante's /hunch. Neither
    # one touches the round outcome or is visible to anyone but the player
    # using it; both are pure private information/bookkeeping, same spirit
    # as checking your own DM'd task.
    # ------------------------------------------------------------------

    @app_commands.command(name="tip", description="Snitch only: privately check whether the crime has landed yet. One-time use.")
    async def tip(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None or game.phase != Phase.ACTIVE_ROUND:
            await interaction.response.send_message("There's no active round here right now.", ephemeral=True)
            return
        if interaction.user.id != game.snitch_id:
            await interaction.response.send_message("Only this round's Snitch can do that.", ephemeral=True)
            return
        if game.snitch_tip_used:
            await interaction.response.send_message("You've already used your one tip this round.", ephemeral=True)
            return

        game.snitch_tip_used = True
        crime_done = game.players[game.lawbreaker_id].task_complete
        verdict = "has already landed" if crime_done else "hasn't landed yet"
        await interaction.response.send_message(
            f"{Emoji.SNITCH} Word on the street: the crime **{verdict}**.", ephemeral=True,
        )

    @app_commands.command(name="hunch", description="Vigilante only: privately lock in who you think the Lawbreaker is. Changeable anytime.")
    async def hunch(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None or game.phase != Phase.ACTIVE_ROUND:
            await interaction.response.send_message("There's no active round here right now.", ephemeral=True)
            return
        if interaction.user.id != game.vigilante_id:
            await interaction.response.send_message("Only this round's Vigilante can do that.", ephemeral=True)
            return

        options = [
            discord.SelectOption(label=p.display_name, value=str(uid), emoji="\U0001F464")
            for uid, p in game.players.items() if uid != game.vigilante_id
        ]

        async def lock_callback(target_id: int) -> None:
            game.vigilante_guess_id = target_id

        current = ""
        if game.vigilante_guess_id is not None:
            current_name = game.players[game.vigilante_guess_id].display_name
            current = f" Current hunch: **{current_name}**."

        view = HunchSelectView(options, lock_callback)
        await interaction.response.send_message(
            f"{Emoji.VIGILANTE} Who's your hunch?{current}",
            view=view,
            ephemeral=True,
        )
        view.message = await interaction.original_response()

    # ------------------------------------------------------------------
    # Resolution - race-guarded, since /shoot's confirm button and the
    # round timer can both try to call this.
    # ------------------------------------------------------------------

    async def resolve_round(self, game: Game, shot_user_id: Optional[int]) -> None:
        if game.resolved:
            return
        game.resolved = True
        game.phase = Phase.RESOLUTION

        if game.timer_task and not game.timer_task.done():
            game.timer_task.cancel()
        if game.warning_task and not game.warning_task.done():
            game.warning_task.cancel()

        lawbreaker_caught = shot_user_id is not None and shot_user_id == game.lawbreaker_id
        crime_completed = game.players[game.lawbreaker_id].task_complete

        if shot_user_id is not None:
            winner = "officer" if lawbreaker_caught else "lawbreaker"
        else:
            # Time ran out with no shot taken: officer wins by default if
            # the crime never actually landed, otherwise the lawbreaker
            # wins. Without this branch a lawbreaker could just go silent
            # for a free stalemate.
            winner = "lawbreaker" if crime_completed else "officer"

        log.info(
            "Round resolved in channel %s: winner=%s shot=%s crime_completed=%s.",
            game.channel_id, winner, shot_user_id, crime_completed,
        )

        # If a session is running in this channel, fold this round's
        # individual-performance points into it now - this is the last
        # moment `game` exists (it's discarded a few lines down), and the
        # only place round outcomes ever get read for scoring.
        session = self.sessions.get(game.channel_id)
        round_points = None
        if session is not None:
            round_points = score_round(game, winner, shot_user_id)
            session.add_round(round_points)

        # Note: build_resolution_embed only ever shows pool-authored task
        # descriptions and <@id> mentions, never a player's raw message
        # text, and it's all inside embed fields (which Discord doesn't
        # parse for @everyone/@here anyway). If you extend this to quote
        # someone's actual completing message, pass
        # allowed_mentions=discord.AllowedMentions.none() on the send()
        # below - a Lawbreaker could otherwise stuff @everyone into their
        # crime message and have the recap re-ping the whole server.
        embed = build_resolution_embed(game, shot_user_id, winner, round_points)
        channel = self.bot.get_channel(game.channel_id)
        if channel is not None:
            await channel.send(embed=embed)

        game.phase = Phase.END
        self.manager.remove(game.channel_id)

    # ------------------------------------------------------------------
    # Endgame / cancel - same permission model as /startgame's host
    # control, plus a moderator override in case the host goes AFK.
    # ------------------------------------------------------------------

    @app_commands.command(name="endgame", description="Cancel the current lobby or round in this channel.")
    async def endgame(self, interaction: discord.Interaction) -> None:
        game = self.manager.get(interaction.channel_id)
        if game is None:
            await interaction.response.send_message("There's nothing running here to cancel.", ephemeral=True)
            return

        is_host = interaction.user.id == game.host_id
        is_mod = (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.manage_guild
        )
        if not (is_host or is_mod):
            await interaction.response.send_message(
                "Only the host or a server moderator can cancel this game.", ephemeral=True,
            )
            return

        if game.timer_task and not game.timer_task.done():
            game.timer_task.cancel()
        if game.warning_task and not game.warning_task.done():
            game.warning_task.cancel()
        game.resolved = True
        was_lobby = game.phase == Phase.LOBBY
        self.manager.remove(interaction.channel_id)
        log.info("Game in channel %s cancelled by %s (%s).", interaction.channel_id, interaction.user, interaction.user.id)
        await interaction.response.send_message(f"\U0001F6D1 Game cancelled by {interaction.user.mention}.")

        if was_lobby and game.lobby_message is not None:
            try:
                await game.lobby_message.edit(
                    embed=build_lobby_closed_embed(
                        game, MAX_PLAYERS, f"{Emoji.FAIL} Cancelled by {interaction.user.display_name}.",
                        discord.Color.orange(),
                    ),
                )
            except discord.HTTPException:
                pass

    # ------------------------------------------------------------------
    # Session scoring - independent of any single Game. A session tracks
    # individual-performance points across however many games get played
    # in this channel between /startsession and /endsession; end-session
    # permissions mirror /endgame above (starter or a moderator).
    # ------------------------------------------------------------------

    @app_commands.command(
        name="startsession",
        description="Start a scoring session - points build up across every game played here until /endsession.",
    )
    async def startsession(self, interaction: discord.Interaction) -> None:
        if self.sessions.get(interaction.channel_id) is not None:
            await interaction.response.send_message(
                "There's already a session running here - `/leaderboard` to check it, "
                "or `/endsession` to close it out.",
                ephemeral=True,
            )
            return

        self.sessions.create(interaction.channel_id, started_by=interaction.user.id)
        await interaction.response.send_message(
            f"{Emoji.SCORE} Session started by {interaction.user.mention}! Every game played in this channel "
            "from here on adds to the board - `/leaderboard` any time, `/endsession` when you're done.",
        )

    @app_commands.command(name="endsession", description="End the scoring session here and post the final standings.")
    async def endsession(self, interaction: discord.Interaction) -> None:
        session = self.sessions.get(interaction.channel_id)
        if session is None:
            await interaction.response.send_message("No session running here.", ephemeral=True)
            return

        is_starter = interaction.user.id == session.started_by
        is_mod = (
            isinstance(interaction.user, discord.Member)
            and interaction.user.guild_permissions.manage_guild
        )
        if not (is_starter or is_mod):
            await interaction.response.send_message(
                "Only whoever started the session (or a server moderator) can end it.", ephemeral=True,
            )
            return

        self.sessions.remove(interaction.channel_id)
        await interaction.response.send_message(embed=build_leaderboard_embed(session, final=True))

    @app_commands.command(name="leaderboard", description="Check the current session's point standings in this channel.")
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        session = self.sessions.get(interaction.channel_id)
        if session is None:
            await interaction.response.send_message(
                "No session running here - `/startsession` to start one.", ephemeral=True,
            )
            return
        await interaction.response.send_message(embed=build_leaderboard_embed(session, final=False))

    # ------------------------------------------------------------------
    # Task-completion listener - silent, server-side only. No public
    # reaction, ever: that would hand the Officer a live suspect-locator.
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        game = self.manager.get(message.channel.id)
        if game is None or game.phase != Phase.ACTIVE_ROUND:
            return
        if game.round_ends_at and discord.utils.utcnow() >= game.round_ends_at:
            return  # timer is about to (or already did) resolve this

        pstate = game.players.get(message.author.id)
        if pstate is None or pstate.role == Role.OFFICER or pstate.task_complete or pstate.task is None:
            return

        if pstate.task.check(message):
            pstate.task_complete = True
            pstate.completed_at = discord.utils.utcnow()
            log.info(
                "Task completed in channel %s: user=%s task_id=%s.",
                message.channel.id, message.author.id, pstate.task.id,
            )
            # Double Agent interference: finishing their OWN decoy task
            # runs enough cover that it also completes the Lawbreaker's
            # crime, even if the Lawbreaker hasn't finished it themselves.
            # See build_role_embed's Double Agent copy for the
            # player-facing explanation of this, and
            # lawbreaker_covered_by_double_agent's docstring in state.py
            # for where this gets surfaced post-round.
            if (
                pstate.role == Role.DOUBLE_AGENT
                and game.lawbreaker_id is not None
                and not game.players[game.lawbreaker_id].task_complete
            ):
                lawbreaker = game.players[game.lawbreaker_id]
                lawbreaker.task_complete = True
                lawbreaker.completed_at = discord.utils.utcnow()
                game.lawbreaker_covered_by_double_agent = True
                log.info(
                    "Double Agent interference in channel %s: user=%s covered for lawbreaker=%s.",
                    message.channel.id, message.author.id, game.lawbreaker_id,
                )
            try:
                await message.author.send(f"{Emoji.SUCCESS} Task complete. Sit tight.")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    """Standard extension entry point, kept in case this ever gets loaded
    via bot.load_extension() instead of being wired up directly in main.py
    (e.g. if you fold it into a cogs/ folder alongside Gaia later).
    """
    await bot.add_cog(OfficerLawbreakerCog(bot))
