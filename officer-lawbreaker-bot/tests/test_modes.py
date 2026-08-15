"""Unit tests for game/modes.py - the mode -> extra-role-pool logic, plus
completeness checks on the descriptive copy used by /modes and /roles.

Run directly:   python tests/test_modes.py
Or with pytest: pytest tests/
"""

import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game.constants import MAX_PLAYERS, MIN_PLAYERS, Mode, Role  # noqa: E402
from game.modes import (  # noqa: E402
    MODE_EMOJI,
    MODE_INFO,
    ROLE_INFO,
    ROLE_SECTIONS,
    detective_lead_size,
    extra_roles_for_mode,
)


def test_classic_never_adds_extra_roles():
    for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
        assert extra_roles_for_mode(Mode.CLASSIC, n) == []


def test_extra_roles_never_exceed_available_slots():
    for mode in Mode:
        for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
            roles = extra_roles_for_mode(mode, n)
            assert len(roles) <= max(n - 2, 0)


def test_extra_roles_are_always_distinct():
    rng = random.Random(0)
    for mode in Mode:
        for n in range(MIN_PLAYERS, MAX_PLAYERS + 1):
            for _ in range(20):
                roles = extra_roles_for_mode(mode, n, rng=rng)
                assert len(roles) == len(set(roles)), f"{mode} n={n} produced a duplicate: {roles}"


def test_wildcard_gates_detective_and_snitch_by_player_count():
    assert extra_roles_for_mode(Mode.WILDCARD, 3) == []
    assert Role.DETECTIVE in extra_roles_for_mode(Mode.WILDCARD, 4)
    assert Role.SNITCH not in extra_roles_for_mode(Mode.WILDCARD, 4)
    six = extra_roles_for_mode(Mode.WILDCARD, 6)
    assert Role.DETECTIVE in six and Role.SNITCH in six


def test_chaos_unlocks_at_least_as_much_as_wildcard_at_the_same_size():
    for n in (4, 6, 8, 10):
        wildcard = set(extra_roles_for_mode(Mode.WILDCARD, n))
        chaos = set(extra_roles_for_mode(Mode.CHAOS, n))
        assert len(chaos) >= len(wildcard)


def test_chaos_vigilante_needs_eight_double_agent_needs_six():
    assert Role.DOUBLE_AGENT not in extra_roles_for_mode(Mode.CHAOS, 5)
    assert Role.DOUBLE_AGENT in extra_roles_for_mode(Mode.CHAOS, 6)
    assert Role.VIGILANTE not in extra_roles_for_mode(Mode.CHAOS, 7)
    assert Role.VIGILANTE in extra_roles_for_mode(Mode.CHAOS, 8)


def test_crimson_mimic_is_never_guaranteed_before_six_but_always_present_from_seven():
    for n in (3, 4, 5):
        for i in range(30):
            assert Role.MIMIC not in extra_roles_for_mode(Mode.CRIMSON, n, rng=random.Random(i))
    # At exactly 6 the 5-role candidate pool doesn't all fit (only 4
    # slots) - the Mimic should show up sometimes but not every time.
    six_results = [Role.MIMIC in extra_roles_for_mode(Mode.CRIMSON, 6, rng=random.Random(i)) for i in range(200)]
    assert any(six_results), "expected the Mimic to appear at least once at 6 players across 200 shuffles"
    assert not all(six_results), "expected the Mimic to be excluded at least once at 6 players across 200 shuffles"
    # From 7 players up, all 5 candidates fit in the available slots, so
    # the Mimic (and everything else) is always included.
    for n in (7, 8, 9, 10):
        for i in range(20):
            assert Role.MIMIC in extra_roles_for_mode(Mode.CRIMSON, n, rng=random.Random(i))


def test_mode_info_and_role_info_cover_every_enum_member():
    assert set(MODE_INFO) == set(Mode)
    assert set(MODE_EMOJI) == set(Mode)
    assert set(ROLE_INFO) == set(Role)


def test_role_sections_cover_every_role_exactly_once():
    listed = [role for _, roles in ROLE_SECTIONS for role in roles]
    assert set(listed) == set(Role)
    assert len(listed) == len(set(listed))


def test_detective_lead_size_formula():
    # The exact scaling asked for: 3 at 5 players, 4 at 6, 5 at 8, 6 at
    # 10+, following n_players // 2 + 1. Also check it's monotonically
    # non-decreasing across the whole valid player range, since a bigger
    # lobby should never get a *smaller* lead than a smaller one.
    assert detective_lead_size(5) == 3
    assert detective_lead_size(6) == 4
    assert detective_lead_size(8) == 5
    assert detective_lead_size(10) == 6
    sizes = [detective_lead_size(n) for n in range(MIN_PLAYERS, MAX_PLAYERS + 1)]
    assert sizes == sorted(sizes)


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
