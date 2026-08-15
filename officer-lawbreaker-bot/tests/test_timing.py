"""Unit tests for game/timing.py - pure functions, no discord.py needed.

Run directly:   python tests/test_timing.py
Or with pytest: pytest tests/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from game.timing import render_progress_bar, warning_offset_seconds  # noqa: E402


def test_render_progress_bar_bounds():
    assert render_progress_bar(0.0) == "\u2591" * 12
    assert render_progress_bar(1.0) == "\u2588" * 12
    assert render_progress_bar(-5.0) == "\u2591" * 12  # clamps below 0
    assert render_progress_bar(5.0) == "\u2588" * 12   # clamps above 1


def test_render_progress_bar_midpoint():
    bar = render_progress_bar(0.5, length=10)
    assert bar == "\u2588" * 5 + "\u2591" * 5


def test_render_progress_bar_custom_length():
    bar = render_progress_bar(0.25, length=4)
    assert len(bar) == 4
    assert bar.count("\u2588") == 1


def test_warning_offset_short_round_hits_floor():
    # 2 minute round: 10% = 12s, above the 10s floor, so it should be ~12s.
    offset = warning_offset_seconds(120)
    assert 10.0 <= offset <= 15.0


def test_warning_offset_very_short_round_hits_floor_exactly():
    # A hypothetical very short round: 10% would be under the floor.
    offset = warning_offset_seconds(60)
    assert offset == 10.0


def test_warning_offset_long_round_hits_cap():
    # 24 hour round: 10% would be 2.4 hours, way above the 5 minute cap.
    offset = warning_offset_seconds(24 * 60 * 60)
    assert offset == 300.0


def test_warning_offset_mid_round_is_proportional():
    offset = warning_offset_seconds(1000)  # 10% = 100s, within floor/cap
    assert offset == 100.0


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
