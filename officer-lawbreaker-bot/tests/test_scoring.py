"""Unit tests for game/scoring.py - individual-performance point
calculation, Session, and SessionManager.

Games are built by hand here (not via assign_roles_and_tasks) so each
test controls exactly the fields score_round reads, independent of any
randomness in role assignment.

Run directly:   python tests/test_scoring.py
Or with pytest: pytest tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game.constants import Role  # noqa: E402
from game.scoring import (  # noqa: E402
    DOUBLE_AGENT_COVER_POINTS,
    LAWBREAKER_EVADED_POINTS,
    MIMIC_CORRECT_ROOT_POINTS,
    OFFICER_CORRECT_CATCH_POINTS,
    TASK_COMPLETE_POINTS,
    VIGILANTE_CORRECT_HUNCH_POINTS,
    Session,
    SessionManager,
    score_round,
)
from game.state import Game, PlayerState  # noqa: E402


def make_game():
    """An Officer, a Lawbreaker, and one Innocent (uid 1002) - the
    Innocent's uid doubles as the "extra role" slot in tests that need
    a Vigilante/Double Agent/Mimic, since only one of those is ever in
    play in a given scenario here."""
    game = Game(channel_id=1, guild_id=99, host_id=1000)
    game.officer_id = 1000
    game.lawbreaker_id = 1001
    game.players[1000] = PlayerState(user_id=1000, display_name="Officer", role=Role.OFFICER)
    game.players[1001] = PlayerState(user_id=1001, display_name="Lawbreaker", role=Role.LAWBREAKER)
    game.players[1002] = PlayerState(user_id=1002, display_name="Third", role=Role.INNOCENT)
    return game


def derive_winner(game, shot_user_id):
    """Mirrors resolve_round's winner derivation in cog.py, so every
    scenario below is one score_round could actually be handed in
    production, not just an arbitrary (game, winner, shot) triple."""
    if shot_user_id is not None:
        return "officer" if shot_user_id == game.lawbreaker_id else "lawbreaker"
    return "lawbreaker" if game.players[game.lawbreaker_id].task_complete else "officer"


# --------------------------------------------------------------------------
# score_round - Officer
# --------------------------------------------------------------------------

def test_officer_earns_points_for_a_correct_catch():
    game = make_game()
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[game.officer_id] == OFFICER_CORRECT_CATCH_POINTS


def test_officer_earns_nothing_for_a_wrong_guess():
    game = make_game()
    shot = 1002  # shot the Innocent, not the Lawbreaker
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[game.officer_id] == 0


def test_officer_earns_nothing_when_time_runs_out_with_no_shot():
    game = make_game()
    points = score_round(game, derive_winner(game, None), None)
    assert points[game.officer_id] == 0


# --------------------------------------------------------------------------
# score_round - Lawbreaker
# --------------------------------------------------------------------------

def test_lawbreaker_earns_task_points_when_crime_completed():
    game = make_game()
    game.players[game.lawbreaker_id].task_complete = True
    points = score_round(game, derive_winner(game, None), None)
    assert points[game.lawbreaker_id] == TASK_COMPLETE_POINTS


def test_lawbreaker_earns_evasion_bonus_on_a_wrong_shot():
    game = make_game()
    game.players[game.lawbreaker_id].task_complete = True
    shot = 1002  # Officer shot the Innocent instead
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[game.lawbreaker_id] == TASK_COMPLETE_POINTS + LAWBREAKER_EVADED_POINTS


def test_lawbreaker_gets_no_evasion_bonus_when_correctly_caught():
    game = make_game()
    game.players[game.lawbreaker_id].task_complete = True
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[game.lawbreaker_id] == TASK_COMPLETE_POINTS


def test_lawbreaker_gets_no_evasion_bonus_from_a_timeout_with_no_shot_fired():
    # Timing out isn't "evading" anything - no one even took a shot.
    game = make_game()
    game.players[game.lawbreaker_id].task_complete = False
    points = score_round(game, derive_winner(game, None), None)
    assert points[game.lawbreaker_id] == 0


# --------------------------------------------------------------------------
# score_round - Innocent (the shared task-completion baseline)
# --------------------------------------------------------------------------

def test_innocent_earns_task_points_only_if_their_task_is_done():
    game = make_game()
    game.players[1002].task_complete = True
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == TASK_COMPLETE_POINTS


def test_innocent_earns_nothing_if_their_task_is_not_done():
    game = make_game()
    game.players[1002].task_complete = False
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == 0


# --------------------------------------------------------------------------
# score_round - Vigilante
# --------------------------------------------------------------------------

def test_vigilante_earns_bonus_for_a_correct_hunch():
    game = make_game()
    game.vigilante_id = 1002
    game.vigilante_guess_id = game.lawbreaker_id
    game.players[1002].task_complete = True
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == TASK_COMPLETE_POINTS + VIGILANTE_CORRECT_HUNCH_POINTS


def test_vigilante_earns_no_bonus_for_a_missing_or_wrong_hunch():
    game = make_game()
    game.vigilante_id = 1002
    game.vigilante_guess_id = None  # never locked one in
    game.players[1002].task_complete = True
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == TASK_COMPLETE_POINTS


# --------------------------------------------------------------------------
# score_round - Double Agent
# --------------------------------------------------------------------------

def test_double_agent_earns_cover_bonus_when_their_task_saved_the_crime():
    game = make_game()
    game.double_agent_id = 1002
    game.lawbreaker_covered_by_double_agent = True
    game.players[1002].task_complete = True
    game.players[game.lawbreaker_id].task_complete = True  # the interference is what completed it
    points = score_round(game, derive_winner(game, None), None)
    assert points[1002] == TASK_COMPLETE_POINTS + DOUBLE_AGENT_COVER_POINTS


def test_double_agent_earns_no_cover_bonus_when_never_needed():
    game = make_game()
    game.double_agent_id = 1002
    game.lawbreaker_covered_by_double_agent = False
    game.players[1002].task_complete = True
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == TASK_COMPLETE_POINTS


# --------------------------------------------------------------------------
# score_round - Mimic
# --------------------------------------------------------------------------

def test_mimic_earns_bonus_when_their_secret_root_wins():
    game = make_game()
    game.mimic_id = 1002
    game.mimic_roots_for = "Officer"
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == MIMIC_CORRECT_ROOT_POINTS


def test_mimic_earns_no_bonus_when_their_secret_root_loses():
    game = make_game()
    game.mimic_id = 1002
    game.mimic_roots_for = "Lawbreaker"
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert points[1002] == 0


# --------------------------------------------------------------------------
# score_round - every player gets an entry, 0 included
# --------------------------------------------------------------------------

def test_every_player_gets_a_points_entry_even_when_it_is_zero():
    game = make_game()
    shot = game.lawbreaker_id
    points = score_round(game, derive_winner(game, shot), shot)
    assert set(points) == set(game.players)
    assert points[1002] == 0  # Innocent, task not done


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------

def test_session_add_round_accumulates_across_multiple_rounds():
    session = Session(channel_id=1, started_by=1000)
    session.add_round({1000: 2, 1001: 0})
    session.add_round({1000: 1, 1002: 3})
    assert session.scores == {1000: 3, 1001: 0, 1002: 3}
    assert session.games_played == 2


def test_session_standings_sorted_highest_first():
    session = Session(channel_id=1, started_by=1000)
    session.add_round({1000: 1, 1001: 5, 1002: 3})
    assert session.standings() == [(1001, 5), (1002, 3), (1000, 1)]


# --------------------------------------------------------------------------
# SessionManager
# --------------------------------------------------------------------------

def test_session_manager_create_get_remove():
    manager = SessionManager()
    assert manager.get(1) is None
    session = manager.create(1, started_by=1000)
    assert manager.get(1) is session
    manager.remove(1)
    assert manager.get(1) is None


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
