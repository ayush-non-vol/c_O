"""Integration-style tests for game/cog.py's orchestration logic - the
parts test_tasks.py/test_state.py don't reach because they're about async
wiring (parallel DM fan-out, editing the lobby card, race-guarded
resolution) rather than pure game logic.

Uses small hand-rolled fakes instead of a live Discord connection or a
mocking framework - just enough duck-typed surface to match what cog.py
actually calls.

Run directly:   python tests/test_integration.py
Or with pytest: pytest tests/
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import discord  # noqa: E402
from discord.ext import commands  # noqa: E402

from game.cog import OfficerLawbreakerCog  # noqa: E402
from game.constants import Mode, Phase, Role  # noqa: E402
from game.scoring import OFFICER_CORRECT_CATCH_POINTS  # noqa: E402
from game.state import PlayerState  # noqa: E402
from game.tasks import Task  # noqa: E402


class FakeHTTPException(discord.HTTPException):
    """A raisable/catchable stand-in - skips the real __init__, which
    wants a live aiohttp response object we don't have here."""

    def __init__(self):
        pass


class FakeMessage:
    def __init__(self):
        self.edits: list[dict] = []
        self.edit_fails = False

    async def edit(self, **kwargs):
        if self.edit_fails:
            raise FakeHTTPException()
        self.edits.append(kwargs)


class FakeMember:
    def __init__(self, user_id, display_name, dm_fails=False):
        self.id = user_id
        self.display_name = display_name
        self.mention = f"<@{user_id}>"
        self.bot = False
        self.dm_fails = dm_fails
        self.dms_received: list[tuple] = []

    async def send(self, content=None, *, embed=None):
        if self.dm_fails:
            raise FakeHTTPException()
        self.dms_received.append((content, embed))
        return FakeMessage()


class FakeGuild:
    def __init__(self, members):
        self.id = 999
        self._members = {m.id: m for m in members}

    def get_member(self, uid):
        return self._members.get(uid)

    async def fetch_member(self, uid):
        member = self._members.get(uid)
        if member is None:
            raise FakeHTTPException()
        return member


class FakeChannel:
    def __init__(self, channel_id=1):
        self.id = channel_id
        self.sent: list[tuple] = []

    async def send(self, *args, **kwargs):
        msg = FakeMessage()
        self.sent.append((args, kwargs, msg))
        return msg


class FakeFollowup:
    def __init__(self, channel):
        self.channel = channel
        self.sent: list[tuple] = []

    async def send(self, *args, **kwargs):
        self.sent.append((args, kwargs))
        return await self.channel.send(*args, **kwargs)


class FakeInteraction:
    def __init__(self, guild, channel):
        self.guild = guild
        self.guild_id = guild.id
        self.channel = channel
        self.channel_id = channel.id
        self.followup = FakeFollowup(channel)


class _FakeChannelRef:
    def __init__(self, channel_id):
        self.id = channel_id


class FakeUserMessage:
    """Stands in for discord.Message in on_message tests."""

    def __init__(self, author, content, channel_id):
        self.author = author
        self.content = content
        self.reference = None
        self.mentions: list = []
        self.guild = FakeGuild([])  # just needs to be non-None
        self.channel = _FakeChannelRef(channel_id)


def run(coro):
    return asyncio.run(coro)


def make_cog(channel=None):
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    if channel is not None:
        # resolve_round/_round_warning look channels up via bot.get_channel();
        # there's no live gateway cache here, so point it at our fake.
        bot.get_channel = lambda cid: channel if cid == channel.id else None
    return OfficerLawbreakerCog(bot)


def make_full_lobby(cog, guild, channel, n_players=4, round_minutes=2):
    members = [FakeMember(1000 + i, f"Player {i}") for i in range(n_players)]
    for m in members:
        guild._members[m.id] = m
    game = cog.manager.create(channel.id, guild.id, members[0].id, members[0].display_name)
    for m in members[1:]:
        game.players[m.id] = PlayerState(user_id=m.id, display_name=m.display_name)
    game.round_minutes = round_minutes
    return game, members


# --------------------------------------------------------------------------
# _sync_lobby_message
# --------------------------------------------------------------------------

