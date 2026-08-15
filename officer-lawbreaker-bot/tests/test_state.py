"""Unit tests for game/state.py - role/task assignment and GameManager.
Still no live Discord connection: display-name resolution is injected as a
plain callable instead of a real guild lookup.

Run directly:   python tests/test_state.py
Or with pytest: pytest tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game.constants import Mode, Role, TaskContent  # noqa: E402
from game.modes import detective_lead_size  # noqa: E402
from game.state import GameManager, PlayerState, assign_roles_and_tasks  # noqa: E402
from game.tasks import CRIME_TASKS, CRIME_TASKS_18PLUS, INNOCENT_TASKS, INNOCENT_TASKS_18PLUS  # noqa: E402


def make_game(manager, n_players, channel_id=1, mode=Mode.CLASSIC, task_content=TaskContent.SFW):
    game = manager.create(channel_id, guild_id=99, host_id=1000, host_display="Player 1000")
    for i in range(1, n_players):
        uid = 1000 + i
        game.players[uid] = PlayerState(user_id=uid, display_name=f"Player {uid}")
    game.mode = mode
    game.task_content = task_content
    return game


def resolver(uid):
    return f"Player {uid}"


def test_assign_roles_basic_distribution():
    manager = GameManager()
    game = make_game(manager, n_players=5)
    assign_roles_and_tasks(game, resolver)

    roles = [p.role for p in game.players.values()]
    assert roles.count(Role.OFFICER) == 1
    assert roles.count(Role.LAWBREAKER) == 1
    assert roles.count(Role.INNOCENT) == 3

    officer = game.players[game.officer_id]
    lawbreaker = game.players[game.lawbreaker_id]
    assert officer.role == Role.OFFICER
    assert officer.task is None  # the Officer never gets a task
    assert lawbreaker.role == Role.LAWBREAKER
    assert lawbreaker.task is not None

    innocents = [p for p in game.players.values() if p.role == Role.INNOCENT]
    for p in innocents:
        assert p.task is not None


def test_assign_roles_innocent_tasks_are_distinct_within_a_round():
    # Looped, not a single call: the Innocent pool deliberately holds the
    # mention-any sentinel twice (see tasks.py), so a single unlucky
    # shuffle had roughly a 1-in-30 chance of handing two Innocents the
    # same id even when everything else was working correctly -
    # ShuffleBag.draw_many now guards against that directly (see its own
    # tests in test_tasks.py), and this checks it holds at real round
    # sizes across enough tries that a regression can't hide in the noise.
    manager = GameManager()
    for i in range(200):
        game = make_game(manager, n_players=8, channel_id=100 + i)  # 1 officer, 1 lawbreaker, 6 innocents
        assign_roles_and_tasks(game, resolver)

        innocents = [p for p in game.players.values() if p.role == Role.INNOCENT]
        task_ids = [p.task.id for p in innocents]
        assert len(task_ids) == len(set(task_ids)), f"innocents in the same round got duplicate tasks: {task_ids}"


def test_assign_roles_many_times_covers_the_mention_sentinel_swap():
    # Mention sentinels are only ~2/30 of each pool, so run this enough
    # times to be confident the swap path (dynamic factory call) runs
    # cleanly and never leaves a raw "placeholder" task assigned to anyone.
    manager = GameManager()
    for i in range(300):
        game = make_game(manager, n_players=5, channel_id=i)
        assign_roles_and_tasks(game, resolver)
        for p in game.players.values():
            if p.task is not None:
                assert p.task.id not in ("DYNAMIC_MENTION_SPECIFIC", "DYNAMIC_MENTION_ANY")
                assert "placeholder" not in p.task.description


def test_gamemanager_create_get_remove():
    manager = GameManager()
    assert manager.get(42) is None
    game = manager.create(42, guild_id=1, host_id=7, host_display="Host")
    assert manager.get(42) is game
    assert 7 in game.players
    manager.remove(42)
    assert manager.get(42) is None


def test_assign_roles_classic_mode_never_adds_special_roles():
    # Classic is the default and must reproduce v1 exactly - a lobby that
    # never touches /config should never see a special-role id populated.
    manager = GameManager()
    for n in range(3, 11):
        game = make_game(manager, n_players=n, channel_id=n)
        assign_roles_and_tasks(game, resolver)
        assert game.detective_id is None
        assert game.snitch_id is None
        assert game.vigilante_id is None
        assert game.double_agent_id is None
        assert game.mimic_id is None
        assert game.mimic_roots_for is None
        roles = {p.role for p in game.players.values()}
        assert roles <= {Role.OFFICER, Role.LAWBREAKER, Role.INNOCENT}


def test_assign_roles_chaos_mode_fills_out_the_special_roles():
    manager = GameManager()
    game = make_game(manager, n_players=8, mode=Mode.CHAOS)  # unlocks all 4 Chaos extras
    assign_roles_and_tasks(game, resolver)

    for uid, role in [
        (game.detective_id, Role.DETECTIVE),
        (game.snitch_id, Role.SNITCH),
        (game.vigilante_id, Role.VIGILANTE),
        (game.double_agent_id, Role.DOUBLE_AGENT),
    ]:
        assert uid is not None, f"expected {role} to be assigned at 8 players in Chaos mode"
        assert game.players[uid].role == role
        assert game.players[uid].task is not None  # extra roles get a normal decoy task too
    assert game.mimic_id is None  # Mimic is Crimson-only regardless of player count

    # Every seat is still filled exactly once.
    roles = [p.role for p in game.players.values()]
    assert roles.count(Role.OFFICER) == 1
    assert roles.count(Role.LAWBREAKER) == 1
    assert len(roles) == 8


def test_detective_lead_scales_with_player_count_and_always_includes_the_lawbreaker():
    manager = GameManager()
    # Chaos makes the Detective available from 3 players up, so this
    # covers the whole range the formula needs to handle.
    for n in range(3, 11):
        for i in range(20):
            game = make_game(manager, n_players=n, channel_id=(n * 100) + i, mode=Mode.CHAOS)
            assign_roles_and_tasks(game, resolver)
            if game.detective_id is None:
                continue
            lead = game.detective_lead
            assert game.lawbreaker_id in lead
            assert len(lead) == len(set(lead)), f"n={n}: duplicate name in the lead: {lead}"
            assert game.detective_id not in lead, "the Detective isn't their own lead"
            expected_size = min(detective_lead_size(n), n - 1)
            assert len(lead) == expected_size, f"n={n}: expected lead size {expected_size}, got {len(lead)}"


def test_detective_lead_size_matches_the_documented_examples():
    # 3 at 5 players, 4 at 6, 5 at 8, 6 at 10+ - the exact scaling asked for.
    assert detective_lead_size(5) == 3
    assert detective_lead_size(6) == 4
    assert detective_lead_size(8) == 5
    assert detective_lead_size(10) == 6


def test_detective_lead_can_include_or_exclude_the_officer():
    # The Officer is just one more candidate in the decoy pool, with no
    # special treatment - so across enough tries, the lead should
    # sometimes name the Officer and sometimes not.
    manager = GameManager()
    saw_officer_in_lead = False
    saw_officer_out_of_lead = False
    for i in range(150):
        game = make_game(manager, n_players=6, channel_id=5000 + i, mode=Mode.WILDCARD)
        assign_roles_and_tasks(game, resolver)
        if game.detective_id is None:
            continue
        if game.officer_id in game.detective_lead:
            saw_officer_in_lead = True
        else:
            saw_officer_out_of_lead = True
    assert saw_officer_in_lead, "expected the Officer to show up in the lead at least once across 150 tries"
    assert saw_officer_out_of_lead, "expected the Officer to be left out of the lead at least once across 150 tries"


def test_mimic_roots_for_is_set_only_when_mimic_is_in_play():
    manager = GameManager()
    saw_mimic = False
    for i in range(60):
        game = make_game(manager, n_players=9, channel_id=2000 + i, mode=Mode.CRIMSON)
        assign_roles_and_tasks(game, resolver)
        if game.mimic_id is not None:
            saw_mimic = True
            assert game.mimic_roots_for in ("Officer", "Lawbreaker")
            assert game.players[game.mimic_id].role == Role.MIMIC
        else:
            assert game.mimic_roots_for is None
    assert saw_mimic, "expected Crimson at 9 players to include the Mimic at least once across 60 tries"


def test_task_content_default_is_sfw_for_backward_compatibility():
    # No content argument at all - mirrors any pre-existing caller.
    manager = GameManager()
    game = make_game(manager, n_players=5)
    assign_roles_and_tasks(game, resolver)
    sfw_crime_ids = {t.id for t in CRIME_TASKS if not t.id.startswith("DYNAMIC_")}
    assert game.players[game.lawbreaker_id].task.id in sfw_crime_ids or "mention" in game.players[game.lawbreaker_id].task.id


def test_task_content_18plus_draws_only_from_18plus_pools():
    manager = GameManager()
    crime_18_ids = {t.id for t in CRIME_TASKS_18PLUS if not t.id.startswith("DYNAMIC_")}
    innocent_18_ids = {t.id for t in INNOCENT_TASKS_18PLUS if not t.id.startswith("DYNAMIC_")}
    for i in range(30):
        game = make_game(manager, n_players=5, channel_id=3000 + i, task_content=TaskContent.EIGHTEEN_PLUS)
        assign_roles_and_tasks(game, resolver)
        lawbreaker_task_id = game.players[game.lawbreaker_id].task.id
        assert lawbreaker_task_id in crime_18_ids or lawbreaker_task_id.startswith("crime_mention_")
        for p in game.players.values():
            if p.role == Role.INNOCENT:
                assert p.task.id in innocent_18_ids or p.task.id == "innocent_mention_any"


def test_task_content_mixed_draws_from_both_sfw_and_18plus_pools():
    manager = GameManager()
    sfw_ids = {t.id for t in CRIME_TASKS if not t.id.startswith("DYNAMIC_")}
    plus_ids = {t.id for t in CRIME_TASKS_18PLUS if not t.id.startswith("DYNAMIC_")}
    seen_sfw = False
    seen_18plus = False
    for i in range(200):
        game = make_game(manager, n_players=3, channel_id=4000 + i, task_content=TaskContent.MIXED)
        assign_roles_and_tasks(game, resolver)
        tid = game.players[game.lawbreaker_id].task.id
        if tid in sfw_ids:
            seen_sfw = True
        elif tid in plus_ids:
            seen_18plus = True
    assert seen_sfw and seen_18plus, "expected Mixed content to draw from both the SFW and 18+ crime pools across 200 tries"


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
