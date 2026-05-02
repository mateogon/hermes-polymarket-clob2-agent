"""Command line interface for safe local operation."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from hermes_polymarket.config import load_settings
from hermes_polymarket.execution.live_executor import LiveExecutor
from hermes_polymarket.polymarket.clob_v2_client import ClobV2Client
from hermes_polymarket.polymarket.gamma_client import GammaClient
from hermes_polymarket.storage.db import Database


def _settings():
    return load_settings()


def cmd_audit(_: argparse.Namespace) -> int:
    root = Path(__file__).resolve().parents[2]
    print((root / "repo_audit.md").read_text())
    return 0


def cmd_smoke(_: argparse.Namespace) -> int:
    from scripts.smoke_public_data import run_smoke

    return 0 if run_smoke(_settings()) else 1


def cmd_scan(args: argparse.Namespace) -> int:
    if args.mode != "paper":
        print("Only paper scan is implemented at this stage.")
        return 2
    from scripts.paper_scan import run_paper_scan

    result = run_paper_scan(_settings())
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_signal_weather(args: argparse.Namespace) -> int:
    from hermes_polymarket.signals.weather_signal import make_weather_signal

    signal = make_weather_signal(
        market_id="demo-weather",
        outcome="yes",
        samples=[70, 71, 72, 73, 74, 70, 69],
        low=args.low,
        high=args.high,
    )
    print(json.dumps(signal.__dict__, indent=2, sort_keys=True))
    return 0


def cmd_dry_run(args: argparse.Namespace) -> int:
    from scripts.dry_run_order import run_dry_run

    identifier = args.market_slug or args.condition_id or args.token_id or args.market
    if not identifier:
        print("Dry-run requires --market, --market-slug, --condition-id, or --token-id")
        return 2
    identifier_type = None
    if args.market_slug:
        identifier_type = "slug"
    elif args.condition_id:
        identifier_type = "condition_id"
    elif args.token_id:
        identifier_type = "token_id"
    result = run_dry_run(_settings(), identifier, args.side, args.amount, fixture=args.fixture, identifier_type=identifier_type)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["decision"]["allowed"] else 2


def cmd_portfolio(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        positions = [dict(row) for row in db.open_positions()]
        account = dict(db.account())
        print(json.dumps({"mode": args.mode, "account": account, "positions": positions}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_live(args: argparse.Namespace) -> int:
    executor = LiveExecutor(_settings())
    gate = executor.check_gate(live_flag=args.live)
    if not gate.allowed:
        print(f"Refusing live trading: {gate.reason}")
        return 2
    try:
        executor.place_order(live_flag=args.live)
    except NotImplementedError as exc:
        print(str(exc))
        return 2
    return 0


def cmd_wallet_flow_report(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.wallet_flow import wallet_flow_metrics

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        metrics = wallet_flow_metrics(db, wallet=args.wallet)
        print(json.dumps(metrics.to_dict(), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_fetch(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_fetch import fetch_and_persist_wallet_trades_paginated
    from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    registry = WalletRegistry.load()
    wallet = registry.by_name(args.wallet)
    client = PolymarketDataApi()
    try:
        limit_total = args.limit_total if args.limit_total is not None else args.limit
        page_size = args.page_size if args.page_size is not None else args.limit
        max_pages = args.max_pages if args.max_pages is not None else 1
        sides = [None] if args.side != "all" else ["BUY", "SELL"]
        if args.side in {"buy", "sell"}:
            sides = [args.side.upper()]
        fetch_results = [
            fetch_and_persist_wallet_trades_paginated(
                db,
                client,
                wallet=wallet.address,
                page_size=page_size,
                max_pages=max_pages,
                limit_total=limit_total,
                min_cash=args.min_cash,
                side=side,
            )
            for side in sides
        ]
        payload = {
            "wallet": wallet.name,
            "address": wallet.address,
            "fetched_count": sum(result.fetched_total for result in fetch_results),
            "inserted_count": sum(result.inserted_total for result in fetch_results),
            "duplicate_count": sum(result.duplicate_total for result in fetch_results),
            "side": args.side,
            "pages": [
                {"side": side or "unspecified", **page.__dict__}
                for side, result in zip(sides, fetch_results)
                for page in result.pages
            ],
        }
        if args.json:
            payload["trades"] = [trade.raw for result in fetch_results for trade in result.trades]
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        client.close()
        db.close()
    return 0


def cmd_wallet_flow_replay(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay import replay_wallet_trades
    from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayRunConfig
    from hermes_polymarket.backtest.wallet_replay_storage import insert_replay_run, insert_replay_trade, wallet_trades
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        delays = tuple(int(value) for value in args.delay.split(",") if value.strip())
        trades = wallet_trades(db, wallet.address, limit=args.limit, since_ts=args.since_ts, condition_id=args.condition_id)
        if not trades:
            print("No persisted wallet trades. Run wallet-flow fetch first.")
            return 2
        config = ReplayRunConfig(
            wallet=wallet.address,
            delays_seconds=delays,
            mode=args.mode.replace("-", "_"),
            paper_amount_usd=args.amount,
            exit_model=ExitModel(args.exit_model),
            data_quality=args.mode.replace("-", "_"),
        )
        if config.mode == "local_l2":
            import uuid

            from hermes_polymarket.backtest.wallet_replay_local_l2 import replay_wallet_trades_local_l2, summarize_local_l2_replay

            run_id = f"wallet_replay_{uuid.uuid4().hex[:12]}"
            results = replay_wallet_trades_local_l2(db, trades, config, run_id=run_id)
            summary = summarize_local_l2_replay(results)
        else:
            run_id, results, summary = replay_wallet_trades(trades, config)
        quality = None
        if args.quality_warnings:
            from hermes_polymarket.backtest.replay_quality import replay_quality_warnings

            quality = replay_quality_warnings(results).to_dict()
            summary["quality"] = quality
        insert_replay_run(
            db,
            run_id=run_id,
            wallet=wallet.address,
            mode=config.mode,
            data_quality=config.data_quality,
            delays=list(config.delays_seconds),
            config={"wallet_name": wallet.name, "amount": args.amount, "exit_model": config.exit_model.value, "limit": args.limit},
            metrics=summary,
        )
        for result in results:
            insert_replay_trade(db, result.to_storage_dict())
        artifact_paths = _write_replay_artifacts(run_id, wallet.name, config, summary, results, export_csv=args.export_csv, quality=quality)
        _record_replay_experiment(db, run_id, wallet.name, wallet.address, config, summary, artifact_paths)
        _maybe_create_replay_memory(db, run_id, wallet.address, wallet.name, summary)
        print(json.dumps({"run_id": run_id, "wallet": wallet.name, "summary": summary}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_score(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayTradeResult
    from hermes_polymarket.backtest.wallet_replay_storage import replay_trades, upsert_wallet_score
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry
    from hermes_polymarket.signals.wallet_score import score_wallet

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        rows = replay_trades(db)
        results = [
            ReplayTradeResult(
                replay_trade_id=row["replay_trade_id"],
                run_id=row["run_id"],
                wallet=row["wallet"],
                condition_id=row["condition_id"],
                asset_id=row["asset_id"],
                outcome=row["outcome"],
                delay_seconds=int(row["delay_seconds"]),
                exit_model=ExitModel(row["exit_model"]),
                status=row["status"],
                pnl=row["pnl"],
                roi=row["roi"],
                worse_entry_cents=row["worse_entry_cents"],
                skipped_reason=row["skipped_reason"],
                category=row["category"],
            )
            for row in rows
            if row["wallet"].lower() == wallet.address.lower()
        ]
        score = score_wallet(wallet.address, results)
        upsert_wallet_score(
            db,
            wallet=wallet.address,
            score=score.score,
            components=score.components,
            sample_size=score.sample_size,
            warnings=list(score.warnings),
        )
        print(
            json.dumps(
                {
                    "wallet": wallet.name,
                    "address": wallet.address,
                    "score": score.score,
                    "components": score.components,
                    "sample_size": score.sample_size,
                    "warnings": list(score.warnings),
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
    return 0


def cmd_wallet_flow_leaderboard(_: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay_storage import wallet_scores

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = [
            {
                "wallet": row["wallet"],
                "score": row["score"],
                "sample_size": row["sample_size"],
                "warnings": json.loads(row["warnings_json"] or "[]"),
                "components": json.loads(row["components_json"] or "{}"),
            }
            for row in wallet_scores(db)
        ]
        print(json.dumps({"wallets": rows}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_exit_coverage(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_exit_diagnostics import exit_coverage_report
    from hermes_polymarket.backtest.wallet_replay_storage import wallet_trades
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        trades = wallet_trades(db, wallet.address, limit=args.limit, since_ts=args.since_ts, condition_id=args.condition_id)
        if not trades:
            print("No persisted wallet trades. Run wallet-flow fetch first.")
            return 2
        report = exit_coverage_report(wallet.address, trades).to_dict()
        report["wallet_name"] = wallet.name
        print(json.dumps(report, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def _position_pages(page_size: int, max_pages: int) -> list[tuple[int, int]]:
    return [(page * page_size, page_size) for page in range(max_pages)]


def cmd_wallet_flow_positions_fetch(args: argparse.Namespace) -> int:
    from hermes_polymarket.data_sources.polymarket_positions_api import PolymarketPositionsApi
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry
    from hermes_polymarket.storage.wallet_positions import insert_closed_positions, upsert_current_positions

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    wallet = WalletRegistry.load().by_name(args.wallet)
    client = PolymarketPositionsApi()
    try:
        pages = []
        fetched_total = 0
        inserted_total = 0
        duplicate_total = 0
        for offset, limit in _position_pages(args.page_size, args.max_pages):
            if args.kind == "current":
                rows = client.current_positions(wallet.address, market=args.market, limit=limit, offset=offset)
                inserted = upsert_current_positions(db, rows)
                duplicates = 0
            else:
                rows = client.closed_positions(wallet.address, market=args.market, limit=limit, offset=offset)
                counts = insert_closed_positions(db, rows)
                inserted = counts["inserted"]
                duplicates = counts["duplicates"]
            pages.append({"offset": offset, "fetched": len(rows), "inserted": inserted, "duplicates": duplicates})
            fetched_total += len(rows)
            inserted_total += inserted
            duplicate_total += duplicates
            if len(rows) < limit:
                break
        print(
            json.dumps(
                {
                    "wallet": wallet.name,
                    "address": wallet.address,
                    "kind": args.kind,
                    "fetched_count": fetched_total,
                    "inserted_count": inserted_total,
                    "duplicate_count": duplicate_total,
                    "pages": pages,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        client.close()
        db.close()
    return 0


def cmd_wallet_flow_positions_current(args: argparse.Namespace) -> int:
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry
    from hermes_polymarket.storage.wallet_positions import current_positions

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        print(json.dumps({"wallet": wallet.name, "positions": current_positions(db, wallet.address)[: args.limit]}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_positions_report(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.position_report import closed_position_report, current_position_report, trade_position_coverage
    from hermes_polymarket.backtest.wallet_replay_storage import wallet_trades
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry
    from hermes_polymarket.storage.wallet_positions import closed_positions, current_positions

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        current_rows = current_positions(db, wallet.address)
        closed_rows = closed_positions(db, wallet.address, limit=args.limit)
        trade_rows = [trade.__dict__ for trade in wallet_trades(db, wallet.address, limit=args.trade_limit)]
        payload = {
            "wallet": wallet.name,
            "address": wallet.address,
            "current": current_position_report(current_rows),
            "closed": closed_position_report(closed_rows),
            "trade_position_coverage": trade_position_coverage(trade_rows, current_rows, closed_rows),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def _git_commit_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=Path(__file__).resolve().parents[2], text=True).strip()
    except Exception:
        return "unknown"


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode()
    return hashlib.sha256(raw).hexdigest()[:16]


def _write_replay_artifacts(
    run_id: str,
    wallet_name: str,
    config: object,
    summary: dict[str, Any],
    results: list[object],
    *,
    export_csv: bool = False,
    quality: dict[str, Any] | None = None,
) -> dict[str, str]:
    artifact_base = Path(os.getenv("HERMES_ARTIFACTS_DIR", str(Path(__file__).resolve().parents[2] / "artifacts" / "runs")))
    root = artifact_base / run_id
    root.mkdir(parents=True, exist_ok=True)
    config_hash = _stable_hash(
        {
            "wallet": config.wallet,
            "mode": config.mode,
            "delays_seconds": list(config.delays_seconds),
            "paper_amount_usd": config.paper_amount_usd,
            "exit_model": config.exit_model.value,
        }
    )
    config_payload = {
        "wallet_name": wallet_name,
        "wallet": config.wallet,
        "mode": config.mode,
        "data_quality": config.data_quality,
        "delays_seconds": list(config.delays_seconds),
        "paper_amount_usd": config.paper_amount_usd,
        "exit_model": config.exit_model.value,
    }
    if export_csv:
        from hermes_polymarket.backtest.replay_artifacts import write_replay_artifacts_csv

        return write_replay_artifacts_csv(
            root=root,
            run_id=run_id,
            summary=summary,
            results=results,
            config=config_payload,
            quality=quality or {},
            code_commit_sha=_git_commit_sha(),
            config_hash=config_hash,
        )
    paths = {
        "manifest": str(root / "manifest.json"),
        "config": str(root / "config.json"),
        "summary": str(root / "summary.json"),
        "replay_trades": str(root / "replay_trades.jsonl"),
        "notes": str(root / "notes.md"),
    }
    Path(paths["manifest"]).write_text(
        json.dumps(
            {
                "run_id": run_id,
                "code_commit_sha": _git_commit_sha(),
                "config_hash": config_hash,
                "data_quality": summary.get("data_quality"),
                "paths": paths,
                "config": config_payload,
                "quality": quality or {},
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    Path(paths["config"]).write_text(json.dumps(config_payload, indent=2, sort_keys=True) + "\n")
    Path(paths["summary"]).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    Path(paths["replay_trades"]).write_text("\n".join(json.dumps(result.to_storage_dict(), sort_keys=True) for result in results) + "\n")
    Path(paths["notes"]).write_text(
        "# Wallet Replay Notes\n\n"
        f"- Run: `{run_id}`\n"
        f"- Data quality: `{config.data_quality}`\n"
        "- Historical approximate mode uses public wallet trades, not executable L2 orderbook snapshots.\n"
        "- Candidate memories remain inactive until explicitly promoted to paper.\n"
    )
    return paths


def _record_replay_experiment(
    db: Database,
    run_id: str,
    wallet_name: str,
    wallet_address: str,
    config: object,
    summary: dict[str, Any],
    artifact_paths: dict[str, str],
) -> None:
    from hermes_polymarket.learning.experiments import ExperimentTracker
    from hermes_polymarket.learning.journal_schema import StrategyExperimentRecord

    parameters = {
        "wallet": wallet_address,
        "wallet_name": wallet_name,
        "mode": config.mode,
        "delays_seconds": list(config.delays_seconds),
        "paper_amount_usd": config.paper_amount_usd,
        "max_worse_entry_cents": config.max_worse_entry_cents,
        "max_delay_seconds": config.max_delay_seconds,
        "exit_model": config.exit_model.value,
    }
    now = datetime.now(timezone.utc).isoformat()
    ExperimentTracker(db).record(
        StrategyExperimentRecord(
            run_id=run_id,
            run_type="wallet_replay",
            strategy_id=f"wallet_flow:{wallet_name}",
            code_commit_sha=_git_commit_sha(),
            config_hash=_stable_hash(parameters),
            data_quality=config.data_quality,
            parameters=parameters,
            metrics=summary,
            artifacts={"run_id": run_id, "wallet": wallet_address, "mode": config.mode, "delays": list(config.delays_seconds), "paths": artifact_paths},
            dataset_version=f"wallet_observed_trades:{wallet_address}",
            started_at=now,
            ended_at=now,
        )
    )


def _maybe_create_replay_memory(db: Database, run_id: str, wallet_address: str, wallet_name: str, summary: dict[str, Any]) -> None:
    from hermes_polymarket.learning.memory_store import MemoryRecord, MemoryStore

    closed = int(summary.get("replayed_trades") or 0)
    skipped = sum(int(value) for value in (summary.get("skipped_trades_by_reason") or {}).values())
    pending = int(summary.get("pending_trades") or 0)
    if closed < 3 and skipped < 3 and pending < 3:
        return
    memory_id = f"memory:{run_id}:wallet_copyability"
    content = {
        "rule_type": "wallet_copyability_warning",
        "wallet": wallet_name,
        "statement": "Wallet replay produced candidate copyability evidence; keep inactive until reviewed.",
        "data_quality": summary.get("data_quality"),
        "closed_trades": closed,
        "pending_trades": pending,
        "skipped_trades_by_reason": summary.get("skipped_trades_by_reason", {}),
        "by_delay": summary.get("by_delay", {}),
    }
    MemoryStore(db).put(
        MemoryRecord(
            memory_id=memory_id,
            memory_type="semantic",
            status="candidate_rule",
            strategy_id=f"wallet_flow:{wallet_name}",
            wallet=wallet_address,
            content=content,
            evidence={"run_id": run_id, "summary": summary},
            confidence=0.35,
            active_in_paper=False,
            active_in_live=False,
        )
    )


def _learning_db() -> tuple[Database, object]:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    return db, settings


def cmd_learning_daily(_: argparse.Namespace) -> int:
    from hermes_polymarket.learning.reports import daily_report, render_report

    db, _ = _learning_db()
    try:
        print(render_report(daily_report(db)))
    finally:
        db.close()
    return 0


def cmd_learning_weekly(_: argparse.Namespace) -> int:
    from hermes_polymarket.learning.reports import render_report, weekly_review

    db, _ = _learning_db()
    try:
        print(render_report(weekly_review(db)))
    finally:
        db.close()
    return 0


def cmd_learning_hypotheses(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.decision_journal import DecisionJournal

    db, _ = _learning_db()
    try:
        rows = [dict(row) for row in DecisionJournal(db).hypotheses(status=args.status)]
        print(json.dumps(rows, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_learning_memory_search(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.memory_store import MemoryStore

    db, _ = _learning_db()
    try:
        rows = [
            dict(row)
            for row in MemoryStore(db).search(
                query=args.query,
                memory_type=args.memory_type,
                strategy_id=args.strategy_id,
                wallet=args.wallet,
                market_category=args.market_category,
            )
        ]
        print(json.dumps(rows, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_learning_promote(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.memory_store import MemoryStore
    from hermes_polymarket.learning.promotion import promote_candidate_to_paper

    db, _ = _learning_db()
    try:
        record = promote_candidate_to_paper(
            MemoryStore(db),
            rule_id=args.rule_id,
            human_approved=args.human_approved,
            paper_only=args.paper_only,
            reason=args.reason,
        )
        print(json.dumps(record.content, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_learning_retire(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.memory_store import MemoryStore
    from hermes_polymarket.learning.promotion import retire_rule

    db, _ = _learning_db()
    try:
        record = retire_rule(MemoryStore(db), rule_id=args.rule_id, reason=args.reason)
        print(json.dumps(record.content, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_discover(args: argparse.Namespace) -> int:
    from collections import Counter

    from hermes_polymarket.crypto.crypto_market_classifier import crypto_market_reject_reason
    from hermes_polymarket.crypto.market_resolver import market_window_from_gamma_market
    from hermes_polymarket.data_sources.base import now_ms
    from hermes_polymarket.polymarket.gamma_client import GammaClient
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report, insert_crypto_market_window
    from hermes_polymarket.storage.crypto_watchlist import upsert_crypto_market_watchlist

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    gamma = GammaClient()
    try:
        query_terms = args.query or ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "xrp", "crypto", "up or down", "higher or lower", "rise or fall"]
        discovered: dict[tuple[str, str, str], dict[str, Any]] = {}
        candidates: list[dict[str, Any]] = []
        for query in query_terms:
            market_rows = gamma.search_markets(query, limit=args.max_markets)
            event_rows = gamma.search_events(query, limit=args.max_markets)
            nested_market_rows = [market for event in event_rows for market in (event.get("markets") or []) if isinstance(market, dict)]
            for market in [*market_rows, *nested_market_rows]:
                candidates.append(market)
                window = market_window_from_gamma_market(market)
                if window is None:
                    continue
                window["discovered_at_ms"] = now_ms()
                window["raw"] = market
                key = (window["condition_id"], window["yes_token_id"], window["no_token_id"])
                discovered[key] = window

        for row in discovered.values():
            insert_crypto_market_window(db, row)
            upsert_crypto_market_watchlist(db, row)

        payload = crypto_latency_report(db)
        payload["status"] = "measurement_only"
        payload["discovered"] = len(discovered)
        payload["candidates_seen"] = len(candidates)
        payload["markets"] = [
            {
                "condition_id": row["condition_id"],
                "slug": row["slug"],
                "symbol": row["symbol"],
                "yes_token_id": row["yes_token_id"],
                "no_token_id": row["no_token_id"],
            }
            for row in discovered.values()
        ]
        if args.debug_candidates:
            rejected: list[dict[str, str]] = []
            reason_counts: Counter[str] = Counter()
            for market in candidates:
                slug = str(market.get("slug") or "")
                question = str(market.get("question") or market.get("title") or "")
                reason = crypto_market_reject_reason(question, slug) or "classified_or_missing_tokens"
                if reason != "classified_or_missing_tokens":
                    reason_counts[reason] += 1
                rejected.append({"slug": slug, "question": question, "reason": reason})
            payload["debug"] = {
                "rejected_reason_counts": dict(reason_counts),
                "top_rejected": rejected[: min(25, len(rejected))],
            }
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        gamma.close()
        db.close()
    return 0


def cmd_crypto_latency_record(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.latency_recorder import RecorderConfig, run_crypto_latency_recorder
    from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
    from hermes_polymarket.data_sources.event_bus import EventBus
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        symbols = tuple(symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip())
        if not symbols:
            print("crypto-latency record requires at least one symbol")
            return 2
        seconds = max(1, min(args.seconds, 900))

        async def publish_fixture_crypto_events(bus: EventBus) -> None:
            ts = now_ms()
            for price in (100.0, 100.02, 101.0):
                await bus.publish(
                    DataEvent(
                        source="fixture_binance",
                        event_type=EventType.BINANCE_TRADE,
                        event_ts_ms=ts,
                        received_ts_ms=ts,
                        key="btcusdt",
                        payload={"symbol": "BTCUSDT", "price": price, "qty": 1.0},
                    )
                )
                await bus.publish(
                    DataEvent(
                        source="fixture_coinbase",
                        event_type=EventType.COINBASE_TICKER,
                        event_ts_ms=None,
                        received_ts_ms=ts,
                        key="btc-usd",
                        payload={"product_id": "BTC-USD", "price": price},
                    )
                )
                ts += 1000

        async def run_recording() -> dict[str, Any]:
            bus = EventBus()
            tasks: list[asyncio.Task[None]] = []
            market_ws_token_count = 0
            if args.fixture:
                await publish_fixture_crypto_events(bus)
            else:
                from hermes_polymarket.data_sources.binance_stream import run_binance_stream
                from hermes_polymarket.data_sources.coinbase_stream import run_coinbase_ticker
                from hermes_polymarket.data_sources.kraken_stream import run_kraken_ticker
                if not args.disable_rtds:
                    from hermes_polymarket.data_sources.polymarket_rtds import run_polymarket_rtds_crypto
                if args.use_watchlist:
                    from hermes_polymarket.data_sources.polymarket_market_ws import run_polymarket_market_ws
                    from hermes_polymarket.storage.crypto_watchlist import watchlist_token_ids

                coinbase_products = tuple(symbol.replace("usdt", "-USD").upper() for symbol in symbols)
                kraken_symbols = tuple(symbol.replace("usdt", "/USD").upper() for symbol in symbols)
                tasks = [
                    asyncio.create_task(run_binance_stream(bus, symbols=symbols)),
                    asyncio.create_task(run_coinbase_ticker(bus, product_ids=coinbase_products)),
                    asyncio.create_task(run_kraken_ticker(bus, symbols=kraken_symbols)),
                ]
                if not args.disable_rtds:
                    tasks.append(asyncio.create_task(run_polymarket_rtds_crypto(bus, symbols=symbols)))
                if args.use_watchlist:
                    token_ids = watchlist_token_ids(db, active_only=True, limit=args.max_watchlist_markets)
                    market_ws_token_count = len(token_ids)
                    if token_ids:
                        tasks.append(asyncio.create_task(run_polymarket_market_ws(bus, asset_ids=token_ids)))
            try:
                summary = await run_crypto_latency_recorder(
                    db=db,
                    bus=bus,
                    config=RecorderConfig(
                        symbols=symbols,
                        seconds=seconds,
                        min_move_pct=args.min_move_pct,
                        max_age_ms=args.max_age_ms,
                        max_deviation_pct=args.max_deviation_pct,
                        min_sources=args.min_sources,
                        cooldown_ms=args.cooldown_ms,
                    ),
                )
            finally:
                for task in tasks:
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks)

            payload = {
                "mode": "measurement_paper_only",
                "data_quality": "paper_live" if not args.fixture else "local_observation",
                "fixture": args.fixture,
                "use_watchlist": args.use_watchlist,
                "watchlist_token_count": market_ws_token_count,
                "symbols": symbols,
                "summary": summary.to_dict(),
                "report": crypto_latency_report(db),
            }
            if args.write_artifacts:
                payload["artifact_dir"] = str(_write_crypto_latency_artifacts(db, payload))
            return payload

        payload = asyncio.run(run_recording())
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_report(_: argparse.Namespace) -> int:
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(json.dumps(crypto_latency_report(db), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_source_health(_: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = [dict(row) for row in db.source_health()]
        print(json.dumps({"mode": "measurement_paper_only", "source_health": rows}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_watchlist(args: argparse.Namespace) -> int:
    from hermes_polymarket.data_sources.base import now_ms
    from hermes_polymarket.crypto.market_quality import watchlist_health_report
    from hermes_polymarket.storage.crypto_watchlist import (
        clear_crypto_market_watchlist,
        crypto_market_watchlist,
        set_crypto_market_watchlist_active,
        upsert_crypto_market_watchlist,
    )
    try:
        import yaml
    except Exception:  # pragma: no cover - dependency is expected in normal runtime
        yaml = None

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        if args.watchlist_action == "add":
            up_token_id = args.up_token_id
            down_token_id = args.down_token_id
            if args.yes_direction == "up":
                up_token_id = up_token_id or args.yes_token_id
                down_token_id = down_token_id or args.no_token_id
            elif args.yes_direction == "down":
                up_token_id = up_token_id or args.no_token_id
                down_token_id = down_token_id or args.yes_token_id
            upsert_crypto_market_watchlist(
                db,
                {
                    "condition_id": args.condition_id,
                    "slug": args.slug,
                    "question": args.question or args.slug,
                    "symbol": args.symbol.lower(),
                    "yes_token_id": args.yes_token_id,
                    "no_token_id": args.no_token_id,
                    "up_token_id": up_token_id,
                    "down_token_id": down_token_id,
                    "direction_map": {"up": up_token_id, "down": down_token_id} if up_token_id and down_token_id else {},
                    "active": True,
                    "discovered_at_ms": now_ms(),
                    "raw": {"manual": True},
                },
            )
            rows = crypto_market_watchlist(db, active_only=False, limit=args.limit)
            print(json.dumps({"mode": "measurement_paper_only", "status": "added", "watchlist": rows}, indent=2, sort_keys=True))
        elif args.watchlist_action == "import":
            if yaml is None:
                print("pyyaml is required for watchlist import")
                return 2
            path = Path(args.file)
            payload = yaml.safe_load(path.read_text()) or {}
            markets = payload.get("markets") if isinstance(payload, dict) else None
            if not isinstance(markets, list):
                print("manual watchlist file must contain a markets list")
                return 2
            imported = 0
            for market in markets:
                if not isinstance(market, dict):
                    continue
                yes_token_id = str(market["yes_token_id"])
                no_token_id = str(market["no_token_id"])
                up_token_id = market.get("up_token_id")
                down_token_id = market.get("down_token_id")
                yes_direction = market.get("yes_direction")
                if yes_direction == "up":
                    up_token_id = up_token_id or yes_token_id
                    down_token_id = down_token_id or no_token_id
                elif yes_direction == "down":
                    up_token_id = up_token_id or no_token_id
                    down_token_id = down_token_id or yes_token_id
                upsert_crypto_market_watchlist(
                    db,
                    {
                        "condition_id": str(market["condition_id"]),
                        "slug": str(market["slug"]),
                        "question": str(market.get("question") or market["slug"]),
                        "symbol": str(market["symbol"]).lower(),
                        "yes_token_id": yes_token_id,
                        "no_token_id": no_token_id,
                        "up_token_id": up_token_id,
                        "down_token_id": down_token_id,
                        "direction_map": {"up": up_token_id, "down": down_token_id} if up_token_id and down_token_id else {},
                        "active": bool(market.get("active", True)),
                        "discovered_at_ms": int(market.get("discovered_at_ms") or now_ms()),
                        "raw": {"manual_import": str(path)},
                    },
                )
                imported += 1
            rows = crypto_market_watchlist(db, active_only=False, limit=args.limit)
            print(json.dumps({"mode": "measurement_paper_only", "status": "imported", "imported": imported, "watchlist": rows}, indent=2, sort_keys=True))
        elif args.watchlist_action == "clear":
            deleted = clear_crypto_market_watchlist(db)
            print(json.dumps({"mode": "measurement_paper_only", "status": "cleared", "deleted": deleted}, indent=2, sort_keys=True))
        elif args.watchlist_action == "health":
            print(json.dumps(watchlist_health_report(db, symbol=args.symbol, active_only=not args.all, limit=args.limit), indent=2, sort_keys=True))
        elif args.watchlist_action == "disable":
            updated = set_crypto_market_watchlist_active(db, condition_id=args.condition_id, active=False)
            print(json.dumps({"mode": "measurement_paper_only", "status": "disabled", "condition_id": args.condition_id, "updated": updated}, indent=2, sort_keys=True))
        elif args.watchlist_action == "enable":
            updated = set_crypto_market_watchlist_active(db, condition_id=args.condition_id, active=True)
            print(json.dumps({"mode": "measurement_paper_only", "status": "enabled", "condition_id": args.condition_id, "updated": updated}, indent=2, sort_keys=True))
        elif args.watchlist_action == "prune-bad":
            report = watchlist_health_report(db, symbol=args.symbol, active_only=True, limit=args.limit)
            disabled: list[str] = []
            for market in report["markets"]:
                if market["recommended_action"] != "disable_or_replace_market":
                    continue
                disabled.append(str(market["condition_id"]))
                if not args.dry_run:
                    set_crypto_market_watchlist_active(db, condition_id=str(market["condition_id"]), active=False)
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "status": "dry_run" if args.dry_run else "pruned",
                        "disabled": disabled,
                        "health": report,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        else:
            rows = crypto_market_watchlist(db, active_only=not args.all, limit=args.limit)
            print(json.dumps({"mode": "measurement_paper_only", "watchlist": rows}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_consensus(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = db.conn.execute(
            """
            SELECT * FROM crypto_consensus_ticks
            WHERE symbol = ?
            ORDER BY received_ts_ms DESC, id DESC
            LIMIT ?
            """,
            (args.symbol.lower(), args.last),
        ).fetchall()
        print(json.dumps({"mode": "measurement_paper_only", "consensus": [dict(row) for row in rows]}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_events(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        if args.symbol:
            rows = db.conn.execute(
                """
                SELECT * FROM crypto_latency_events
                WHERE symbol = ?
                ORDER BY external_move_detected_ts_ms DESC, id DESC
                LIMIT ?
                """,
                (args.symbol.lower(), args.last),
            ).fetchall()
        else:
            rows = db.conn.execute(
                "SELECT * FROM crypto_latency_events ORDER BY external_move_detected_ts_ms DESC, id DESC LIMIT ?",
                (args.last,),
            ).fetchall()
        print(json.dumps({"mode": "measurement_paper_only", "events": [dict(row) for row in rows]}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_threshold_sweep(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.threshold_sweep import count_threshold_hits

    thresholds = [float(value) for value in args.thresholds.split(",") if value.strip()]
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = db.conn.execute(
            """
            SELECT received_ts_ms, consensus_price
            FROM crypto_consensus_ticks
            WHERE symbol = ?
            ORDER BY received_ts_ms DESC, id DESC
            LIMIT ?
            """,
            (args.symbol.lower(), args.last),
        ).fetchall()
        prices = [(int(row["received_ts_ms"]), float(row["consensus_price"])) for row in rows]
        results = count_threshold_hits(
            symbol=args.symbol.lower(),
            prices=prices,
            thresholds_pct=thresholds,
            lookback_ms=args.lookback_ms,
            cooldown_ms=args.cooldown_ms,
        )
        threshold_payload = {
            str(result.threshold_pct): {"hits": result.hits, "max_move_pct": result.max_move_pct}
            for result in results
        }
        print(
            json.dumps(
                {
                    "mode": "measurement_paper_only",
                    "symbol": args.symbol.lower(),
                    "lookback_ms": args.lookback_ms,
                    "data_points": len(prices),
                    "thresholds": threshold_payload,
                    "threshold_sweep": [result.__dict__ for result in results],
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
    return 0


def cmd_crypto_latency_raw_samples(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.raw_samples import raw_samples

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = raw_samples(db, source=args.source, limit=args.last)
        print(json.dumps({"mode": "measurement_paper_only", "raw_samples": rows}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_opportunities(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.crypto_latency import crypto_latency_opportunities

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(json.dumps({"mode": "measurement_paper_only", "opportunities": crypto_latency_opportunities(db, limit=args.limit)}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_watch(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.artifacts import write_forward_paper_artifacts
    from hermes_polymarket.forward_paper.quality import forward_paper_quality_warnings
    from hermes_polymarket.crypto.paper_watcher import PaperWatcherConfig, run_crypto_paper_watcher
    from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
    from hermes_polymarket.data_sources.event_bus import EventBus
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report
    from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist, watchlist_token_ids
    from hermes_polymarket.storage.forward_positions import (
        forward_position_report,
        forward_positions,
        forward_signals_for_run,
        insert_forward_run,
    )

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        symbols = tuple(symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip())
        if not symbols:
            print("crypto-paper watch requires at least one symbol")
            return 2
        if not args.from_watchlist and not args.fixture:
            print("crypto-paper watch requires --from-watchlist so paper fills use known Polymarket token IDs.")
            return 2
        seconds = max(1, min(args.seconds, 900))
        watchlist = crypto_market_watchlist(db, active_only=True, limit=args.max_watchlist_markets) if args.from_watchlist else []
        token_ids = watchlist_token_ids(db, active_only=True, limit=args.max_watchlist_markets) if args.from_watchlist else ()
        if args.fixture and not watchlist:
            watchlist = [
                {
                    "condition_id": "fixture-condition",
                    "slug": "fixture-crypto-paper",
                    "question": "Fixture crypto paper market",
                    "symbol": symbols[0],
                    "yes_token_id": "fixture-yes-token",
                    "no_token_id": "fixture-no-token",
                    "up_token_id": "fixture-yes-token",
                    "down_token_id": "fixture-no-token",
                    "active": 1,
                }
            ]
            token_ids = ("fixture-yes-token", "fixture-no-token")
        if args.from_watchlist and not token_ids:
            print("No token IDs found. Run crypto-latency discover or crypto-latency watchlist add first.")
            return 2

        async def publish_fixture(bus: EventBus) -> None:
            ts = now_ms()
            for market in watchlist:
                for token_id in (str(market["yes_token_id"]), str(market["no_token_id"])):
                    await bus.publish(
                        DataEvent(
                            source="fixture_market_ws",
                            event_type=EventType.POLY_BOOK,
                            event_ts_ms=ts,
                            received_ts_ms=ts,
                            key=token_id,
                            payload={
                                "asset_id": token_id,
                                "market": market["condition_id"],
                                "bids": [{"price": "0.49", "size": "100"}],
                                "asks": [{"price": "0.50", "size": "100"}],
                            },
                        )
                    )
                    await bus.publish(
                        DataEvent(
                            source="fixture_market_ws",
                            event_type=EventType.POLY_BEST_BID_ASK,
                            event_ts_ms=ts + 10,
                            received_ts_ms=ts + 10,
                            key=token_id,
                            payload={"asset_id": token_id, "market": market["condition_id"], "best_bid": "0.49", "best_ask": "0.50"},
                        )
                    )
            symbol = symbols[0]
            coinbase_key = symbol.replace("usdt", "-USD").upper()
            for price in (100.0, 100.02, 101.0):
                await bus.publish(
                    DataEvent(
                        source="fixture_binance",
                        event_type=EventType.BINANCE_TRADE,
                        event_ts_ms=ts,
                        received_ts_ms=ts,
                        key=symbol,
                        payload={"symbol": symbol.upper(), "price": price, "qty": 1.0},
                    )
                )
                await bus.publish(
                    DataEvent(
                        source="fixture_coinbase",
                        event_type=EventType.COINBASE_TICKER,
                        event_ts_ms=None,
                        received_ts_ms=ts,
                        key=coinbase_key.lower(),
                        payload={"product_id": coinbase_key, "price": price},
                    )
                )
                ts += 1000
            for market in watchlist:
                for token_id in (str(market["yes_token_id"]), str(market["no_token_id"])):
                    await bus.publish(
                        DataEvent(
                            source="fixture_market_ws",
                            event_type=EventType.POLY_BEST_BID_ASK,
                            event_ts_ms=ts + 100,
                            received_ts_ms=ts + 100,
                            key=token_id,
                            payload={"asset_id": token_id, "market": market["condition_id"], "best_bid": "0.60", "best_ask": "0.61"},
                        )
                    )

        async def run() -> dict[str, Any]:
            bus = EventBus()
            tasks: list[asyncio.Task[None]] = []
            if args.fixture:
                await publish_fixture(bus)
            else:
                from hermes_polymarket.data_sources.binance_stream import run_binance_stream
                from hermes_polymarket.data_sources.coinbase_stream import run_coinbase_ticker
                from hermes_polymarket.data_sources.kraken_stream import run_kraken_ticker
                from hermes_polymarket.data_sources.polymarket_market_ws import run_polymarket_market_ws

                coinbase_products = tuple(symbol.replace("usdt", "-USD").upper() for symbol in symbols)
                kraken_symbols = tuple(symbol.replace("usdt", "/USD").upper() for symbol in symbols)
                tasks = [
                    asyncio.create_task(run_binance_stream(bus, symbols=symbols)),
                    asyncio.create_task(run_coinbase_ticker(bus, product_ids=coinbase_products)),
                    asyncio.create_task(run_kraken_ticker(bus, symbols=kraken_symbols)),
                    asyncio.create_task(run_polymarket_market_ws(bus, asset_ids=token_ids)),
                ]
                if not args.disable_rtds:
                    from hermes_polymarket.data_sources.polymarket_rtds import run_polymarket_rtds_crypto

                    tasks.append(asyncio.create_task(run_polymarket_rtds_crypto(bus, symbols=symbols)))
            try:
                summary = await run_crypto_paper_watcher(
                    db=db,
                    bus=bus,
                    config=PaperWatcherConfig(
                        symbols=symbols,
                        seconds=seconds,
                        amount_usd=args.amount,
                        min_move_pct=args.min_move_pct,
                        calibration_thresholds_pct=tuple(float(value) for value in args.threshold_grid.split(",") if value.strip()),
                        max_age_ms=args.max_age_ms,
                        max_deviation_pct=args.max_deviation_pct,
                        min_sources=args.min_sources,
                        cooldown_ms=args.cooldown_ms,
                        take_profit_cents=args.take_profit_cents,
                        stop_loss_cents=args.stop_loss_cents,
                        timeout_seconds=args.timeout_seconds,
                        fixture=args.fixture,
                        healthy_only=args.healthy_only,
                    ),
                    watchlist=watchlist,
                    settings=settings,
                )
            finally:
                for task in tasks:
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks)

            summary_dict = summary.to_dict()
            position_report = forward_position_report(db, run_id=summary.run_id, include_fixture=args.fixture)
            warnings = forward_paper_quality_warnings(
                signals=summary.signals_generated,
                closed_positions=summary.positions_closed,
                min_move_pct=args.min_move_pct,
                min_strategy_threshold_pct=args.min_strategy_threshold_pct,
            )
            if args.seconds != seconds:
                warnings.append("duration_capped_by_config")
            quality = {
                "warnings": warnings,
                "threshold_calibration": summary.threshold_calibration,
                "exploratory_threshold": args.min_move_pct < args.min_strategy_threshold_pct,
                "requested_seconds": args.seconds,
                "actual_seconds": seconds,
                "duration_capped": args.seconds != seconds,
                "cap_reason": "config.max_record_seconds" if args.seconds != seconds else None,
            }
            signals = forward_signals_for_run(db, summary.run_id, limit=args.max_event_samples)
            positions = forward_positions(db, run_id=summary.run_id, include_fixture=args.fixture, limit=500)
            artifacts: dict[str, str] = {}
            if args.write_artifacts:
                artifacts = write_forward_paper_artifacts(
                    root=Path(args.artifact_dir) / summary.run_id,
                    run_id=summary.run_id,
                    summary=summary_dict,
                    report=position_report,
                    signals=signals,
                    positions=positions,
                    quality=quality,
                )
            insert_forward_run(
                db,
                run_id=summary.run_id,
                symbols=symbols,
                config={
                    "seconds": seconds,
                    "requested_seconds": args.seconds,
                    "amount_usd": args.amount,
                    "min_move_pct": args.min_move_pct,
                    "min_strategy_threshold_pct": args.min_strategy_threshold_pct,
                    "threshold_grid": args.threshold_grid,
                    "healthy_only": args.healthy_only,
                },
                summary=summary_dict,
                report=position_report,
                quality=quality,
                artifacts=artifacts,
                requested_symbols=symbols,
                requested_seconds=args.seconds,
                actual_seconds=seconds,
                fixture=args.fixture,
                exploratory_threshold=args.min_move_pct < args.min_strategy_threshold_pct,
            )
            return {
                "mode": "forward_paper_only",
                "data_quality": "paper_live" if not args.fixture else "local_observation",
                "fixture": args.fixture,
                "symbols": symbols,
                "from_watchlist": args.from_watchlist,
                "healthy_only": args.healthy_only,
                "watchlist_token_count": len(token_ids),
                "summary": summary_dict,
                "position_report": position_report,
                "quality": quality,
                "artifacts": artifacts,
                "latency_report": crypto_latency_report(db),
            }

        print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_positions(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.forward_positions import forward_positions

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        status = "open" if args.open else "closed" if args.closed else None
        rows = forward_positions(db, run_id=args.run_id, status=status, include_fixture=args.include_fixture, limit=args.limit)
        print(
            json.dumps(
                {
                    "mode": "forward_paper_only",
                    "data_quality": "paper_live",
                    "run_id": args.run_id,
                    "include_fixture": args.include_fixture,
                    "positions": rows,
                },
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
    return 0


def cmd_crypto_paper_report(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.forward_positions import forward_run_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(json.dumps(forward_run_report(db, run_id=args.run_id, include_fixture=args.include_fixture), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_signals(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.forward_positions import forward_signals

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        rows = forward_signals(
            db,
            run_id=args.run_id,
            include_fixture=args.include_fixture,
            rejected_only=args.rejected_only,
            risk_reason=getattr(args, "reason", None),
            limit=args.last,
        )
        print(json.dumps({"mode": "forward_paper_only", "run_id": args.run_id, "signals": rows}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_explain(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.diagnostics import explain_forward_signal

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        result = explain_forward_signal(db, args.signal_id, settings)
        if not result.get("found"):
            print(json.dumps(result, indent=2, sort_keys=True))
            return 2
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_l2_context(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.diagnostics import l2_context_for_signal, signal_by_id

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        signal = signal_by_id(db, args.signal_id)
        if signal is None:
            print(json.dumps({"signal_id": args.signal_id, "book_found": False, "reason": "signal_not_found"}, indent=2, sort_keys=True))
            return 2
        print(json.dumps(l2_context_for_signal(db, signal, levels=args.levels), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_runs(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.forward_positions import forward_runs

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(json.dumps({"mode": "forward_paper_only", "runs": forward_runs(db, include_fixture=args.include_fixture, limit=args.limit)}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_artifacts(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.forward_positions import forward_run

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        row = forward_run(db, args.run_id)
        if row is None:
            print(f"No forward paper run found for {args.run_id}")
            return 2
        print(json.dumps({"mode": "forward_paper_only", "run_id": args.run_id, "artifacts": json.loads(row["artifacts_json"])}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_readiness(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.readiness import forward_paper_readiness

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(
            json.dumps(
                forward_paper_readiness(
                    db,
                    include_fixture=args.include_fixture,
                    min_signals=args.min_signals,
                    min_positions=args.min_positions,
                ),
                indent=2,
                sort_keys=True,
            )
        )
    finally:
        db.close()
    return 0


def cmd_crypto_paper_campaign_summary(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.campaign_summary import summarize_campaign_dbs

    result = summarize_campaign_dbs(args.db, include_fixture=args.include_fixture, include_signals=args.include_signals)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_strategy_arena_run(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.strategy_arena import load_arena_config, run_strategy_arena, write_arena_artifact

    config = load_arena_config(args.config)
    result = run_strategy_arena(args.db, config_path=args.config, include_fixture=args.include_fixture)
    artifact_dir = config.get("arena", {}).get("artifact_dir", "artifacts/strategy_arena")
    output = write_arena_artifact(result, output=args.output, artifact_dir=artifact_dir)
    result = {**result, "artifact": str(output)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_strategy_arena_report(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.strategy_arena import load_arena_artifact

    path = args.file or "artifacts/strategy_arena/latest.json"
    print(json.dumps(load_arena_artifact(path), indent=2, sort_keys=True))
    return 0


def cmd_strategy_arena_compare(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.strategy_arena import load_arena_artifact

    path = args.file or "artifacts/strategy_arena/latest.json"
    result = load_arena_artifact(path)
    baseline = args.baseline
    strategies = result.get("strategies", [])
    baseline_row = next((row for row in strategies if row.get("strategy_id") == baseline), {"net_pnl": 0.0, "positions": 0, "closed_positions": 0})
    baseline_pnl = float(baseline_row.get("net_pnl") or 0.0)
    comparisons = []
    for row in strategies:
        if row.get("strategy_id") == baseline:
            continue
        comparisons.append(
            {
                "strategy_id": row.get("strategy_id"),
                "baseline": baseline,
                "net_pnl_delta": float(row.get("net_pnl") or 0.0) - baseline_pnl,
                "positions_delta": int(row.get("positions") or 0) - int(baseline_row.get("positions") or 0),
                "closed_positions_delta": int(row.get("closed_positions") or 0) - int(baseline_row.get("closed_positions") or 0),
                "warnings": row.get("warnings", []),
            }
        )
    print(json.dumps({"mode": "diagnostic_paper", "baseline": baseline, "comparisons": comparisons}, indent=2, sort_keys=True))
    return 0


def cmd_strategy_arena_artifacts(args: argparse.Namespace) -> int:
    path = Path(args.file or "artifacts/strategy_arena/latest.json")
    print(json.dumps({"mode": "diagnostic_paper", "artifact": str(path), "exists": path.exists()}, indent=2, sort_keys=True))
    return 0


def cmd_evidence_dashboard(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.evidence_dashboard import (
        evidence_dashboard,
        expand_db_globs,
        write_evidence_dashboard,
    )

    db_paths = expand_db_globs(args.db_glob)
    result = evidence_dashboard(db_paths, include_fixture=args.include_fixture)
    if args.output:
        output = write_evidence_dashboard(result, args.output)
        result = {**result, "artifact": str(output)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_l2_recorder_start(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.l2_recorder import run_l2_recorder
    from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
    from hermes_polymarket.data_sources.event_bus import EventBus
    from hermes_polymarket.data_sources.polymarket_market_ws import run_polymarket_market_ws
    from hermes_polymarket.storage.crypto_watchlist import watchlist_token_ids

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        token_ids = tuple(args.token_id or ())
        if args.from_crypto_watchlist:
            token_ids = (*token_ids, *watchlist_token_ids(db, active_only=True, limit=args.max_watchlist_markets))
        token_ids = tuple(dict.fromkeys(token_ids))
        if not token_ids:
            print("No token IDs found. Run crypto-latency discover or crypto-latency watchlist add first.")
            return 2

        async def publish_fixture(bus: EventBus, token_id: str) -> None:
            ts = now_ms()
            await bus.publish(
                DataEvent(
                    source="fixture_market_ws",
                    event_type=EventType.POLY_BOOK,
                    event_ts_ms=ts,
                    received_ts_ms=ts,
                    key=token_id,
                    payload={
                        "asset_id": token_id,
                        "bids": [{"price": "0.49", "size": "10"}],
                        "asks": [{"price": "0.51", "size": "10"}],
                    },
                )
            )
            await bus.publish(
                DataEvent(
                    source="fixture_market_ws",
                    event_type=EventType.POLY_BEST_BID_ASK,
                    event_ts_ms=ts + 50,
                    received_ts_ms=ts + 50,
                    key=token_id,
                    payload={"asset_id": token_id, "bid": "0.49", "ask": "0.51"},
                )
            )
            await bus.publish(
                DataEvent(
                    source="fixture_market_ws",
                    event_type=EventType.POLY_PRICE_CHANGE,
                    event_ts_ms=ts + 100,
                    received_ts_ms=ts + 100,
                    key=token_id,
                    payload={"asset_id": token_id, "side": "ask", "price": "0.51", "size": "0", "removed": True},
                )
            )

        async def run() -> dict[str, Any]:
            bus = EventBus()
            producer: asyncio.Task[None] | None = None
            if args.fixture:
                await publish_fixture(bus, token_ids[0])
            else:
                producer = asyncio.create_task(run_polymarket_market_ws(bus, asset_ids=token_ids))
            try:
                summary = await run_l2_recorder(db=db, bus=bus, token_ids=token_ids, seconds=args.seconds)
            finally:
                if producer is not None:
                    producer.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await producer
            return {"mode": "local_l2_paper_only", "fixture": args.fixture, "token_ids": token_ids, "summary": summary.to_dict()}

        print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_l2_recorder_status(args: argparse.Namespace) -> int:
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        runs = [
            dict(row)
            for row in db.conn.execute(
                "SELECT * FROM l2_recorder_runs ORDER BY started_at DESC LIMIT ?",
                (args.limit,),
            )
        ]
        counts = {
            "snapshots": db.conn.execute("SELECT COUNT(*) AS n FROM l2_book_snapshots").fetchone()["n"],
            "deltas": db.conn.execute("SELECT COUNT(*) AS n FROM l2_price_changes").fetchone()["n"],
            "bbo": db.conn.execute("SELECT COUNT(*) AS n FROM l2_bbo_updates").fetchone()["n"],
        }
        print(json.dumps({"mode": "local_l2_paper_only", "counts": counts, "runs": runs}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_l2_recorder_coverage(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.local_l2_coverage import local_l2_coverage_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        if args.token_id:
            reports = [local_l2_coverage_report(db, token_id=args.token_id)]
        else:
            token_rows = db.conn.execute(
                """
                SELECT token_id FROM l2_book_snapshots
                UNION
                SELECT token_id FROM l2_price_changes
                UNION
                SELECT token_id FROM l2_bbo_updates
                ORDER BY token_id
                """
            ).fetchall()
            reports = [local_l2_coverage_report(db, token_id=row["token_id"]) for row in token_rows]
        print(json.dumps({"mode": "local_l2_paper_only", "data_quality": "local_l2", "coverage": reports}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_l2_recorder_reconstruct(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.local_l2_lookup import nearest_bbo_before, reconstruct_book_at

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        state = reconstruct_book_at(db, token_id=args.token_id, target_ts_ms=args.timestamp_ms)
        token_state = state.by_token.get(args.token_id) if state is not None else None
        payload = {
            "mode": "local_l2_paper_only",
            "token_id": args.token_id,
            "timestamp_ms": args.timestamp_ms,
            "book_found": token_state is not None,
            "best_bid": token_state.best_bid if token_state else None,
            "best_ask": token_state.best_ask if token_state else None,
            "spread": token_state.spread if token_state else None,
            "bids": len(token_state.bids) if token_state else 0,
            "asks": len(token_state.asks) if token_state else 0,
            "nearest_bbo": nearest_bbo_before(db, token_id=args.token_id, target_ts_ms=args.timestamp_ms),
        }
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if token_state is not None else 2
    finally:
        db.close()


def cmd_crypto_latency_replay_opportunities(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.crypto_latency_local_l2_replay import replay_crypto_latency_opportunities_local_l2

    if args.mode != "local-l2":
        print("Only --mode local-l2 is implemented for replay-opportunities.")
        return 2
    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        result = replay_crypto_latency_opportunities_local_l2(db, amount_usd=args.amount, limit=args.limit)
        print(json.dumps(result, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def _write_crypto_latency_artifacts(db: Database, payload: dict[str, Any]) -> Path:
    run_id = f"crypto_latency_{uuid4().hex[:12]}"
    root = Path("artifacts/crypto_latency") / run_id
    root.mkdir(parents=True, exist_ok=True)

    (root / "summary.json").write_text(json.dumps(payload, indent=2, sort_keys=True))
    (root / "diagnostics.json").write_text(json.dumps(payload.get("summary", {}).get("diagnostics", {}), indent=2, sort_keys=True))
    source_health = [dict(row) for row in db.source_health()]
    (root / "source_health.json").write_text(json.dumps(source_health, indent=2, sort_keys=True))

    _write_query_csv(
        root / "consensus_ticks.csv",
        [dict(row) for row in db.conn.execute("SELECT * FROM crypto_consensus_ticks ORDER BY received_ts_ms DESC, id DESC LIMIT 5000")],
    )
    _write_query_csv(
        root / "latency_events.csv",
        [dict(row) for row in db.conn.execute("SELECT * FROM crypto_latency_events ORDER BY external_move_detected_ts_ms DESC, id DESC LIMIT 1000")],
    )
    _write_threshold_sweep_csv(root / "threshold_sweep.csv", db)
    return root


def _write_query_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("")
        return
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _write_threshold_sweep_csv(path: Path, db: Database) -> None:
    from hermes_polymarket.crypto.threshold_sweep import count_threshold_hits

    rows: list[dict[str, Any]] = []
    for symbol_row in db.conn.execute("SELECT DISTINCT symbol FROM crypto_consensus_ticks ORDER BY symbol"):
        symbol = symbol_row["symbol"]
        price_rows = db.conn.execute(
            """
            SELECT received_ts_ms, consensus_price
            FROM crypto_consensus_ticks
            WHERE symbol = ?
            ORDER BY received_ts_ms DESC, id DESC
            LIMIT 5000
            """,
            (symbol,),
        ).fetchall()
        prices = [(int(row["received_ts_ms"]), float(row["consensus_price"])) for row in price_rows]
        for result in count_threshold_hits(symbol=symbol, prices=prices, thresholds_pct=[0.03, 0.05, 0.08, 0.12], lookback_ms=3000):
            rows.append(result.__dict__)
    _write_query_csv(path, rows)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hermes-polymarket")
    sub = parser.add_subparsers(dest="command", required=True)

    audit = sub.add_parser("audit")
    audit.set_defaults(func=cmd_audit)

    smoke = sub.add_parser("smoke")
    smoke.set_defaults(func=cmd_smoke)

    scan = sub.add_parser("scan")
    scan.add_argument("--mode", default="paper", choices=["paper", "dry-run", "live"])
    scan.set_defaults(func=cmd_scan)

    signal = sub.add_parser("signal")
    signal_sub = signal.add_subparsers(dest="signal_command", required=True)
    weather = signal_sub.add_parser("weather")
    weather.add_argument("--mode", default="paper", choices=["paper"])
    weather.add_argument("--low", type=float, default=None)
    weather.add_argument("--high", type=float, default=75.0)
    weather.set_defaults(func=cmd_signal_weather)

    wallet_flow = sub.add_parser("wallet-flow")
    wallet_sub = wallet_flow.add_subparsers(dest="wallet_command", required=True)
    fetch = wallet_sub.add_parser("fetch")
    fetch.add_argument("--wallet", required=True)
    fetch.add_argument("--limit", type=int, default=100)
    fetch.add_argument("--page-size", type=int, default=None)
    fetch.add_argument("--max-pages", type=int, default=None)
    fetch.add_argument("--limit-total", type=int, default=None)
    fetch.add_argument("--min-cash", type=float, default=None)
    fetch.add_argument("--side", default="all", choices=["all", "buy", "sell", "unspecified"])
    fetch.add_argument("--json", action="store_true", help="Include raw Data API trade payloads in output")
    fetch.set_defaults(func=cmd_wallet_flow_fetch)
    replay = wallet_sub.add_parser("replay")
    replay.add_argument("--wallet", required=True)
    replay.add_argument("--delay", default="0,2,5,15,30,120,600")
    replay.add_argument("--mode", default="historical-approx", choices=["historical-approx", "local-l2"])
    replay.add_argument("--amount", type=float, default=5.0)
    replay.add_argument("--limit", type=int, default=1000)
    replay.add_argument("--since-ts", type=int, default=None)
    replay.add_argument("--condition-id", default=None)
    replay.add_argument("--exit-model", default="leader_exit", choices=["leader_exit", "resolution_exit", "risk_exit"])
    replay.add_argument("--export-csv", action="store_true")
    replay.add_argument("--quality-warnings", action="store_true")
    replay.set_defaults(func=cmd_wallet_flow_replay)
    score = wallet_sub.add_parser("score")
    score.add_argument("--wallet", required=True)
    score.set_defaults(func=cmd_wallet_flow_score)
    leaderboard = wallet_sub.add_parser("leaderboard")
    leaderboard.set_defaults(func=cmd_wallet_flow_leaderboard)
    exit_coverage = wallet_sub.add_parser("exit-coverage")
    exit_coverage.add_argument("--wallet", required=True)
    exit_coverage.add_argument("--limit", type=int, default=5000)
    exit_coverage.add_argument("--since-ts", type=int, default=None)
    exit_coverage.add_argument("--condition-id", default=None)
    exit_coverage.set_defaults(func=cmd_wallet_flow_exit_coverage)
    report = wallet_sub.add_parser("report")
    report.add_argument("--wallet", default=None)
    report.set_defaults(func=cmd_wallet_flow_report)
    positions = wallet_sub.add_parser("positions")
    positions_sub = positions.add_subparsers(dest="positions_command", required=True)
    positions_fetch = positions_sub.add_parser("fetch")
    positions_fetch.add_argument("--wallet", required=True)
    positions_fetch.add_argument("--kind", required=True, choices=["current", "closed"])
    positions_fetch.add_argument("--market", default=None)
    positions_fetch.add_argument("--page-size", type=int, default=50)
    positions_fetch.add_argument("--max-pages", type=int, default=10)
    positions_fetch.set_defaults(func=cmd_wallet_flow_positions_fetch)
    positions_report = positions_sub.add_parser("report")
    positions_report.add_argument("--wallet", required=True)
    positions_report.add_argument("--limit", type=int, default=1000)
    positions_report.add_argument("--trade-limit", type=int, default=5000)
    positions_report.set_defaults(func=cmd_wallet_flow_positions_report)
    positions_current = positions_sub.add_parser("current")
    positions_current.add_argument("--wallet", required=True)
    positions_current.add_argument("--limit", type=int, default=50)
    positions_current.set_defaults(func=cmd_wallet_flow_positions_current)

    learning = sub.add_parser("learning")
    learning_sub = learning.add_subparsers(dest="learning_command", required=True)
    daily = learning_sub.add_parser("daily-report")
    daily.set_defaults(func=cmd_learning_daily)
    weekly = learning_sub.add_parser("weekly-review")
    weekly.set_defaults(func=cmd_learning_weekly)
    hypotheses = learning_sub.add_parser("hypotheses")
    hypotheses.add_argument("--status", default=None)
    hypotheses.set_defaults(func=cmd_learning_hypotheses)
    memories = learning_sub.add_parser("memories")
    memories_sub = memories.add_subparsers(dest="memories_command", required=True)
    mem_search = memories_sub.add_parser("search")
    mem_search.add_argument("--query", default=None)
    mem_search.add_argument("--memory-type", default=None, choices=["episodic", "semantic", "procedural"])
    mem_search.add_argument("--strategy-id", default=None)
    mem_search.add_argument("--wallet", default=None)
    mem_search.add_argument("--market-category", default=None)
    mem_search.set_defaults(func=cmd_learning_memory_search)
    promote = learning_sub.add_parser("promote-candidate")
    promote.add_argument("--rule-id", required=True)
    promote.add_argument("--paper-only", action="store_true")
    promote.add_argument("--human-approved", action="store_true")
    promote.add_argument("--reason", default="human approved paper promotion")
    promote.set_defaults(func=cmd_learning_promote)
    retire = learning_sub.add_parser("retire-rule")
    retire.add_argument("--rule-id", required=True)
    retire.add_argument("--reason", default="retired by operator")
    retire.set_defaults(func=cmd_learning_retire)

    crypto_latency = sub.add_parser("crypto-latency")
    crypto_sub = crypto_latency.add_subparsers(dest="crypto_latency_command", required=True)
    crypto_discover = crypto_sub.add_parser("discover")
    crypto_discover.add_argument("--max-markets", type=int, default=20)
    crypto_discover.add_argument("--query", action="append", help="Gamma search query; may be repeated")
    crypto_discover.add_argument("--debug-candidates", action="store_true")
    crypto_discover.set_defaults(func=cmd_crypto_latency_discover)
    crypto_record = crypto_sub.add_parser("record")
    crypto_record.add_argument("--seconds", type=int, default=300)
    crypto_record.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    crypto_record.add_argument("--fixture", action="store_true", help="Publish deterministic local crypto events into the recorder")
    crypto_record.add_argument("--min-move-pct", type=float, default=0.08)
    crypto_record.add_argument("--max-age-ms", type=int, default=2500)
    crypto_record.add_argument("--max-deviation-pct", type=float, default=0.25)
    crypto_record.add_argument("--min-sources", type=int, default=2)
    crypto_record.add_argument("--cooldown-ms", type=int, default=5000)
    crypto_record.add_argument("--write-artifacts", action="store_true")
    crypto_record.add_argument("--disable-rtds", action="store_true")
    crypto_record.add_argument("--use-watchlist", action="store_true")
    crypto_record.add_argument("--max-watchlist-markets", type=int, default=20)
    crypto_record.set_defaults(func=cmd_crypto_latency_record)
    crypto_report = crypto_sub.add_parser("report")
    crypto_report.set_defaults(func=cmd_crypto_latency_report)
    crypto_watchlist = crypto_sub.add_parser("watchlist")
    crypto_watchlist.add_argument("--limit", type=int, default=50)
    crypto_watchlist.add_argument("--all", action="store_true")
    watchlist_sub = crypto_watchlist.add_subparsers(dest="watchlist_action")
    watchlist_add = watchlist_sub.add_parser("add")
    watchlist_add.add_argument("--condition-id", required=True)
    watchlist_add.add_argument("--slug", required=True)
    watchlist_add.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    watchlist_add.add_argument("--yes-token-id", required=True)
    watchlist_add.add_argument("--no-token-id", required=True)
    watchlist_add.add_argument("--up-token-id", default=None)
    watchlist_add.add_argument("--down-token-id", default=None)
    watchlist_add.add_argument("--yes-direction", choices=["up", "down"], default=None)
    watchlist_add.add_argument("--question", default=None)
    watchlist_clear = watchlist_sub.add_parser("clear")
    watchlist_import = watchlist_sub.add_parser("import")
    watchlist_import.add_argument("--file", required=True)
    watchlist_health = watchlist_sub.add_parser("health")
    watchlist_health.add_argument("--symbol", default=None)
    watchlist_disable = watchlist_sub.add_parser("disable")
    watchlist_disable.add_argument("--condition-id", required=True)
    watchlist_enable = watchlist_sub.add_parser("enable")
    watchlist_enable.add_argument("--condition-id", required=True)
    watchlist_prune = watchlist_sub.add_parser("prune-bad")
    watchlist_prune.add_argument("--symbol", default=None)
    watchlist_prune.add_argument("--dry-run", action="store_true")
    crypto_watchlist.set_defaults(func=cmd_crypto_latency_watchlist)
    crypto_health = crypto_sub.add_parser("source-health")
    crypto_health.set_defaults(func=cmd_crypto_latency_source_health)
    crypto_consensus = crypto_sub.add_parser("consensus")
    crypto_consensus.add_argument("--symbol", required=True)
    crypto_consensus.add_argument("--last", type=int, default=20)
    crypto_consensus.set_defaults(func=cmd_crypto_latency_consensus)
    crypto_events = crypto_sub.add_parser("events")
    crypto_events.add_argument("--symbol", default=None)
    crypto_events.add_argument("--last", type=int, default=20)
    crypto_events.set_defaults(func=cmd_crypto_latency_events)
    crypto_sweep = crypto_sub.add_parser("threshold-sweep")
    crypto_sweep.add_argument("--symbol", required=True)
    crypto_sweep.add_argument("--lookback-ms", type=int, default=3000)
    crypto_sweep.add_argument("--cooldown-ms", type=int, default=0)
    crypto_sweep.add_argument("--thresholds", default="0.03,0.05,0.08,0.12")
    crypto_sweep.add_argument("--last", type=int, default=5000)
    crypto_sweep.set_defaults(func=cmd_crypto_latency_threshold_sweep)
    crypto_raw = crypto_sub.add_parser("raw-samples")
    crypto_raw.add_argument("--source", required=True)
    crypto_raw.add_argument("--last", type=int, default=20)
    crypto_raw.set_defaults(func=cmd_crypto_latency_raw_samples)
    crypto_replay_opps = crypto_sub.add_parser("replay-opportunities")
    crypto_replay_opps.add_argument("--mode", default="local-l2", choices=["local-l2"])
    crypto_replay_opps.add_argument("--amount", type=float, default=5.0)
    crypto_replay_opps.add_argument("--limit", type=int, default=100)
    crypto_replay_opps.set_defaults(func=cmd_crypto_latency_replay_opportunities)
    crypto_opps = crypto_sub.add_parser("opportunities")
    crypto_opps.add_argument("--limit", type=int, default=50)
    crypto_opps.set_defaults(func=cmd_crypto_latency_opportunities)

    crypto_paper = sub.add_parser("crypto-paper")
    crypto_paper_sub = crypto_paper.add_subparsers(dest="crypto_paper_command", required=True)
    crypto_paper_watch = crypto_paper_sub.add_parser("watch")
    crypto_paper_watch.add_argument("--seconds", type=int, default=300)
    crypto_paper_watch.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    crypto_paper_watch.add_argument("--from-watchlist", action="store_true")
    crypto_paper_watch.add_argument("--max-watchlist-markets", type=int, default=20)
    crypto_paper_watch.add_argument("--amount", type=float, default=5.0)
    crypto_paper_watch.add_argument("--min-move-pct", type=float, default=0.03)
    crypto_paper_watch.add_argument("--max-age-ms", type=int, default=2500)
    crypto_paper_watch.add_argument("--max-deviation-pct", type=float, default=0.25)
    crypto_paper_watch.add_argument("--min-sources", type=int, default=2)
    crypto_paper_watch.add_argument("--cooldown-ms", type=int, default=5000)
    crypto_paper_watch.add_argument("--threshold-grid", default="0.01,0.02,0.03,0.05,0.08")
    crypto_paper_watch.add_argument("--min-strategy-threshold-pct", type=float, default=0.03)
    crypto_paper_watch.add_argument("--write-artifacts", action="store_true")
    crypto_paper_watch.add_argument("--artifact-dir", default="artifacts/forward_paper")
    crypto_paper_watch.add_argument("--max-event-samples", type=int, default=50)
    crypto_paper_watch.add_argument("--take-profit-cents", type=float, default=8.0)
    crypto_paper_watch.add_argument("--stop-loss-cents", type=float, default=4.0)
    crypto_paper_watch.add_argument("--timeout-seconds", type=int, default=900)
    crypto_paper_watch.add_argument("--disable-rtds", action="store_true")
    crypto_paper_watch.add_argument("--fixture", action="store_true")
    crypto_paper_watch.add_argument(
        "--healthy-only",
        action="store_true",
        help="Label this forward-paper run as restricted to market-quality-gated opportunities.",
    )
    crypto_paper_watch.set_defaults(func=cmd_crypto_paper_watch)
    crypto_paper_positions = crypto_paper_sub.add_parser("positions")
    crypto_paper_positions.add_argument("--open", action="store_true")
    crypto_paper_positions.add_argument("--closed", action="store_true")
    crypto_paper_positions.add_argument("--run-id", default=None)
    crypto_paper_positions.add_argument("--include-fixture", action="store_true")
    crypto_paper_positions.add_argument("--limit", type=int, default=100)
    crypto_paper_positions.set_defaults(func=cmd_crypto_paper_positions)
    crypto_paper_report = crypto_paper_sub.add_parser("report")
    crypto_paper_report.add_argument("--run-id", default=None)
    crypto_paper_report.add_argument("--include-fixture", action="store_true")
    crypto_paper_report.add_argument("--aggregate", action="store_true")
    crypto_paper_report.set_defaults(func=cmd_crypto_paper_report)
    crypto_paper_signals = crypto_paper_sub.add_parser("signals")
    crypto_paper_signals.add_argument("--run-id", default=None)
    crypto_paper_signals.add_argument("--last", type=int, default=50)
    crypto_paper_signals.add_argument("--include-fixture", action="store_true")
    crypto_paper_signals.set_defaults(rejected_only=False)
    crypto_paper_signals.set_defaults(func=cmd_crypto_paper_signals)
    crypto_paper_rejected = crypto_paper_sub.add_parser("rejected")
    crypto_paper_rejected.add_argument("--run-id", default=None)
    crypto_paper_rejected.add_argument("--last", type=int, default=50)
    crypto_paper_rejected.add_argument("--include-fixture", action="store_true")
    crypto_paper_rejected.add_argument("--reason", default=None)
    crypto_paper_rejected.set_defaults(rejected_only=True)
    crypto_paper_rejected.set_defaults(func=cmd_crypto_paper_signals)
    crypto_paper_explain = crypto_paper_sub.add_parser("explain")
    crypto_paper_explain.add_argument("--signal-id", required=True)
    crypto_paper_explain.set_defaults(func=cmd_crypto_paper_explain)
    crypto_paper_l2_context = crypto_paper_sub.add_parser("l2-context")
    crypto_paper_l2_context.add_argument("--signal-id", required=True)
    crypto_paper_l2_context.add_argument("--levels", type=int, default=5)
    crypto_paper_l2_context.set_defaults(func=cmd_crypto_paper_l2_context)
    crypto_paper_runs = crypto_paper_sub.add_parser("runs")
    crypto_paper_runs.add_argument("--limit", type=int, default=20)
    crypto_paper_runs.add_argument("--include-fixture", action="store_true")
    crypto_paper_runs.set_defaults(func=cmd_crypto_paper_runs)
    crypto_paper_artifacts = crypto_paper_sub.add_parser("artifacts")
    crypto_paper_artifacts.add_argument("--run-id", required=True)
    crypto_paper_artifacts.set_defaults(func=cmd_crypto_paper_artifacts)
    crypto_paper_readiness = crypto_paper_sub.add_parser("readiness")
    crypto_paper_readiness.add_argument("--include-fixture", action="store_true")
    crypto_paper_readiness.add_argument("--min-signals", type=int, default=30)
    crypto_paper_readiness.add_argument("--min-positions", type=int, default=5)
    crypto_paper_readiness.set_defaults(func=cmd_crypto_paper_readiness)
    crypto_paper_campaign_summary = crypto_paper_sub.add_parser("campaign-summary")
    crypto_paper_campaign_summary.add_argument("--db", action="append", required=True)
    crypto_paper_campaign_summary.add_argument("--output", default=None)
    crypto_paper_campaign_summary.add_argument("--include-fixture", action="store_true")
    crypto_paper_campaign_summary.add_argument("--include-signals", action="store_true")
    crypto_paper_campaign_summary.set_defaults(func=cmd_crypto_paper_campaign_summary)

    strategy_arena = sub.add_parser("strategy-arena")
    strategy_arena_sub = strategy_arena.add_subparsers(dest="strategy_arena_command", required=True)
    strategy_arena_run = strategy_arena_sub.add_parser("run")
    strategy_arena_run.add_argument("--db", action="append", required=True)
    strategy_arena_run.add_argument("--config", default="config/strategy_arena.yaml")
    strategy_arena_run.add_argument("--output", default=None)
    strategy_arena_run.add_argument("--include-fixture", action="store_true")
    strategy_arena_run.set_defaults(func=cmd_strategy_arena_run)
    strategy_arena_report = strategy_arena_sub.add_parser("report")
    strategy_arena_report.add_argument("--file", default=None)
    strategy_arena_report.set_defaults(func=cmd_strategy_arena_report)
    strategy_arena_compare = strategy_arena_sub.add_parser("compare")
    strategy_arena_compare.add_argument("--baseline", default="no_trade")
    strategy_arena_compare.add_argument("--file", default=None)
    strategy_arena_compare.set_defaults(func=cmd_strategy_arena_compare)
    strategy_arena_artifacts = strategy_arena_sub.add_parser("artifacts")
    strategy_arena_artifacts.add_argument("--file", default=None)
    strategy_arena_artifacts.set_defaults(func=cmd_strategy_arena_artifacts)

    evidence_dashboard_parser = sub.add_parser("evidence-dashboard")
    evidence_dashboard_parser.add_argument("--db-glob", action="append", required=True)
    evidence_dashboard_parser.add_argument("--output", default="artifacts/evidence/latest.json")
    evidence_dashboard_parser.add_argument("--include-fixture", action="store_true")
    evidence_dashboard_parser.set_defaults(func=cmd_evidence_dashboard)

    l2 = sub.add_parser("l2-recorder")
    l2_sub = l2.add_subparsers(dest="l2_command", required=True)
    l2_start = l2_sub.add_parser("start")
    l2_start.add_argument("--token-id", action="append", default=[])
    l2_start.add_argument("--from-crypto-watchlist", action="store_true")
    l2_start.add_argument("--max-watchlist-markets", type=int, default=20)
    l2_start.add_argument("--seconds", type=int, default=300)
    l2_start.add_argument("--fixture", action="store_true")
    l2_start.set_defaults(func=cmd_l2_recorder_start)
    l2_status = l2_sub.add_parser("status")
    l2_status.add_argument("--limit", type=int, default=10)
    l2_status.set_defaults(func=cmd_l2_recorder_status)
    l2_coverage = l2_sub.add_parser("coverage")
    l2_coverage.add_argument("--token-id", default=None)
    l2_coverage.set_defaults(func=cmd_l2_recorder_coverage)
    l2_reconstruct = l2_sub.add_parser("reconstruct")
    l2_reconstruct.add_argument("--token-id", required=True)
    l2_reconstruct.add_argument("--timestamp-ms", type=int, required=True)
    l2_reconstruct.set_defaults(func=cmd_l2_recorder_reconstruct)

    dry = sub.add_parser("dry-run")
    dry.add_argument("--market", default=None, help="Market identifier: slug, condition ID, token ID, or search text")
    dry.add_argument("--market-slug", default=None)
    dry.add_argument("--condition-id", default=None)
    dry.add_argument("--token-id", default=None)
    dry.add_argument("--side", required=True, choices=["YES", "NO", "yes", "no"])
    dry.add_argument("--amount", required=True, type=float)
    dry.add_argument("--fixture", action="store_true", help="Use deterministic local fixture data")
    dry.set_defaults(func=cmd_dry_run)

    portfolio = sub.add_parser("portfolio")
    portfolio.add_argument("--mode", default="paper", choices=["paper"])
    portfolio.set_defaults(func=cmd_portfolio)

    live = sub.add_parser("live")
    live.add_argument("--market", required=True)
    live.add_argument("--side", required=True, choices=["YES", "NO", "yes", "no"])
    live.add_argument("--amount", required=True, type=float)
    live.add_argument("--live", action="store_true")
    live.set_defaults(func=cmd_live)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