def test_sync_lobby_message_edits_existing_message():
    async def scenario():
        cog = make_cog()
        channel = FakeChannel()
        game = cog.manager.create(1, 99, 1000, "Host")
        game.lobby_message = FakeMessage()
        await cog._sync_lobby_message(game, channel)
        assert len(game.lobby_message.edits) == 1
        assert not channel.sent  # existing message was edited, nothing new sent
    run(scenario())


def test_sync_lobby_message_falls_back_to_new_message_on_edit_failure():
    async def scenario():
        cog = make_cog()
        channel = FakeChannel()
        game = cog.manager.create(1, 99, 1000, "Host")
        stale = FakeMessage()
        stale.edit_fails = True
        game.lobby_message = stale
        await cog._sync_lobby_message(game, channel)
        assert len(channel.sent) == 1
        assert game.lobby_message is not stale
    run(scenario())


# --------------------------------------------------------------------------
# _assign_and_start_round: parallel role/task delivery
# --------------------------------------------------------------------------

def test_assign_and_start_round_delivers_roles_and_starts_timers():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=5)
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)

        for m in members:
            assert len(m.dms_received) == 1, f"expected exactly one role DM for {m.display_name}"
        assert game.phase == Phase.ACTIVE_ROUND
        assert game.timer_task is not None and not game.timer_task.done()
        assert game.warning_task is not None and not game.warning_task.done()
        assert interaction.followup.sent, "round-start embed should have gone out"

        game.timer_task.cancel()
        game.warning_task.cancel()
    run(scenario())


def test_assign_and_start_round_falls_back_when_dm_closed():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        members[1].dm_fails = True
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)

        assert any("couldn't DM you" in str(kwargs) for args, kwargs, _ in channel.sent)
        assert game.phase == Phase.ACTIVE_ROUND

        game.timer_task.cancel()
        game.warning_task.cancel()
    run(scenario())


def test_on_message_is_not_ignored_while_other_players_dms_are_still_in_flight():
    # Regression test: phase used to only flip to ACTIVE_ROUND *after*
    # every DM had finished sending, so on_message (which only processes
    # messages once phase == ACTIVE_ROUND) would silently drop anything a
    # fast player sent while a slower delivery was still in flight - the
    # task genuinely never got marked complete, not just a missed
    # notification. This stalls one member's DM mid-delivery and checks
    # that a different, already-assigned player's message still counts.
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        interaction = FakeInteraction(guild, channel)

        stall = asyncio.Event()
        slow_member = members[-1]
        original_send = slow_member.send

        async def stalling_send(*args, **kwargs):
            await stall.wait()
            return await original_send(*args, **kwargs)

        slow_member.send = stalling_send

        start_task = asyncio.create_task(cog._assign_and_start_round(game, interaction))
        await asyncio.sleep(0)
        await asyncio.sleep(0)

        assert not start_task.done(), "the slow DM should still be pending at this point"
        assert game.phase == Phase.ACTIVE_ROUND, "round should already be live even before every DM lands"

        fast_player_id = next(
            uid for uid, p in game.players.items() if uid != slow_member.id and p.role != Role.OFFICER
        )
        game.players[fast_player_id].task = Task("forced", "forced task", lambda m: True, "test")
        msg = FakeUserMessage(author=FakeMember(fast_player_id, "fast"), content="go", channel_id=channel.id)
        await cog.on_message(msg)

        assert game.players[fast_player_id].task_complete is True, (
            "a message sent while another player's DM was still in flight must still be processed"
        )

        stall.set()
        await start_task
        game.timer_task.cancel()
        game.warning_task.cancel()
    run(scenario())


# --------------------------------------------------------------------------
# on_message dispatch + resolve_round
# --------------------------------------------------------------------------

def test_on_message_completes_task_and_resolve_round_declares_winner():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        # Swap in a fully-controlled task so this test verifies
        # on_message's dispatch logic, not any one validator's own rule
        # (those already have their own unit tests).
        lawbreaker_id = game.lawbreaker_id
        game.players[lawbreaker_id].task = Task("forced", "forced task", lambda m: True, "test")

        msg = FakeUserMessage(author=FakeMember(lawbreaker_id, "whoever"), content="irrelevant", channel_id=channel.id)
        await cog.on_message(msg)
        assert game.players[lawbreaker_id].task_complete is True

        await cog.resolve_round(game, shot_user_id=None)
        assert channel.sent, "resolution embed should have been posted"
        assert cog.manager.get(game.channel_id) is None  # cleaned up after resolution
    run(scenario())


