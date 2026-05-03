"""Broad Gamma market universe scanner for crypto paper campaigns."""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_polymarket.crypto.crypto_market_classifier import infer_symbol_from_text
from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
from hermes_polymarket.crypto.strike_market import parse_strike_market
from hermes_polymarket.crypto.updown_discovery import UPDOWN_PATTERNS
from hermes_polymarket.data_sources.base import now_ms
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.signals.source_consensus import ConsensusPrice


MARKET_TYPES = ("up_down", "above_strike", "below_strike", "multi_strike_event", "unsupported")
STRIKE_RE = re.compile(r"\b(above|below|over|under)\b|[$]\s*\d|\b\d+(?:[.,]\d+)?[kmb]?\b")


@dataclass(frozen=True)
class UniverseCandidate:
    event_slug: str
    event_title: str
    question: str
    slug: str
    condition_id: str
    symbol: str
    market_type: str
    score: float
    reasons: tuple[str, ...]
    yes_token_id: str | None
    no_token_id: str | None
    up_token_id: str | None
    down_token_id: str | None
    strike_price: float | None
    comparator: str | None
    outcomes: tuple[str, ...]
    end_date: str | None
    active: bool
    closed: bool
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_slug": self.event_slug,
            "event_title": self.event_title,
            "question": self.question,
            "slug": self.slug,
            "condition_id": self.condition_id,
            "symbol": self.symbol,
            "market_type": self.market_type,
            "score": self.score,
            "reasons": list(self.reasons),
            "yes_token_id": self.yes_token_id,
            "no_token_id": self.no_token_id,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "strike_price": self.strike_price,
            "comparator": self.comparator,
            "outcomes": list(self.outcomes),
            "end_date": self.end_date,
            "active": self.active,
            "closed": self.closed,
            "source": self.source,
        }


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _text(market: dict[str, Any], event: dict[str, Any] | None = None) -> str:
    event = event or {}
    return " ".join(
        str(value or "")
        for value in (
            market.get("question") or market.get("title"),
            market.get("slug"),
            event.get("title"),
            event.get("slug"),
        )
    ).lower()


def _outcomes(market: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(item) for item in _coerce_list(market.get("outcomes")) if str(item))


def _token_ids(market: dict[str, Any]) -> tuple[str, ...]:
    tokens = _coerce_list(market.get("clobTokenIds") or market.get("clob_token_ids"))
    if tokens:
        return tuple(str(item) for item in tokens if str(item))
    token_rows = _coerce_list(market.get("tokens"))
    out: list[str] = []
    for row in token_rows:
        if isinstance(row, dict):
            token = row.get("token_id") or row.get("id")
            if token:
                out.append(str(token))
        elif row:
            out.append(str(row))
    return tuple(out)


def _float_field(market: dict[str, Any], *keys: str) -> float:
    for key in keys:
        value = market.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 0.0


def _future_end_date(value: Any) -> bool:
    if not value:
        return False
    try:
        text = str(value).replace("Z", "+00:00")
        end_date = datetime.fromisoformat(text)
    except ValueError:
        return False
    if end_date.tzinfo is None:
        end_date = end_date.replace(tzinfo=timezone.utc)
    return end_date > datetime.now(timezone.utc)


def _is_updown_text(text: str) -> bool:
    return any(pattern in text for pattern in UPDOWN_PATTERNS)


def _is_strike_text(text: str) -> bool:
    return STRIKE_RE.search(text) is not None and any(word in text for word in ("above", "below", "over", "under", "$"))


def _infer_direction_tokens(outcomes: tuple[str, ...], token_ids: tuple[str, ...], question: str) -> tuple[str | None, str | None]:
    if len(outcomes) != 2 or len(token_ids) != 2:
        return None, None

    lowered = [outcome.strip().lower() for outcome in outcomes]

    def direction(text: str) -> str | None:
        if text in {"up", "higher", "above", "rise"}:
            return "up"
        if text in {"down", "lower", "below", "fall"}:
            return "down"
        return None

    directions = [direction(item) for item in lowered]
    if directions == ["up", "down"]:
        return token_ids[0], token_ids[1]
    if directions == ["down", "up"]:
        return token_ids[1], token_ids[0]

    # Gamma often exposes binary up/down markets as Yes/No. For this market
    # family, manual seeds have used Yes as the up-equivalent token.
    q = question.lower()
    if lowered == ["yes", "no"] and _is_updown_text(q):
        return token_ids[0], token_ids[1]
    if lowered == ["no", "yes"] and _is_updown_text(q):
        return token_ids[1], token_ids[0]

    return None, None


def classify_market_type(market: dict[str, Any], *, event: dict[str, Any] | None = None, multi_strike_event: bool = False) -> tuple[str, str | None]:
    text = _text(market, event)
    symbol = infer_symbol_from_text(text)
    if symbol is None:
        return "unsupported", None
    if _is_updown_text(text) and not _is_strike_text(text):
        return "up_down", symbol
    if "above" in text or "over" in text:
        return "above_strike", symbol
    if "below" in text or "under" in text:
        return "below_strike", symbol
    if multi_strike_event and _is_strike_text(text):
        return "multi_strike_event", symbol
    return "unsupported", symbol


