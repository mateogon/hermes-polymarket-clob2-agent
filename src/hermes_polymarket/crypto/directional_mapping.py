"""Directional token selection for up/down crypto markets."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DirectionalToken:
    symbol: str
    condition_id: str
    token_id: str
    outcome: str
    direction: str


def normalize_outcome_direction(outcome: str) -> str | None:
    text = outcome.strip().lower()
    if text in {"up", "higher", "above", "yes", "rise"}:
        return "up"
    if text in {"down", "lower", "below", "no", "fall"}:
        return "down"
    return None


def desired_direction_from_move(move_pct: float) -> str:
    return "up" if move_pct > 0 else "down"


def select_directional_token(
    *,
    tokens: list[DirectionalToken],
    symbol: str,
    move_pct: float,
) -> DirectionalToken | None:
    wanted = desired_direction_from_move(move_pct)
    matches = [token for token in tokens if token.symbol == symbol and token.direction == wanted]
    if len(matches) == 1:
        return matches[0]
    return None