def test_on_message_double_agent_interference_completes_lawbreaker_task():
    # Chaos mode at 6 players unlocks the Double Agent (see game/modes.py's
    # thresholds) - this exercises the one bit of on_message logic that's
    # new for extra roles: completing the Double Agent's own task should
    # also flip the Lawbreaker's task_complete, even though the Lawbreaker
    # never sent a qualifying message themselves.
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=6)
        game.mode = Mode.CHAOS
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        assert game.double_agent_id is not None, "expected Chaos mode at 6 players to include a Double Agent"
        lawbreaker_id = game.lawbreaker_id
        agent_id = game.double_agent_id
        assert game.players[lawbreaker_id].task_complete is False

        game.players[agent_id].task = Task("forced", "forced task", lambda m: True, "test")
        msg = FakeUserMessage(author=FakeMember(agent_id, "whoever"), content="irrelevant", channel_id=channel.id)
        await cog.on_message(msg)

        assert game.players[agent_id].task_complete is True
        assert game.players[lawbreaker_id].task_complete is True, "Double Agent should have covered for the Lawbreaker"
        assert game.lawbreaker_covered_by_double_agent is True
    run(scenario())


def test_on_message_lawbreaker_completing_their_own_task_is_not_flagged_as_covered():
    # The flip side of the test above: if the Lawbreaker completes their
    # OWN task before the Double Agent ever does anything, that's not
    # "coverage" - lawbreaker_covered_by_double_agent must stay False so
    # the resolution embed doesn't misattribute a genuine completion.
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=6)
        game.mode = Mode.CHAOS
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        assert game.double_agent_id is not None
        lawbreaker_id = game.lawbreaker_id

        game.players[lawbreaker_id].task = Task("forced", "forced task", lambda m: True, "test")
        msg = FakeUserMessage(author=FakeMember(lawbreaker_id, "whoever"), content="irrelevant", channel_id=channel.id)
        await cog.on_message(msg)

        assert game.players[lawbreaker_id].task_complete is True
        assert game.lawbreaker_covered_by_double_agent is False, "the Lawbreaker did it themselves - no cover involved"
    run(scenario())


def test_resolve_round_is_race_guarded():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        interaction = FakeInteraction(guild, channel)

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        await cog.resolve_round(game, shot_user_id=game.officer_id)
        sent_after_first = len(channel.sent)

        # Simulates the round timer firing right after a /shoot confirm
        # already resolved things - must be a no-op, not a second embed.
        await cog.resolve_round(game, shot_user_id=None)
        assert len(channel.sent) == sent_after_first
    run(scenario())


def test_resolve_round_adds_points_to_an_active_session():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        interaction = FakeInteraction(guild, channel)
        cog.sessions.create(channel.id, started_by=members[0].id)

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        await cog.resolve_round(game, shot_user_id=game.lawbreaker_id)  # a correct catch

        session = cog.sessions.get(channel.id)
        assert session is not None, "resolve_round must not tear down an active session"
        assert session.games_played == 1
        assert session.scores[game.officer_id] == OFFICER_CORRECT_CATCH_POINTS
    run(scenario())


def test_resolve_round_leaves_things_alone_when_no_session_is_running():
    async def scenario():
        channel = FakeChannel()
        guild = FakeGuild([])
        cog = make_cog(channel)
        game, members = make_full_lobby(cog, guild, channel, n_players=4)
        interaction = FakeInteraction(guild, channel)
        # Deliberately no cog.sessions.create() here.

        await cog._assign_and_start_round(game, interaction)
        game.timer_task.cancel()
        game.warning_task.cancel()

        await cog.resolve_round(game, shot_user_id=game.lawbreaker_id)

        assert cog.sessions.get(channel.id) is None  # resolve_round must never create one on its own
    run(scenario())


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
        except Exception as e:  # noqa: BLE001 - surface anything unexpected as a failure too
            failed += 1
            print(f"ERROR {name}: {e!r}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