def build_candidate(
    market: dict[str, Any],
    *,
    event: dict[str, Any] | None = None,
    source: str,
    allowed_symbols: set[str] | None = None,
    multi_strike_event: bool = False,
) -> UniverseCandidate | None:
    market_type, symbol = classify_market_type(market, event=event, multi_strike_event=multi_strike_event)
    if symbol is None:
        return None
    if allowed_symbols is not None and symbol not in allowed_symbols:
        return None

    text = _text(market, event)
    strike = parse_strike_market(text)
    if strike is not None:
        market_type = strike.market_type
    target = parse_multi_strike_target(text)
    if strike is None and target is not None:
        market_type = target.market_type
    outcomes = _outcomes(market)
    token_ids = _token_ids(market)
    active = bool(market.get("active", False))
    closed = bool(market.get("closed", False))
    condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
    future_end_date = _future_end_date(market.get("endDate"))

    score = 0.0
    reasons: list[str] = []
    if active and not closed and future_end_date:
        score += 0.2
        reasons.append("active")
    elif active and not closed:
        reasons.append("end_date_past_or_missing")
    if condition_id:
        score += 0.1
        reasons.append("condition_id")
    if len(outcomes) == 2:
        score += 0.15
        reasons.append("two_outcomes")
    if len(token_ids) == 2:
        score += 0.2
        reasons.append("clob_tokens")
    if symbol:
        score += 0.1
        reasons.append("crypto_symbol")
    if market_type == "up_down":
        score += 0.2
        reasons.append("crypto_updown_text")
    elif market_type in {"above_strike", "below_strike", "multi_strike_event"}:
        score += 0.08
        reasons.append("crypto_strike_text")
    if future_end_date:
        score += 0.03
        reasons.append("end_date")
    if _float_field(market, "volume24hr", "volume_24hr", "liquidity", "liquidityNum", "volume") > 0:
        score += 0.02
        reasons.append("volume_or_liquidity")

    up_token_id: str | None = None
    down_token_id: str | None = None
    if market_type == "up_down":
        up_token_id, down_token_id = _infer_direction_tokens(outcomes, token_ids, text)
        if up_token_id and down_token_id:
            score += 0.05
            reasons.append("direction_tokens")
        else:
            reasons.append("direction_mapping_ambiguous")

    if not future_end_date:
        score = min(score, 0.49)

    yes_token_id = token_ids[0] if len(token_ids) >= 1 else None
    no_token_id = token_ids[1] if len(token_ids) >= 2 else None
    return UniverseCandidate(
        event_slug=str((event or {}).get("slug") or ""),
        event_title=str((event or {}).get("title") or ""),
        question=str(market.get("question") or market.get("title") or ""),
        slug=str(market.get("slug") or ""),
        condition_id=condition_id,
        symbol=symbol,
        market_type=market_type,
        score=round(min(score, 1.0), 4),
        reasons=tuple(reasons),
        yes_token_id=yes_token_id,
        no_token_id=no_token_id,
        up_token_id=up_token_id,
        down_token_id=down_token_id,
        strike_price=strike.strike_price if strike is not None else target.target_price if target is not None else None,
        comparator=strike.comparator if strike is not None else target.target_direction if target is not None else None,
        outcomes=outcomes,
        end_date=str(market.get("endDate") or "") or None,
        active=active,
        closed=closed,
        source=source,
    )


def _dedupe_markets(candidates: list[UniverseCandidate]) -> list[UniverseCandidate]:
    deduped: dict[str, UniverseCandidate] = {}
    for candidate in candidates:
        key = candidate.condition_id or candidate.slug
        current = deduped.get(key)
        if current is None or candidate.score > current.score:
            deduped[key] = candidate
    return list(deduped.values())


def scan_market_universe(
    *,
    events: list[dict[str, Any]],
    markets: list[dict[str, Any]],
    symbols: set[str] | None = None,
) -> dict[str, Any]:
    candidates: list[UniverseCandidate] = []
    scanned_markets = 0

    for event in events:
        if not isinstance(event, dict):
            continue
        event_markets = [market for market in (event.get("markets") or []) if isinstance(market, dict)]
        strike_count = sum(1 for market in event_markets if _is_strike_text(_text(market, event)) and infer_symbol_from_text(_text(market, event)))
        multi_strike_event = strike_count > 1
        for market in event_markets:
            scanned_markets += 1
            candidate = build_candidate(market, event=event, source="events", allowed_symbols=symbols, multi_strike_event=multi_strike_event)
            if candidate is not None:
                candidates.append(candidate)

    for market in markets:
        if not isinstance(market, dict):
            continue
        scanned_markets += 1
        candidate = build_candidate(market, source="markets", allowed_symbols=symbols)
        if candidate is not None:
            candidates.append(candidate)

    deduped = _dedupe_markets(candidates)
    classified = Counter(candidate.market_type for candidate in deduped)
    for market_type in MARKET_TYPES:
        classified.setdefault(market_type, 0)
    sorted_candidates = sorted(deduped, key=lambda row: (row.score, row.market_type == "up_down"), reverse=True)

    return {
        "mode": "measurement_paper_only",
        "scanned_events": len(events),
        "scanned_markets": scanned_markets,
        "classified": dict(classified),
        "candidates": [candidate.to_dict() for candidate in sorted_candidates],
        "top_candidates": [candidate.to_dict() for candidate in sorted_candidates[:20]],
    }


