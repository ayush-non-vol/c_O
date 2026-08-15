"""Pure helpers for rendering time/progress in the UI. No discord.py
dependency, so these are trivial to unit test directly.
"""

from __future__ import annotations


def render_progress_bar(fraction: float, length: int = 12) -> str:
    """A block-character progress bar, e.g. '████████░░░░' for ~67%."""
    fraction = max(0.0, min(1.0, fraction))
    filled = round(fraction * length)
    return "\u2588" * filled + "\u2591" * (length - filled)


def warning_offset_seconds(round_seconds: float) -> float:
    """How long before round end to fire the single 'down to the wire'
    ping: 10% of the round length, floored at 10s so short rounds still
    get one, capped at 5 minutes so a 24-hour round doesn't warn hours
    early.
    """
    return min(max(round_seconds * 0.1, 10.0), 300.0)