def fetch_gamma_universe(
    gamma: GammaClient,
    *,
    limit_events: int,
    limit_markets: int,
    orders: tuple[str, ...] = ("volume_24hr", "liquidity", "start_date", "end_date"),
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    events_by_slug: dict[str, dict[str, Any]] = {}
    markets_by_key: dict[str, dict[str, Any]] = {}

    def page_limit(remaining: int) -> int:
        return max(1, min(300, remaining))

    for order in orders:
        remaining = max(0, limit_events - len(events_by_slug))
        offset = 0
        while remaining > 0:
            batch_limit = page_limit(remaining)
            page = gamma.list_events(active="true", closed="false", order=order, ascending="false", limit=batch_limit, offset=offset)
            if not page:
                break
            for event in page:
                if isinstance(event, dict):
                    key = str(event.get("slug") or event.get("id") or len(events_by_slug))
                    events_by_slug.setdefault(key, event)
            if len(page) < batch_limit:
                break
            offset += batch_limit
            remaining = max(0, limit_events - len(events_by_slug))

    for order in orders:
        remaining = max(0, limit_markets - len(markets_by_key))
        offset = 0
        while remaining > 0:
            batch_limit = page_limit(remaining)
            page = gamma.list_markets(active="true", closed="false", order=order, ascending="false", limit=batch_limit, offset=offset)
            if not page:
                break
            for market in page:
                if isinstance(market, dict):
                    key = str(market.get("conditionId") or market.get("slug") or len(markets_by_key))
                    markets_by_key.setdefault(key, market)
            if len(page) < batch_limit:
                break
            offset += batch_limit
            remaining = max(0, limit_markets - len(markets_by_key))

    return list(events_by_slug.values()), list(markets_by_key.values())


def write_universe_scan(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def load_universe_scan(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def filter_universe_candidates(
    payload: dict[str, Any],
    *,
    market_type: str | None = None,
    min_score: float = 0.0,
    limit: int = 20,
) -> list[dict[str, Any]]:
    rows = payload.get("candidates") or payload.get("top_candidates") or []
    filtered = [
        row
        for row in rows
        if isinstance(row, dict)
        and (market_type is None or row.get("market_type") == market_type)
        and float(row.get("score") or 0.0) >= min_score
    ]
    filtered.sort(key=lambda row: float(row.get("score") or 0.0), reverse=True)
    return filtered[:limit]


def candidate_to_watchlist_row(candidate: dict[str, Any], *, reference: ConsensusPrice | None, duration_seconds: int) -> dict[str, Any] | None:
    market_type = str(candidate.get("market_type") or "up_down")
    if market_type not in {"up_down", "above_strike", "below_strike"}:
        return None
    up_token_id = candidate.get("up_token_id")
    down_token_id = candidate.get("down_token_id")
    yes_token_id = candidate.get("yes_token_id")
    no_token_id = candidate.get("no_token_id")
    if market_type == "up_down" and not all((up_token_id, down_token_id, yes_token_id, no_token_id)):
        return None
    if market_type in {"above_strike", "below_strike"} and not all((yes_token_id, no_token_id, candidate.get("strike_price"), candidate.get("comparator"))):
        return None
    start_ms = now_ms()
    end_ts_ms = start_ms + duration_seconds * 1000
    raw: dict[str, Any] = {
        "universe_import": True,
        "market_type": market_type,
        "strike_price": candidate.get("strike_price"),
        "comparator": candidate.get("comparator"),
        "universe_score": candidate.get("score"),
        "universe_reasons": candidate.get("reasons") or [],
    }
    if reference is not None:
        raw.update(
            {
                "reference_price": reference.price,
                "window_start_ts": start_ms // 1000,
                "window_end_ts": end_ts_ms // 1000,
                "consensus_sources": list(reference.sources),
                "max_deviation_pct": reference.max_deviation_pct,
            }
        )
    return {
        "condition_id": candidate["condition_id"],
        "slug": candidate["slug"],
        "question": candidate.get("question") or candidate["slug"],
        "symbol": candidate["symbol"],
        "yes_token_id": yes_token_id,
        "no_token_id": no_token_id,
        "up_token_id": up_token_id,
        "down_token_id": down_token_id,
        "market_type": market_type,
        "strike_price": candidate.get("strike_price"),
        "comparator": candidate.get("comparator"),
        "resolution_ts": end_ts_ms // 1000,
        "direction_map": {"up": up_token_id, "down": down_token_id} if up_token_id and down_token_id else {},
        "active": True,
        "discovered_at_ms": start_ms,
        "end_ts_ms": end_ts_ms,
        "raw": raw,
    }
