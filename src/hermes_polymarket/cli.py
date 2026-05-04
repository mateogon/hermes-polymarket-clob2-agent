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
import sys
import time
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


def cmd_environment_show(args: argparse.Namespace) -> int:
    previous = os.environ.get("HERMES_ENV")
    if args.env:
        os.environ["HERMES_ENV"] = args.env
    try:
        settings = _settings()
    finally:
        if args.env:
            if previous is None:
                os.environ.pop("HERMES_ENV", None)
            else:
                os.environ["HERMES_ENV"] = previous
    print(
        json.dumps(
            {
                "environment": settings.environment,
                "mode": settings.mode,
                "database_path": str(settings.database_path),
                "artifact_dir": str(settings.artifact_dir),
                "allow_live_trading": settings.allow_live_trading,
                "requires_pre_live_audit": settings.requires_pre_live_audit,
                "data_quality": "environment_config",
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def cmd_research(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.research_ledger import (
        experiment_report,
        get_hypothesis,
        list_hypotheses,
        update_hypothesis,
        upsert_hypothesis,
    )

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        if args.research_command == "hypothesis":
            if args.hypothesis_command == "add":
                payload = upsert_hypothesis(
                    db,
                    hypothesis_id=args.id,
                    strategy=args.strategy,
                    market_family=args.market_family,
                    claim=args.claim,
                    status=args.status,
                    data_quality=args.data_quality,
                    evidence=json.loads(args.evidence_json),
                    next_action=args.next_action,
                    proposed_test=json.loads(args.proposed_test_json),
                    result=json.loads(args.result_json),
                )
                print(json.dumps({"status": "stored", "environment": settings.environment, "hypothesis": payload}, indent=2, sort_keys=True))
                return 0
            if args.hypothesis_command == "list":
                rows = list_hypotheses(db, status=args.status, limit=args.limit)
                print(json.dumps({"environment": settings.environment, "hypotheses": rows}, indent=2, sort_keys=True))
                return 0
            if args.hypothesis_command == "show":
                row = get_hypothesis(db, args.id)
                if row is None:
                    print(json.dumps({"status": "not_found", "hypothesis_id": args.id}, indent=2, sort_keys=True))
                    return 2
                print(json.dumps({"environment": settings.environment, "hypothesis": row}, indent=2, sort_keys=True))
                return 0
            if args.hypothesis_command == "update":
                row = update_hypothesis(
                    db,
                    hypothesis_id=args.id,
                    status=args.status,
                    evidence=json.loads(args.evidence_json) if args.evidence_json else None,
                    next_action=args.next_action,
                    result=json.loads(args.result_json) if args.result_json else None,
                )
                if row is None:
                    print(json.dumps({"status": "not_found", "hypothesis_id": args.id}, indent=2, sort_keys=True))
                    return 2
                print(json.dumps({"status": "updated", "environment": settings.environment, "hypothesis": row}, indent=2, sort_keys=True))
                return 0
        if args.research_command == "experiments" and args.experiments_command == "report":
            report = experiment_report(db, limit=args.limit)
            print(json.dumps({"environment": settings.environment, **report}, indent=2, sort_keys=True))
            return 0
        if args.research_command == "data":
            payload = _research_data_command(args)
            print(json.dumps({"environment": settings.environment, **payload}, indent=2, sort_keys=True))
            return 0
    finally:
        db.close()
    print("unknown research command")
    return 2


def _research_data_command(args: argparse.Namespace) -> dict[str, Any]:
    from hermes_polymarket.data_sources.binance_historical import BinanceHistoricalClient
    from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi
    from hermes_polymarket.polymarket.gamma_client import GammaClient
    from hermes_polymarket.research.data_cache import ResearchDataCache

    cache = ResearchDataCache()
    if args.data_command == "status":
        return {"mode": "research_data_cache_status", **cache.status()}
    if args.data_command == "fetch":
        if args.kind == "gamma-market":
            gamma = GammaClient()
            try:
                markets = gamma.markets_by_slug(args.slug)
            finally:
                gamma.close()
            manifest = cache.write_gamma_market(slug=args.slug, markets=markets, params={"slug": args.slug})
            return {"mode": "research_data_fetch", "kind": args.kind, "manifest": manifest}
        if args.kind == "gamma-universe":
            gamma = GammaClient()
            events: list[dict[str, Any]] = []
            markets: list[dict[str, Any]] = []
            try:
                for offset in range(0, args.limit_events, args.page_size):
                    page = gamma.list_events(active="true", closed="false", order=args.order, ascending="false", limit=min(args.page_size, args.limit_events - offset), offset=offset)
                    events.extend(page)
                    if len(page) < min(args.page_size, args.limit_events - offset):
                        break
                for offset in range(0, args.limit_markets, args.page_size):
                    page = gamma.list_markets(active="true", closed="false", order=args.order, ascending="false", limit=min(args.page_size, args.limit_markets - offset), offset=offset)
                    markets.extend(page)
                    if len(page) < min(args.page_size, args.limit_markets - offset):
                        break
            finally:
                gamma.close()
            label = args.label or f"active_{args.order}_{args.limit_events}_{args.limit_markets}"
            manifest = cache.write_gamma_universe(
                label=label,
                events=events,
                markets=markets,
                params={"limit_events": args.limit_events, "limit_markets": args.limit_markets, "order": args.order, "page_size": args.page_size},
            )
            return {"mode": "research_data_fetch", "kind": args.kind, "manifest": manifest}
        if args.kind == "polymarket-trades":
            data_api = PolymarketDataApi()
            try:
                trades = data_api.get_trades(market=args.condition_id, limit=args.limit)
            finally:
                data_api.close()
            manifest = cache.write_polymarket_trades(condition_id=args.condition_id, trades=trades, params={"condition_id": args.condition_id, "limit": args.limit})
            return {"mode": "research_data_fetch", "kind": args.kind, "manifest": manifest}
        if args.kind == "binance-klines":
            binance = BinanceHistoricalClient()
            try:
                candles = binance.get_klines_paginated(
                    symbol=args.symbol,
                    interval=args.interval,
                    start_ts_ms=args.start_ts_ms,
                    end_ts_ms=args.end_ts_ms,
                    limit=args.limit,
                )
            finally:
                binance.close()
            manifest = cache.write_binance_klines(
                symbol=args.symbol,
                interval=args.interval,
                start_ts_ms=args.start_ts_ms,
                end_ts_ms=args.end_ts_ms,
                candles=candles,
                params={
                    "symbol": args.symbol,
                    "interval": args.interval,
                    "start_ts_ms": args.start_ts_ms,
                    "end_ts_ms": args.end_ts_ms,
                    "limit": args.limit,
                },
            )
            return {"mode": "research_data_fetch", "kind": args.kind, "manifest": manifest}
    return {"mode": "research_data_cache", "status": "unknown_command"}


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


def cmd_learning_memory_add(args: argparse.Namespace) -> int:
    from hermes_polymarket.learning.memory_store import MemoryRecord, MemoryStore

    db, _ = _learning_db()
    try:
        content = json.loads(args.content_json)
        evidence = json.loads(args.evidence_json)
        store = MemoryStore(db)
        store.put(
            MemoryRecord(
                memory_id=args.memory_id,
                memory_type=args.memory_type,
                status=args.status,
                strategy_id=args.strategy_id,
                wallet=args.wallet,
                market_category=args.market_category,
                content=content,
                evidence=evidence,
                confidence=args.confidence,
                active_in_paper=args.active_in_paper,
                active_in_live=False,
            )
        )
        print(json.dumps({"status": "stored", "memory_id": args.memory_id, "active_in_live": False}, indent=2, sort_keys=True))
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


def cmd_crypto_latency_discover_updown(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.updown_discovery import discover_updown_from_events
    from hermes_polymarket.polymarket.gamma_client import GammaClient

    symbols = {symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip()}
    if not symbols:
        print("discover-updown requires at least one symbol")
        return 2

    gamma = GammaClient()
    events: list[dict[str, Any]] = []
    try:
        remaining = args.limit
        offset = 0
        while remaining > 0:
            page_limit = min(300, remaining)
            page = gamma.list_events(active="true", closed="false", order="volume_24hr", ascending="false", limit=page_limit, offset=offset)
            if not page:
                break
            events.extend(page)
            if len(page) < page_limit:
                break
            remaining -= page_limit
            offset += page_limit
        payload = discover_updown_from_events(events, symbols=symbols)
        payload["mode"] = "measurement_paper_only"
        payload["status"] = "discovered" if payload["discovered"] else "no_active_updown_markets_found"
        payload["symbols"] = sorted(symbols)
        payload["events_seen"] = len(events)
        if not args.debug:
            payload.pop("debug", None)
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        gamma.close()
    return 0


def cmd_crypto_latency_universe(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.market_universe import (
        candidate_to_watchlist_row,
        fetch_gamma_universe,
        filter_universe_candidates,
        load_universe_scan,
        scan_market_universe,
        write_universe_scan,
    )
    from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus
    from hermes_polymarket.polymarket.gamma_client import GammaClient
    from hermes_polymarket.storage.crypto_watchlist import crypto_market_watchlist, upsert_crypto_market_watchlist

    symbols = {symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip()} if hasattr(args, "symbols") else None

    if args.universe_action == "scan":
        if not symbols:
            print("universe scan requires at least one symbol")
            return 2
        gamma = GammaClient()
        try:
            events, markets = fetch_gamma_universe(gamma, limit_events=args.limit_events, limit_markets=args.limit_markets)
            payload = scan_market_universe(events=events, markets=markets, symbols=symbols)
            payload["symbols"] = sorted(symbols)
            payload["limits"] = {"events": args.limit_events, "markets": args.limit_markets}
            output = Path(args.output)
            write_universe_scan(output, payload)
            payload["output"] = str(output)
            print(json.dumps(payload, indent=2, sort_keys=True))
        finally:
            gamma.close()
        return 0

    if args.universe_action == "candidates":
        payload = load_universe_scan(Path(args.file))
        rows = filter_universe_candidates(payload, market_type=args.market_type, min_score=args.min_score, limit=args.limit)
        print(
            json.dumps(
                {
                    "mode": "measurement_paper_only",
                    "file": args.file,
                    "market_type": args.market_type,
                    "min_score": args.min_score,
                    "candidates": rows,
                    "count": len(rows),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    if args.universe_action == "strike-candidates":
        if not args.symbol:
            print("strike-candidates requires --symbol")
            return 2
        gamma = GammaClient()
        try:
            events = gamma.list_events(slug=args.event_slug, active="true", closed="false", limit=5)
            if not events:
                print(json.dumps({"status": "event_not_found", "event_slug": args.event_slug}, indent=2, sort_keys=True))
                return 2
            event = events[0]
            payload = scan_market_universe(events=[event], markets=[], symbols={args.symbol})
            price, sources, max_dev = current_reference_consensus(args.symbol)
            candidates: list[dict[str, Any]] = []
            for row in filter_universe_candidates(payload, market_type=None, min_score=0.0, limit=500):
                if row.get("market_type") not in {"above_strike", "below_strike"}:
                    continue
                strike = row.get("strike_price")
                if strike is None:
                    continue
                distance_pct = (price - float(strike)) / float(strike) * 100.0
                market_score = float(row.get("score") or 0.0)
                abs_distance = abs(distance_pct)
                recommended = 0.25 <= abs_distance <= 2.0 and market_score >= 0.8
                candidates.append(
                    {
                        **row,
                        "current_price": price,
                        "distance_pct": distance_pct,
                        "market_score": market_score,
                        "rest_book_ok": None,
                        "l2_quality": None,
                        "recommended": recommended,
                        "selection_reasons": [
                            *([] if recommended else ["outside_distance_or_score_gate"]),
                            "score_l2_not_run" if getattr(args, "score_l2", False) else "universe_score_only",
                        ],
                    }
                )
            candidates.sort(key=lambda row: abs(float(row["distance_pct"])))
            if args.auto_pick_nearest:
                candidates = candidates[:1]
            else:
                candidates = candidates[: args.limit]
            if args.score_l2 and candidates:
                from hermes_polymarket.crypto.market_quality import evaluate_market_quality

                settings = _settings()
                client = ClobV2Client(settings)
                try:
                    for candidate in candidates:
                        token_quality: dict[str, Any] = {}
                        rest_ok = True
                        allowed = True
                        quality_reasons: list[str] = []
                        for outcome, token_id in (("YES", candidate.get("yes_token_id")), ("NO", candidate.get("no_token_id"))):
                            if not token_id:
                                rest_ok = False
                                allowed = False
                                token_quality[outcome] = {"allowed": False, "reason": "missing_token_id"}
                                quality_reasons.append("missing_token_id")
                                continue
                            try:
                                book = client.get_orderbook(str(token_id))
                                quality = evaluate_market_quality(book).to_dict()
                                token_quality[outcome] = {
                                    "token_id": str(token_id),
                                    "best_bid": book.best_bid,
                                    "best_ask": book.best_ask,
                                    "quality": quality,
                                }
                                if not quality.get("allowed"):
                                    allowed = False
                                    quality_reasons.append(str(quality.get("reason") or "quality_rejected"))
                            except Exception as exc:  # noqa: BLE001 - candidate scoring reports per-token failures.
                                rest_ok = False
                                allowed = False
                                reason = str(exc)
                                token_quality[outcome] = {"token_id": str(token_id), "allowed": False, "reason": reason}
                                quality_reasons.append(reason)
                        candidate["rest_book_ok"] = rest_ok
                        candidate["l2_quality"] = {
                            "all_allowed": allowed,
                            "tokens": token_quality,
                            "reasons": sorted(set(quality_reasons)),
                        }
                        candidate["recommended"] = bool(candidate["recommended"] and rest_ok and allowed)
                        candidate["selection_reasons"] = [
                            reason for reason in candidate["selection_reasons"] if reason != "score_l2_not_run"
                        ]
                        candidate["selection_reasons"].append("l2_quality_ok" if rest_ok and allowed else "l2_quality_rejected")
                finally:
                    client.close()
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "event_slug": args.event_slug,
                        "symbol": args.symbol,
                        "current_price_source": args.current_price_source,
                        "current_price": price,
                        "consensus_sources": list(sources),
                        "max_deviation_pct": max_dev,
                        "candidates": candidates,
                        "recommendation": "prefer near-atm with good liquidity",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        finally:
            gamma.close()
        return 0

    if args.universe_action == "strike-events":
        if not symbols:
            print("strike-events requires at least one symbol")
            return 2
        gamma = GammaClient()
        try:
            events, _markets = fetch_gamma_universe(gamma, limit_events=args.limit_events, limit_markets=0)
            payload = scan_market_universe(events=events, markets=[], symbols=symbols)
            grouped: dict[tuple[str, str], dict[str, Any]] = {}
            for row in payload.get("candidates", []):
                if not isinstance(row, dict) or row.get("market_type") not in {"above_strike", "below_strike"}:
                    continue
                key = (str(row.get("event_slug") or ""), str(row.get("symbol") or ""))
                if not key[0] or not key[1]:
                    continue
                group = grouped.setdefault(
                    key,
                    {
                        "event_slug": key[0],
                        "event_title": row.get("event_title"),
                        "symbol": key[1],
                        "candidate_count": 0,
                        "best_score": 0.0,
                        "market_types": {},
                        "top_candidates": [],
                    },
                )
                group["candidate_count"] += 1
                group["best_score"] = max(float(group["best_score"]), float(row.get("score") or 0.0))
                market_types = group["market_types"]
                market_type = str(row.get("market_type"))
                market_types[market_type] = int(market_types.get(market_type, 0)) + 1
                group["top_candidates"].append(
                    {
                        "slug": row.get("slug"),
                        "market_type": row.get("market_type"),
                        "score": row.get("score"),
                        "strike_price": row.get("strike_price"),
                        "comparator": row.get("comparator"),
                    }
                )
            events_out = []
            for group in grouped.values():
                if int(group["candidate_count"]) < args.min_candidates:
                    continue
                group["top_candidates"] = sorted(group["top_candidates"], key=lambda item: float(item.get("score") or 0.0), reverse=True)[:5]
                group["recommended"] = float(group["best_score"]) >= args.min_score
                events_out.append(group)
            events_out.sort(key=lambda row: (bool(row["recommended"]), float(row["best_score"]), int(row["candidate_count"])), reverse=True)
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "symbols": sorted(symbols),
                        "scanned_events": len(events),
                        "min_candidates": args.min_candidates,
                        "min_score": args.min_score,
                        "events": events_out[: args.limit],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        finally:
            gamma.close()
        return 0

    if args.universe_action == "multi-strike-candidates":
        if not args.symbol:
            print("multi-strike-candidates requires --symbol")
            return 2
        from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target

        gamma = GammaClient()
        try:
            events = gamma.list_events(slug=args.event_slug, active="true", closed="false", limit=5)
            if not events:
                print(json.dumps({"status": "event_not_found", "event_slug": args.event_slug}, indent=2, sort_keys=True))
                return 2
            event = events[0]
            payload = scan_market_universe(events=[event], markets=[], symbols={args.symbol})
            price, sources, max_dev = current_reference_consensus(args.symbol)
            now = datetime.now(timezone.utc)
            candidates: list[dict[str, Any]] = []
            for row in filter_universe_candidates(payload, market_type="multi_strike_event", min_score=0.0, limit=500):
                if not row.get("active") or row.get("closed"):
                    continue
                target = parse_multi_strike_target(f"{row.get('question') or ''} {row.get('slug') or ''}", current_price=price)
                target_price = row.get("strike_price") or (target.target_price if target is not None else None)
                if target_price is None:
                    continue
                seconds_to_expiry = 1.0
                if row.get("end_date"):
                    with contextlib.suppress(ValueError):
                        parsed = datetime.fromisoformat(str(row["end_date"]).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        seconds_to_expiry = max(1.0, (parsed - now).total_seconds())
                fv = fair_value_target_hit(
                    current_price=price,
                    target_price=float(target_price),
                    seconds_to_expiry=seconds_to_expiry,
                    annualized_vol=args.annualized_vol,
                )
                distance_abs = abs(float(fv.distance_pct))
                market_score = float(row.get("score") or 0.0)
                recommended = market_score >= args.min_score and args.min_distance_pct <= distance_abs <= args.max_distance_pct
                candidates.append(
                    {
                        **row,
                        "current_price": price,
                        "target_price": float(target_price),
                        "target_direction": fv.direction,
                        "distance_pct": fv.distance_pct,
                        "market_score": market_score,
                        "fair_value": fv.to_dict(),
                        "rest_book_ok": None,
                        "l2_quality": None,
                        "recommended": recommended,
                        "selection_reasons": [
                            *([] if recommended else ["outside_distance_or_score_gate"]),
                            "score_l2_not_run" if getattr(args, "score_l2", False) else "universe_score_only",
                            "multi_strike_long_dated_research_only",
                        ],
                    }
                )
            candidates.sort(key=lambda row: abs(float(row["distance_pct"])))
            candidates = candidates[: args.limit]
            if args.score_l2 and candidates:
                from hermes_polymarket.crypto.market_quality import evaluate_market_quality

                settings = _settings()
                client = ClobV2Client(settings)
                try:
                    for candidate in candidates:
                        token_quality: dict[str, Any] = {}
                        rest_ok = True
                        allowed = True
                        quality_reasons: list[str] = []
                        for outcome, token_id in (("YES", candidate.get("yes_token_id")), ("NO", candidate.get("no_token_id"))):
                            if not token_id:
                                rest_ok = False
                                allowed = False
                                token_quality[outcome] = {"allowed": False, "reason": "missing_token_id"}
                                quality_reasons.append("missing_token_id")
                                continue
                            try:
                                book = client.get_orderbook(str(token_id))
                                quality = evaluate_market_quality(book).to_dict()
                                best_ask = book.best_ask
                                probability_yes = float(candidate["fair_value"]["probability_yes"])
                                edge = probability_yes - best_ask if outcome == "YES" and best_ask is not None else (1.0 - probability_yes) - best_ask if best_ask is not None else None
                                token_quality[outcome] = {
                                    "token_id": str(token_id),
                                    "best_bid": book.best_bid,
                                    "best_ask": best_ask,
                                    "fair_value_edge": edge,
                                    "quality": quality,
                                }
                                if not quality.get("allowed"):
                                    allowed = False
                                    quality_reasons.append(str(quality.get("reason") or "quality_rejected"))
                            except Exception as exc:  # noqa: BLE001 - candidate scoring reports per-token failures.
                                rest_ok = False
                                allowed = False
                                reason = str(exc)
                                token_quality[outcome] = {"token_id": str(token_id), "allowed": False, "reason": reason}
                                quality_reasons.append(reason)
                        candidate["rest_book_ok"] = rest_ok
                        candidate["l2_quality"] = {
                            "all_allowed": allowed,
                            "tokens": token_quality,
                            "reasons": sorted(set(quality_reasons)),
                        }
                        candidate["recommended"] = bool(candidate["recommended"] and rest_ok and allowed)
                        candidate["selection_reasons"] = [
                            reason for reason in candidate["selection_reasons"] if reason != "score_l2_not_run"
                        ]
                        candidate["selection_reasons"].append("l2_quality_ok" if rest_ok and allowed else "l2_quality_rejected")
                finally:
                    client.close()
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "event_slug": args.event_slug,
                        "symbol": args.symbol,
                        "data_quality": "multi_strike_research_only",
                        "current_price": price,
                        "current_price_source": args.current_price_source,
                        "consensus_sources": list(sources),
                        "max_deviation_pct": max_dev,
                        "annualized_vol": args.annualized_vol,
                        "candidates": candidates,
                        "recommendation": "research_only_do_not_run_watch_v2_without_multi_strike_strategy",
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        finally:
            gamma.close()
        return 0

    if args.universe_action == "import-best":
        if args.market_type != "up_down":
            print(json.dumps({"status": "unsupported_market_type", "reason": "import-best currently supports up_down only"}, indent=2, sort_keys=True))
            return 2
        payload = load_universe_scan(Path(args.file))
        rows = filter_universe_candidates(payload, market_type=args.market_type, min_score=args.min_score, limit=args.limit)
        settings = _settings()
        db = Database(settings.database_path)
        db.init_schema(settings.initial_bankroll)
        imported: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        try:
            references: dict[str, Any] = {}
            for candidate in rows:
                symbol = str(candidate.get("symbol") or "")
                reference = references.get(symbol)
                if symbol and symbol not in references:
                    try:
                        reference = current_reference_consensus(symbol)
                    except Exception as exc:  # noqa: BLE001 - import can continue without reference.
                        reference = None
                        skipped.append({"slug": candidate.get("slug"), "reason": f"reference_unavailable:{exc}"})
                    references[symbol] = reference
                if reference is None:
                    continue
                row = candidate_to_watchlist_row(candidate, reference=reference, duration_seconds=args.duration_seconds)
                if row is None:
                    skipped.append({"slug": candidate.get("slug"), "reason": "not_importable_or_direction_mapping_ambiguous"})
                    continue
                upsert_crypto_market_watchlist(db, row)
                imported.append({"condition_id": row["condition_id"], "slug": row["slug"], "symbol": row["symbol"], "score": candidate.get("score")})
            watchlist = crypto_market_watchlist(db, active_only=False, limit=50)
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "status": "imported_best" if imported else "no_candidates_imported",
                        "file": args.file,
                        "imported": imported,
                        "skipped": skipped,
                        "watchlist": watchlist,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        finally:
            db.close()
        return 0

    print(f"unknown universe action: {args.universe_action}")
    return 2


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


def cmd_crypto_latency_availability_monitor(args: argparse.Namespace) -> int:
    from hermes_polymarket.crypto.market_universe import fetch_gamma_universe, scan_market_universe

    symbols = tuple(symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip())
    market_types = {market_type.strip() for market_type in args.market_types.split(",") if market_type.strip()}
    if not symbols:
        print("availability-monitor requires at least one symbol")
        return 2
    started = time.time()
    deadline = started + max(0, args.duration_seconds)
    checks: list[dict[str, Any]] = []
    aggregate: dict[str, dict[str, Any]] = {
        symbol: {
            "up_down_healthy_checks": 0,
            "strike_healthy_checks": 0,
            "multi_strike_checks": 0,
            "best_score": 0.0,
            "best_up_down_score": 0.0,
            "best_strike_score": 0.0,
            "best_multi_strike_score": 0.0,
            "best_event_slug": None,
        }
        for symbol in symbols
    }

    attempt = 0
    while True:
        attempt += 1
        gamma = GammaClient()
        try:
            events, markets = fetch_gamma_universe(gamma, limit_events=args.limit_events, limit_markets=args.limit_markets)
        finally:
            gamma.close()
        universe = scan_market_universe(events=events, markets=markets, symbols=set(symbols))
        rows = [row for row in universe.get("candidates", []) if isinstance(row, dict)]
        by_symbol: dict[str, dict[str, Any]] = {}
        for symbol in symbols:
            symbol_rows = [row for row in rows if row.get("symbol") == symbol]
            up_down = [row for row in symbol_rows if row.get("market_type") == "up_down" and float(row.get("score") or 0.0) >= args.min_score]
            strike = [
                row
                for row in symbol_rows
                if row.get("market_type") in {"above_strike", "below_strike"} and float(row.get("score") or 0.0) >= args.min_score
            ]
            multi_strike = [
                row
                for row in symbol_rows
                if row.get("market_type") == "multi_strike_event" and float(row.get("score") or 0.0) >= args.min_score
            ]
            best_rows = sorted(symbol_rows, key=lambda row: float(row.get("score") or 0.0), reverse=True)
            best = best_rows[0] if best_rows else {}
            best_up = max((float(row.get("score") or 0.0) for row in up_down), default=0.0)
            best_strike = max((float(row.get("score") or 0.0) for row in strike), default=0.0)
            best_multi = max((float(row.get("score") or 0.0) for row in multi_strike), default=0.0)
            aggregate_row = aggregate[symbol]
            aggregate_row["up_down_healthy_checks"] += int(bool(up_down) and "up_down" in market_types)
            aggregate_row["strike_healthy_checks"] += int(bool(strike) and "strike" in market_types)
            aggregate_row["multi_strike_checks"] += int(bool(multi_strike))
            aggregate_row["best_score"] = max(float(aggregate_row["best_score"]), float(best.get("score") or 0.0))
            aggregate_row["best_up_down_score"] = max(float(aggregate_row["best_up_down_score"]), best_up)
            aggregate_row["best_strike_score"] = max(float(aggregate_row["best_strike_score"]), best_strike)
            aggregate_row["best_multi_strike_score"] = max(float(aggregate_row["best_multi_strike_score"]), best_multi)
            if best.get("event_slug") and float(best.get("score") or 0.0) >= float(aggregate_row["best_score"]):
                aggregate_row["best_event_slug"] = best.get("event_slug")
            by_symbol[symbol] = {
                "up_down_candidates": len(up_down),
                "strike_candidates": len(strike),
                "multi_strike_candidates": len(multi_strike),
                "best_score": float(best.get("score") or 0.0),
                "best_market_type": best.get("market_type"),
                "best_event_slug": best.get("event_slug"),
                "best_slug": best.get("slug"),
            }
        checks.append(
            {
                "attempt": attempt,
                "ts_ms": int(time.time() * 1000),
                "scanned_events": universe.get("scanned_events"),
                "scanned_markets": universe.get("scanned_markets"),
                "classified": universe.get("classified"),
                "by_symbol": by_symbol,
            }
        )
        if args.duration_seconds <= 0 or time.time() >= deadline:
            break
        remaining = max(0.0, deadline - time.time())
        time.sleep(min(args.poll_seconds, remaining))

    availability = {
        symbol: {
            **row,
            "recommendation": (
                "run_v2_when_preflight_passes"
                if int(row["strike_healthy_checks"]) > 0 or int(row["up_down_healthy_checks"]) > 0
                else "evaluate_multi_strike_research_only"
                if int(row["multi_strike_checks"]) > 0
                else "waiting_for_healthy_venue"
            ),
        }
        for symbol, row in aggregate.items()
    }
    output = {
        "mode": "measurement_paper_only",
        "duration_seconds": max(0, int(time.time() - started)),
        "requested_duration_seconds": args.duration_seconds,
        "poll_seconds": args.poll_seconds,
        "checks": len(checks),
        "market_types": sorted(market_types),
        "min_score": args.min_score,
        "availability": availability,
        "latest_check": checks[-1] if checks else None,
        "recommendation": "Run v2 only when strike_healthy_checks or up_down_healthy_checks is greater than 0; evaluate multi_strike_event separately.",
    }
    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(output, indent=2, sort_keys=True) + "\n")
        output["output"] = str(output_path)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


def _rotate_strikes_for_watchlist(
    db: Database,
    settings: Any,
    *,
    symbol: str,
    event_slug: str,
    max_markets: int,
    min_score: float,
    duration_seconds: int,
    clear_existing: bool,
) -> tuple[dict[str, Any], int]:
    from hermes_polymarket.data_sources.base import now_ms
    from hermes_polymarket.crypto.market_universe import filter_universe_candidates, scan_market_universe
    from hermes_polymarket.crypto.strike_candidate_selector import StrikeRotationConfig, score_strike_candidate
    from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus
    from hermes_polymarket.storage.crypto_watchlist import deactivate_crypto_watchlist_strikes, upsert_crypto_market_watchlist

    symbol = symbol.lower()
    price, sources, max_dev = current_reference_consensus(symbol)
    gamma = GammaClient()
    clob = ClobV2Client(settings)
    try:
        events = gamma.list_events(slug=event_slug, active="true", closed="false", limit=5)
        if not events:
            return (
                {
                    "mode": "measurement_paper_only",
                    "status": "event_not_found",
                    "symbol": symbol,
                    "event_slug": event_slug,
                    "imported": 0,
                    "selected": [],
                    "rejected": [],
                },
                2,
            )
        universe = scan_market_universe(events=[events[0]], markets=[], symbols={symbol})
        candidates = [
            row
            for row in filter_universe_candidates(universe, market_type=None, min_score=0.0, limit=500)
            if row.get("market_type") in {"above_strike", "below_strike"}
        ]
        config = StrikeRotationConfig(min_market_score=min_score)
        scored: list[dict[str, Any]] = []
        for candidate in candidates:
            yes_book = no_book = None
            try:
                if candidate.get("yes_token_id"):
                    yes_book = clob.get_orderbook(str(candidate["yes_token_id"]))
                if candidate.get("no_token_id"):
                    no_book = clob.get_orderbook(str(candidate["no_token_id"]))
            except Exception:
                yes_book = yes_book
            scored.append(score_strike_candidate(candidate, current_price=price, yes_book=yes_book, no_book=no_book, config=config).to_dict())
        scored.sort(key=lambda row: (bool(row["recommended"]), float(row["rotation_score"])), reverse=True)
        selected = [row for row in scored if row["recommended"] and float(row["rotation_score"]) >= min_score][:max_markets]
        rejected = [
            {
                "slug": row["slug"],
                "score": row["rotation_score"],
                "reason": ",".join(row.get("reject_reasons") or ["below_min_score"]),
            }
            for row in scored
            if row not in selected
        ][:20]
        deactivated = deactivate_crypto_watchlist_strikes(db, symbol=symbol) if clear_existing else 0
        now = now_ms()
        window_start_ts = now // 1000
        window_end_ts = window_start_ts + duration_seconds
        imported = 0
        for row in selected:
            resolution_ts = None
            if row.get("end_date"):
                with contextlib.suppress(ValueError):
                    parsed = datetime.fromisoformat(str(row["end_date"]).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    resolution_ts = int(parsed.timestamp())
            upsert_crypto_market_watchlist(
                db,
                {
                    "condition_id": row["condition_id"],
                    "slug": row["slug"],
                    "question": row["question"],
                    "symbol": symbol,
                    "yes_token_id": row["yes_token_id"],
                    "no_token_id": row["no_token_id"],
                    "up_token_id": "",
                    "down_token_id": "",
                    "market_type": row["market_type"],
                    "strike_price": row.get("strike_price"),
                    "comparator": row.get("comparator"),
                    "resolution_ts": resolution_ts,
                    "direction_map": {},
                    "active": True,
                    "discovered_at_ms": now,
                    "end_ts_ms": window_end_ts * 1000,
                    "raw": {
                        "dynamic_strike_rotation": True,
                        "reference_price": price,
                        "window_start_ts": window_start_ts,
                        "window_end_ts": window_end_ts,
                        "consensus_sources": list(sources),
                        "max_deviation_pct": max_dev,
                        "rotation_score": row["rotation_score"],
                        "rotation_reasons": row.get("rotation_reasons", []),
                        "reject_reasons": row.get("reject_reasons", []),
                    },
                },
            )
            imported += 1
        payload = {
            "mode": "measurement_paper_only",
            "status": "rotated" if selected else "no_usable_strikes",
            "symbol": symbol,
            "event_slug": event_slug,
            "current_price": price,
            "consensus_sources": list(sources),
            "max_deviation_pct": max_dev,
            "deactivated": deactivated,
            "imported": imported,
            "selected": selected,
            "rejected": rejected,
        }
        return payload, 0 if selected else 2
    finally:
        gamma.close()
        clob.close()


def cmd_crypto_latency_watchlist(args: argparse.Namespace) -> int:
    from hermes_polymarket.data_sources.base import now_ms
    from hermes_polymarket.crypto.market_quality import watchlist_health_report
    from hermes_polymarket.storage.crypto_watchlist import (
        clear_crypto_market_watchlist,
        crypto_market_watchlist,
        deactivate_crypto_watchlist_strikes,
        set_crypto_market_reference,
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
        elif args.watchlist_action == "add-current-window":
            from hermes_polymarket.crypto.watchlist_seeding import seed_current_window_from_slug

            try:
                seed = seed_current_window_from_slug(
                    slug=args.slug,
                    symbol=args.symbol,
                    yes_direction=args.yes_direction,
                    duration_seconds=args.duration_seconds,
                    min_sources=args.min_sources,
                    max_deviation_pct=args.max_deviation_pct,
                )
            except ValueError as exc:
                print(
                    json.dumps(
                        {
                            "mode": "measurement_paper_only",
                            "status": "seed_failed",
                            "slug": args.slug,
                            "reason": str(exc),
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 2
            upsert_crypto_market_watchlist(db, seed.to_watchlist_row())
            rows = crypto_market_watchlist(db, active_only=False, limit=args.limit)
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "status": "added_current_window",
                        "seed": {
                            "condition_id": seed.condition_id,
                            "slug": seed.slug,
                            "symbol": seed.symbol,
                            "market_type": seed.market_type,
                            "strike_price": seed.strike_price,
                            "comparator": seed.comparator,
                            "resolution_ts": seed.resolution_ts,
                            "reference_price": seed.reference_price,
                            "window_start_ts": seed.window_start_ts,
                            "window_end_ts": seed.window_end_ts,
                            "consensus_sources": list(seed.consensus_sources),
                            "max_deviation_pct": seed.max_deviation_pct,
                        },
                        "watchlist": rows,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
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
                        "market_type": market.get("market_type", "up_down"),
                        "strike_price": market.get("strike_price"),
                        "comparator": market.get("comparator"),
                        "resolution_ts": market.get("resolution_ts"),
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
        elif args.watchlist_action == "rotate-strikes":
            payload, code = _rotate_strikes_for_watchlist(
                db,
                settings,
                symbol=args.symbol,
                event_slug=args.event_slug,
                max_markets=args.max_markets,
                min_score=args.min_score,
                duration_seconds=args.duration_seconds,
                clear_existing=args.clear_existing,
            )
            print(json.dumps(payload, indent=2, sort_keys=True))
            return code
        elif args.watchlist_action == "wait-for-strike":
            from hermes_polymarket.crypto.l2_preflight import run_l2_preflight

            attempts: list[dict[str, Any]] = []
            for attempt in range(1, args.max_attempts + 1):
                payload, _code = _rotate_strikes_for_watchlist(
                    db,
                    settings,
                    symbol=args.symbol,
                    event_slug=args.event_slug,
                    max_markets=args.max_markets,
                    min_score=args.min_score,
                    duration_seconds=args.duration_seconds,
                    clear_existing=True,
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": payload.get("status"),
                        "imported": payload.get("imported", 0),
                        "selected": payload.get("selected", []),
                        "rejected": payload.get("rejected", [])[:5],
                    }
                )
                if int(payload.get("imported") or 0) > 0:
                    preflight: dict[str, Any] | None = None
                    preflight_usable = None
                    if args.run_preflight:
                        preflight = asyncio.run(
                            run_l2_preflight(
                                db=db,
                                settings=settings,
                                symbol=args.symbol,
                                seconds=args.preflight_seconds,
                                require_rest_book=False,
                                require_ws_book=False,
                                require_bbo=False,
                            )
                        )
                        markets = preflight.get("markets", []) if isinstance(preflight, dict) else []
                        preflight_usable = bool(markets) and all(market.get("recommended_action") == "usable" for market in markets)
                    smoke: dict[str, Any] | None = None
                    smoke_run_id = None
                    if args.run_smoke:
                        if args.run_preflight and not preflight_usable:
                            smoke = {"status": "skipped", "reason": "preflight_not_usable"}
                        else:
                            env = dict(os.environ)
                            env["HERMES_DATABASE_PATH"] = str(settings.database_path)
                            command = [
                                sys.executable,
                                "-m",
                                "hermes_polymarket.cli",
                                "crypto-paper",
                                "watch-v2",
                                "--seconds",
                                str(args.smoke_seconds),
                                "--symbols",
                                args.symbol,
                                "--from-watchlist",
                                "--close-open-on-end",
                            ]
                            if args.write_artifacts:
                                command.append("--write-artifacts")
                            completed = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
                            smoke = {
                                "status": "completed" if completed.returncode == 0 else "failed",
                                "returncode": completed.returncode,
                            }
                            with contextlib.suppress(json.JSONDecodeError):
                                parsed = json.loads(completed.stdout)
                                smoke["output"] = parsed
                                smoke_run_id = (parsed.get("summary") or {}).get("run_id")
                            if completed.returncode != 0:
                                smoke["stderr"] = completed.stderr[-2000:]
                    print(
                        json.dumps(
                            {
                                "mode": "measurement_paper_only",
                                "status": "found",
                                "attempts": attempt,
                                "imported": payload.get("imported", 0),
                                "selected": payload.get("selected", []),
                                "preflight": preflight,
                                "preflight_usable": preflight_usable,
                                "smoke": smoke,
                                "smoke_run_id": smoke_run_id,
                                "attempt_log": attempts,
                            },
                            indent=2,
                            sort_keys=True,
                        )
                    )
                    return 0
                if attempt < args.max_attempts and args.poll_seconds > 0:
                    time.sleep(args.poll_seconds)
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "status": "not_found",
                        "attempts": args.max_attempts,
                        "message": "No healthy strike candidates met min_score.",
                        "attempt_log": attempts,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 2
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
        elif args.watchlist_action == "set-reference":
            updated = set_crypto_market_reference(
                db,
                condition_id=args.condition_id,
                reference_price=args.reference_price,
                window_start_ts=args.window_start_ts,
                window_end_ts=args.window_end_ts,
            )
            print(
                json.dumps(
                    {
                        "mode": "measurement_paper_only",
                        "status": "reference_updated",
                        "condition_id": args.condition_id,
                        "updated": updated,
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
        elif args.watchlist_action == "l2-preflight":
            from hermes_polymarket.crypto.l2_preflight import run_l2_preflight

            report = asyncio.run(
                run_l2_preflight(
                    db=db,
                    settings=settings,
                    symbol=args.symbol,
                    condition_id=args.condition_id,
                    seconds=args.seconds,
                    require_rest_book=args.require_rest_book,
                    require_ws_book=args.require_ws_book,
                    require_bbo=args.require_bbo,
                )
            )
            artifacts: dict[str, str] = {}
            if args.write_artifacts:
                artifact_dir = Path(args.artifact_dir)
                artifact_dir.mkdir(parents=True, exist_ok=True)
                path = artifact_dir / f"l2_preflight_{now_ms()}.json"
                path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
                artifacts["report"] = str(path)
            print(json.dumps({**report, "artifacts": artifacts}, indent=2, sort_keys=True))
        elif args.watchlist_action == "score":
            from hermes_polymarket.crypto.market_score import score_watchlist_markets

            print(json.dumps(score_watchlist_markets(db, symbol=args.symbol, limit=args.limit), indent=2, sort_keys=True))
        elif args.watchlist_action == "best":
            from hermes_polymarket.crypto.market_score import best_watchlist_markets

            print(json.dumps(best_watchlist_markets(db, symbol=args.symbol, limit=args.limit), indent=2, sort_keys=True))
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


def cmd_multi_strike(args: argparse.Namespace) -> int:
    if args.multi_strike_command == "paper-watch":
        from hermes_polymarket.crypto.multi_strike_paper import MultiStrikePaperConfig, run_multi_strike_paper_watch

        settings = _settings()
        db = Database(settings.database_path)
        db.init_schema(settings.initial_bankroll)
        try:
            config = MultiStrikePaperConfig(
                event_slug=args.event_slug,
                symbol=args.symbol,
                amount_usd=args.amount,
                edge_threshold=args.edge_threshold,
                exit_edge_threshold=args.exit_edge_threshold,
                seconds=args.seconds,
                mark_interval_seconds=args.mark_interval_seconds,
                annualized_vol=args.annualized_vol,
                min_ask=args.min_ask,
                max_ask=args.max_ask,
                take_profit_cents=args.take_profit_cents,
                stop_loss_cents=args.stop_loss_cents,
                timeout_seconds=args.timeout_seconds,
                close_open_on_end=args.close_open_on_end,
                max_positions=1,
            )
            payload = run_multi_strike_paper_watch(db=db, settings=settings, config=config)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0 if payload.get("status") in {"completed", "no_candidate_opened"} else 2
        finally:
            db.close()

    if args.multi_strike_command == "report":
        from hermes_polymarket.storage.forward_positions import forward_run_report

        settings = _settings()
        db = Database(settings.database_path)
        db.init_schema(settings.initial_bankroll)
        try:
            print(json.dumps(forward_run_report(db, run_id=args.run_id, include_fixture=False), indent=2, sort_keys=True))
            return 0
        finally:
            db.close()

    if args.multi_strike_command == "promote":
        from hermes_polymarket.crypto.market_quality import evaluate_market_quality
        from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus

        sweep_path = Path(args.sweep_json)
        sweep = json.loads(sweep_path.read_text())
        rows = sweep.get("rows") if isinstance(sweep, dict) else []
        if not isinstance(rows, list):
            print(json.dumps({"status": "invalid_sweep", "file": str(sweep_path)}, indent=2, sort_keys=True))
            return 2
        candidate_rows = [
            row
            for row in rows
            if isinstance(row, dict)
            and bool(row.get("passes_promotion_gate"))
            and float(row.get("cost_cents") or 0.0) >= args.min_cost_cents
            and float(row.get("cost_cents") or 0.0) <= args.max_cost_cents
            and int(row.get("simulated_trades") or 0) >= args.min_trades
            and float(row.get("net_pnl") or 0.0) >= args.min_net_pnl
        ]
        seen_slugs: set[str] = set()
        candidate_rows = [
            row for row in candidate_rows if not (str(row.get("market_slug") or "") in seen_slugs or seen_slugs.add(str(row.get("market_slug") or "")))
        ][: args.limit]
        symbols = sorted({str(row.get("symbol") or args.symbol) for row in candidate_rows if row.get("symbol") or args.symbol})
        references: dict[str, tuple[float, tuple[str, ...], float]] = {}
        for symbol in symbols:
            references[symbol] = current_reference_consensus(symbol)

        gamma = GammaClient()
        clob = ClobV2Client(_settings())
        now = datetime.now(timezone.utc)
        promoted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        try:
            for row in candidate_rows:
                slug = str(row.get("market_slug") or "")
                symbol = str(row.get("symbol") or args.symbol)
                current_price, sources, max_dev = references[symbol]
                markets = gamma.markets_by_slug(slug)
                if not markets:
                    rejected.append({"market_slug": slug, "reason": "market_not_found"})
                    continue
                market = markets[0]
                event_slug = _market_event_slug(market) or slug
                tokens = json.loads(market.get("clobTokenIds") or "[]") if isinstance(market.get("clobTokenIds"), str) else market.get("clobTokenIds") or []
                yes_token = str(tokens[0]) if tokens else ""
                target = parse_multi_strike_target(f"{market.get('question') or ''} {market.get('slug') or ''}", current_price=current_price)
                target_price = row.get("target_price") or (target.target_price if target is not None else None)
                if not yes_token or target_price is None:
                    rejected.append({"market_slug": slug, "reason": "missing_token_or_target"})
                    continue
                seconds_to_expiry = 1.0
                if market.get("endDate"):
                    with contextlib.suppress(ValueError):
                        parsed = datetime.fromisoformat(str(market["endDate"]).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        seconds_to_expiry = max(1.0, (parsed - now).total_seconds())
                try:
                    book = clob.get_orderbook(yes_token)
                    quality = evaluate_market_quality(book).to_dict()
                except Exception as exc:  # noqa: BLE001 - promotion report should explain candidate failure.
                    rejected.append({"market_slug": slug, "reason": "book_error", "error": str(exc)})
                    continue
                fv = fair_value_target_hit(
                    current_price=current_price,
                    target_price=float(target_price),
                    seconds_to_expiry=seconds_to_expiry,
                    annualized_vol=args.annualized_vol,
                )
                best_ask = book.best_ask
                current_edge = fv.probability_yes - best_ask if best_ask is not None else None
                reasons: list[str] = []
                if not quality.get("allowed"):
                    reasons.append(f"quality:{quality.get('reason') or 'rejected'}")
                if current_edge is None:
                    reasons.append("no_best_ask")
                elif current_edge < args.min_current_edge:
                    reasons.append("current_edge_below_min")
                if best_ask is not None and (best_ask < args.min_ask or best_ask > args.max_ask):
                    reasons.append("ask_outside_bounds")
                out = {
                    "market_slug": slug,
                    "symbol": symbol,
                    "condition_id": market.get("conditionId") or market.get("condition_id"),
                    "event_slug": event_slug,
                    "yes_token_id": yes_token,
                    "target_price": float(target_price),
                    "historical": {
                        "net_pnl": row.get("net_pnl"),
                        "simulated_trades": row.get("simulated_trades"),
                        "cost_cents": row.get("cost_cents"),
                        "edge_threshold": row.get("edge_threshold"),
                        "hold_seconds": row.get("hold_seconds"),
                        "avg_evaluated_vol": row.get("avg_evaluated_vol"),
                    },
                    "current": {
                        "current_price": current_price,
                        "consensus_sources": list(sources),
                        "max_deviation_pct": max_dev,
                        "annualized_vol": args.annualized_vol,
                        "probability_yes": fv.probability_yes,
                        "best_bid": book.best_bid,
                        "best_ask": best_ask,
                        "edge": current_edge,
                        "quality": quality,
                    },
                    "paper_command": (
                        f".venv/bin/python -m hermes_polymarket.cli multi-strike paper-watch "
                        f"--event-slug {event_slug} "
                        f"--symbol {symbol} --amount {args.amount} --edge-threshold {args.min_current_edge} "
                        f"--seconds {args.paper_seconds} --mark-interval-seconds 300 --close-open-on-end"
                    ),
                }
                if reasons:
                    rejected.append({**out, "reasons": reasons})
                else:
                    promoted.append(out)
            payload = {
                "mode": "multi_strike_promote_candidates",
                "data_quality": "historical_spot_fair_value_plus_current_rest_book",
                "sweep_json": str(sweep_path),
                "gates": {
                    "min_cost_cents": args.min_cost_cents,
                    "max_cost_cents": args.max_cost_cents,
                    "min_trades": args.min_trades,
                    "min_net_pnl": args.min_net_pnl,
                    "min_current_edge": args.min_current_edge,
                    "min_ask": args.min_ask,
                    "max_ask": args.max_ask,
                },
                "promoted": promoted,
                "rejected": rejected,
                "recommendation": "run_forward_paper_only_for_promoted_candidates",
            }
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                payload["output"] = str(path)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        finally:
            gamma.close()
            clob.close()

    if args.multi_strike_command == "calibrate":
        from hermes_polymarket.crypto.market_quality import evaluate_market_quality
        from hermes_polymarket.crypto.market_universe import filter_universe_candidates, scan_market_universe
        from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus

        vols = [float(value) for value in args.vol_grid.split(",") if value.strip()]
        edges = [float(value) for value in args.edge_grid.split(",") if value.strip()]
        gamma = GammaClient()
        settings = _settings()
        clob = ClobV2Client(settings)
        try:
            events = gamma.list_events(slug=args.event_slug, active="true", closed="false", limit=5)
            if not events:
                print(json.dumps({"status": "event_not_found", "event_slug": args.event_slug}, indent=2, sort_keys=True))
                return 2
            current_price, sources, max_dev = current_reference_consensus(args.symbol)
            universe = scan_market_universe(events=[events[0]], markets=[], symbols={args.symbol})
            now = datetime.now(timezone.utc)
            candidates = []
            for row in filter_universe_candidates(universe, market_type="multi_strike_event", min_score=0.0, limit=500):
                if not row.get("active") or row.get("closed") or not row.get("yes_token_id"):
                    continue
                target = parse_multi_strike_target(f"{row.get('question') or ''} {row.get('slug') or ''}", current_price=current_price)
                target_price = row.get("strike_price") or (target.target_price if target is not None else None)
                if target_price is None:
                    continue
                seconds_to_expiry = 1.0
                if row.get("end_date"):
                    with contextlib.suppress(ValueError):
                        parsed = datetime.fromisoformat(str(row["end_date"]).replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            parsed = parsed.replace(tzinfo=timezone.utc)
                        seconds_to_expiry = max(1.0, (parsed - now).total_seconds())
                try:
                    book = clob.get_orderbook(str(row["yes_token_id"]))
                    quality = evaluate_market_quality(book).to_dict()
                except Exception as exc:  # noqa: BLE001 - report candidate-level failures.
                    candidates.append({**row, "error": str(exc), "quality": {"allowed": False, "reason": "book_error"}})
                    continue
                for vol in vols:
                    fv = fair_value_target_hit(
                        current_price=current_price,
                        target_price=float(target_price),
                        seconds_to_expiry=seconds_to_expiry,
                        annualized_vol=vol,
                    )
                    ask = book.best_ask
                    edge = fv.probability_yes - ask if ask is not None else None
                    candidates.append(
                        {
                            "slug": row.get("slug"),
                            "condition_id": row.get("condition_id"),
                            "token_id": row.get("yes_token_id"),
                            "target_price": float(target_price),
                            "annualized_vol": vol,
                            "probability_yes": fv.probability_yes,
                            "best_bid": book.best_bid,
                            "best_ask": ask,
                            "edge": edge,
                            "quality": quality,
                            "passes": {
                                str(threshold): bool(quality.get("allowed") and edge is not None and edge >= threshold)
                                for threshold in edges
                            },
                        }
                    )
            summary = {
                str(vol): {
                    str(edge): sum(1 for row in candidates if row.get("annualized_vol") == vol and (row.get("passes") or {}).get(str(edge)))
                    for edge in edges
                }
                for vol in vols
            }
            payload = {
                "mode": "multi_strike_research_only",
                "event_slug": args.event_slug,
                "symbol": args.symbol,
                "current_price": current_price,
                "consensus_sources": list(sources),
                "max_deviation_pct": max_dev,
                "summary": summary,
                "candidates": candidates,
                "recommendation": "paper_watch_only_if_candidate_passes_quality_and_edge_threshold",
            }
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                payload["output"] = str(path)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        finally:
            gamma.close()
            clob.close()

    if args.multi_strike_command == "historical-approx":
        from hermes_polymarket.backtest.multi_strike_historical_approx import replay_yes_trade_path
        from hermes_polymarket.crypto.multi_strike_fair_value import fair_value_target_hit
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.crypto.watchlist_seeding import current_reference_consensus
        from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi

        gamma = GammaClient()
        data_api = PolymarketDataApi()
        try:
            markets = gamma.markets_by_slug(args.market_slug)
            if not markets:
                print(json.dumps({"status": "market_not_found", "market_slug": args.market_slug}, indent=2, sort_keys=True))
                return 2
            market = markets[0]
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
            tokens = json.loads(market.get("clobTokenIds") or "[]") if isinstance(market.get("clobTokenIds"), str) else market.get("clobTokenIds") or []
            yes_token = str(tokens[0]) if tokens else ""
            current_price, sources, max_dev = current_reference_consensus(args.symbol)
            target = parse_multi_strike_target(f"{market.get('question') or ''} {market.get('slug') or ''}", current_price=current_price)
            if target is None:
                print(json.dumps({"status": "target_parse_failed", "market_slug": args.market_slug}, indent=2, sort_keys=True))
                return 2
            seconds_to_expiry = 1.0
            if market.get("endDate"):
                with contextlib.suppress(ValueError):
                    parsed = datetime.fromisoformat(str(market["endDate"]).replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    seconds_to_expiry = max(1.0, (parsed - datetime.now(timezone.utc)).total_seconds())
            fv = fair_value_target_hit(
                current_price=current_price,
                target_price=target.target_price,
                seconds_to_expiry=seconds_to_expiry,
                annualized_vol=args.annualized_vol,
            )
            trades = data_api.get_trades(market=condition_id, limit=args.limit)
            results, summary = replay_yes_trade_path(
                trades,
                token_id=yes_token,
                model_probability=fv.probability_yes,
                edge_threshold=args.edge_threshold,
                amount_usd=args.amount,
                hold_seconds=args.hold_seconds,
            )
            payload = {
                "mode": "multi_strike_historical_approx",
                "data_quality": "historical_approx_current_model",
                "market_slug": args.market_slug,
                "condition_id": condition_id,
                "symbol": args.symbol,
                "current_price": current_price,
                "consensus_sources": list(sources),
                "max_deviation_pct": max_dev,
                "fair_value": fv.to_dict(),
                "summary": summary,
                "trades": [row.to_dict() for row in results],
                "warning": "Uses current model probability over historical trade prints; not executable L2 truth.",
            }
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                payload["output"] = str(path)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        finally:
            gamma.close()
            data_api.close()

    if args.multi_strike_command == "historical-spot":
        from hermes_polymarket.backtest.multi_strike_historical_approx import replay_yes_trade_path_with_spot
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.data_sources.binance_historical import BinanceHistoricalClient
        from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi

        gamma = GammaClient()
        data_api = PolymarketDataApi()
        binance = BinanceHistoricalClient()
        try:
            markets = gamma.markets_by_slug(args.market_slug)
            if not markets:
                print(json.dumps({"status": "market_not_found", "market_slug": args.market_slug}, indent=2, sort_keys=True))
                return 2
            market = markets[0]
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
            tokens = json.loads(market.get("clobTokenIds") or "[]") if isinstance(market.get("clobTokenIds"), str) else market.get("clobTokenIds") or []
            yes_token = str(tokens[0]) if tokens else ""
            end_date = market.get("endDate")
            if not end_date:
                print(json.dumps({"status": "missing_end_date", "market_slug": args.market_slug}, indent=2, sort_keys=True))
                return 2
            parsed_end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if parsed_end.tzinfo is None:
                parsed_end = parsed_end.replace(tzinfo=timezone.utc)
            expiry_ts_ms = int(parsed_end.timestamp() * 1000)

            trades = data_api.get_trades(market=condition_id, limit=args.limit)
            if not trades:
                print(
                    json.dumps(
                        {
                            "mode": "multi_strike_historical_spot",
                            "data_quality": "historical_spot_fair_value",
                            "market_slug": args.market_slug,
                            "condition_id": condition_id,
                            "summary": {"observed_yes_trades": 0, "simulated_trades": 0},
                            "warning": "No Data API trades returned for market.",
                        },
                        indent=2,
                        sort_keys=True,
                    )
                )
                return 0

            min_trade_ts_ms = min(trade.timestamp for trade in trades) * 1000
            max_trade_ts_ms = max(trade.timestamp for trade in trades) * 1000
            candle_start = max(0, min_trade_ts_ms - 60_000)
            candle_end = max_trade_ts_ms + max(args.hold_seconds * 1000, 60_000)
            candles = binance.get_klines_paginated(
                symbol=args.symbol,
                interval=args.interval,
                start_ts_ms=candle_start,
                end_ts_ms=candle_end,
            )
            if not candles:
                print(json.dumps({"status": "no_spot_candles", "symbol": args.symbol, "start_ts_ms": candle_start, "end_ts_ms": candle_end}, indent=2, sort_keys=True))
                return 2

            first_spot = candles[0].close
            target = parse_multi_strike_target(f"{market.get('question') or ''} {market.get('slug') or ''}", current_price=first_spot)
            if target is None:
                print(json.dumps({"status": "target_parse_failed", "market_slug": args.market_slug}, indent=2, sort_keys=True))
                return 2
            results, summary = replay_yes_trade_path_with_spot(
                trades,
                token_id=yes_token,
                spot_prices=[(candle.open_ts_ms, candle.close) for candle in candles],
                target_price=target.target_price,
                expiry_ts_ms=expiry_ts_ms,
                annualized_vol=args.annualized_vol,
                edge_threshold=args.edge_threshold,
                amount_usd=args.amount,
                hold_seconds=args.hold_seconds,
                dynamic_vol_window_seconds=args.vol_window_seconds if args.vol_mode == "realized" else None,
                min_annualized_vol=args.min_annualized_vol,
                max_annualized_vol=args.max_annualized_vol,
            )
            payload = {
                "mode": "multi_strike_historical_spot",
                "data_quality": "historical_spot_fair_value",
                "market_slug": args.market_slug,
                "condition_id": condition_id,
                "symbol": args.symbol,
                "spot_source": "binance_klines",
                "spot_interval": args.interval,
                "target_price": target.target_price,
                "expiry_ts_ms": expiry_ts_ms,
                "annualized_vol": args.annualized_vol,
                "vol_mode": args.vol_mode,
                "vol_window_seconds": args.vol_window_seconds if args.vol_mode == "realized" else None,
                "summary": summary,
                "trades": [row.to_dict() for row in results],
                "warning": "Uses historical Binance candles and Polymarket trade prints; still not executable L2 truth.",
            }
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                payload["output"] = str(path)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        finally:
            gamma.close()
            data_api.close()
            binance.close()

    if args.multi_strike_command == "sweep":
        from hermes_polymarket.backtest.multi_strike_historical_approx import SpotSeries, replay_yes_trade_path_with_spot
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.data_sources.binance_historical import BinanceHistoricalClient
        from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi

        market_slugs = [value.strip() for value in args.market_slugs.split(",") if value.strip()]
        vols = [float(value) for value in args.vol_grid.split(",") if value.strip()] if args.vol_mode == "fixed" else [args.annualized_vol]
        edges = [float(value) for value in args.edge_grid.split(",") if value.strip()]
        holds = [int(value) for value in args.hold_grid.split(",") if value.strip()]
        costs = [float(value) for value in args.cost_cents_grid.split(",") if value.strip()]
        gamma = GammaClient()
        data_api = PolymarketDataApi()
        binance = BinanceHistoricalClient()
        rows: list[dict[str, Any]] = []
        market_reports: list[dict[str, Any]] = []
        try:
            for market_slug in market_slugs:
                markets = gamma.markets_by_slug(market_slug)
                if not markets:
                    market_reports.append({"market_slug": market_slug, "status": "market_not_found"})
                    continue
                market = markets[0]
                condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
                tokens = json.loads(market.get("clobTokenIds") or "[]") if isinstance(market.get("clobTokenIds"), str) else market.get("clobTokenIds") or []
                yes_token = str(tokens[0]) if tokens else ""
                end_date = market.get("endDate")
                if not condition_id or not yes_token or not end_date:
                    market_reports.append({"market_slug": market_slug, "status": "missing_market_fields"})
                    continue
                parsed_end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
                if parsed_end.tzinfo is None:
                    parsed_end = parsed_end.replace(tzinfo=timezone.utc)
                expiry_ts_ms = int(parsed_end.timestamp() * 1000)
                trades = data_api.get_trades(market=condition_id, limit=args.limit)
                if not trades:
                    market_reports.append({"market_slug": market_slug, "status": "no_trades", "condition_id": condition_id})
                    continue
                min_trade_ts_ms = min(trade.timestamp for trade in trades) * 1000
                max_trade_ts_ms = max(trade.timestamp for trade in trades) * 1000
                max_hold_ms = (max(holds) if holds else 0) * 1000
                candles = binance.get_klines_paginated(
                    symbol=args.symbol,
                    interval=args.interval,
                    start_ts_ms=max(0, min_trade_ts_ms - 60_000),
                    end_ts_ms=max_trade_ts_ms + max(max_hold_ms, 60_000),
                )
                if not candles:
                    market_reports.append({"market_slug": market_slug, "status": "no_spot_candles", "condition_id": condition_id})
                    continue
                target = parse_multi_strike_target(f"{market.get('question') or ''} {market.get('slug') or ''}", current_price=candles[0].close)
                if target is None:
                    market_reports.append({"market_slug": market_slug, "status": "target_parse_failed", "condition_id": condition_id})
                    continue
                market_reports.append(
                    {
                        "market_slug": market_slug,
                        "status": "ok",
                        "condition_id": condition_id,
                        "target_price": target.target_price,
                        "observed_trades": len(trades),
                        "spot_points": len(candles),
                    }
                )
                spot_prices = [(candle.open_ts_ms, candle.close) for candle in candles]
                dynamic_vol_by_ts_ms = None
                if args.vol_mode == "realized":
                    spot_series = SpotSeries(spot_prices)
                    dynamic_vol_by_ts_ms = {
                        trade.timestamp * 1000: vol
                        for trade in trades
                        if (
                            vol := spot_series.realized_annualized_vol(
                                trade.timestamp * 1000,
                                window_seconds=args.vol_window_seconds,
                                min_annualized_vol=args.min_annualized_vol,
                                max_annualized_vol=args.max_annualized_vol,
                            )
                        )
                        is not None
                    }
                for vol in vols:
                    for edge in edges:
                        for hold in holds:
                            for cost in costs:
                                results, summary = replay_yes_trade_path_with_spot(
                                    trades,
                                    token_id=yes_token,
                                    spot_prices=spot_prices,
                                    target_price=target.target_price,
                                    expiry_ts_ms=expiry_ts_ms,
                                    annualized_vol=vol,
                                    edge_threshold=edge,
                                    amount_usd=args.amount,
                                    hold_seconds=hold,
                                    cost_cents=cost,
                                    dynamic_vol_window_seconds=args.vol_window_seconds if args.vol_mode == "realized" else None,
                                    min_annualized_vol=args.min_annualized_vol,
                                    max_annualized_vol=args.max_annualized_vol,
                                    dynamic_vol_by_ts_ms=dynamic_vol_by_ts_ms,
                                )
                                row = {
                                    "market_slug": market_slug,
                                    "condition_id": condition_id,
                                    "symbol": args.symbol,
                                    "target_price": target.target_price,
                                    "annualized_vol": vol,
                                    "vol_mode": args.vol_mode,
                                    "vol_window_seconds": args.vol_window_seconds if args.vol_mode == "realized" else None,
                                    "avg_selected_vol": summary.get("avg_annualized_vol"),
                                    "avg_evaluated_vol": summary.get("avg_evaluated_annualized_vol"),
                                    "edge_threshold": edge,
                                    "hold_seconds": hold,
                                    "cost_cents": cost,
                                    "amount_usd": args.amount,
                                    **summary,
                                }
                                row["robust_score"] = float(row["net_pnl"] or 0.0) - float(row["max_drawdown"] or 0.0)
                                row["passes_promotion_gate"] = bool(
                                    int(row["simulated_trades"]) >= args.min_trades
                                    and float(row["net_pnl"] or 0.0) > 0
                                    and float(row["max_drawdown"] or 0.0) <= args.max_drawdown
                                )
                                row["sample_trades"] = [trade.to_dict() for trade in results[: args.sample_trades]]
                                rows.append(row)
            ranked = sorted(
                rows,
                key=lambda row: (
                    bool(row.get("passes_promotion_gate")),
                    float(row.get("robust_score") or 0.0),
                    float(row.get("net_pnl") or 0.0),
                    int(row.get("simulated_trades") or 0),
                ),
                reverse=True,
            )
            payload = {
                "mode": "multi_strike_sweep",
                "data_quality": "historical_spot_fair_value_with_cost_penalty",
                "symbol": args.symbol,
                "market_slugs": market_slugs,
                "grids": {
                    "annualized_vol": vols,
                    "vol_mode": args.vol_mode,
                    "vol_window_seconds": args.vol_window_seconds if args.vol_mode == "realized" else None,
                    "edge_threshold": edges,
                    "hold_seconds": holds,
                    "cost_cents": costs,
                },
                "promotion_gate": {"min_trades": args.min_trades, "max_drawdown": args.max_drawdown},
                "markets": market_reports,
                "rows": ranked,
                "top": ranked[: args.top],
                "warning": "Uses historical Binance candles and Polymarket trade prints with synthetic cost penalties; still not executable L2 truth.",
            }
            if args.output:
                path = Path(args.output)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
                payload["output"] = str(path)
            if args.csv_output:
                csv_path = Path(args.csv_output)
                csv_path.parent.mkdir(parents=True, exist_ok=True)
                fieldnames = [
                    "market_slug",
                    "symbol",
                    "target_price",
                    "annualized_vol",
                    "vol_mode",
                    "vol_window_seconds",
                    "avg_selected_vol",
                    "avg_evaluated_vol",
                    "edge_threshold",
                    "hold_seconds",
                    "cost_cents",
                    "simulated_trades",
                    "net_pnl",
                    "avg_roi",
                    "win_rate",
                    "profit_factor",
                    "max_drawdown",
                    "robust_score",
                    "passes_promotion_gate",
                    "skipped_below_edge",
                    "skipped_no_spot",
                ]
                with csv_path.open("w", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=fieldnames)
                    writer.writeheader()
                    for row in ranked:
                        writer.writerow({field: row.get(field) for field in fieldnames})
                payload["csv_output"] = str(csv_path)
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0
        finally:
            gamma.close()
            data_api.close()
            binance.close()

    if args.multi_strike_command == "sweep-from-cache":
        from hermes_polymarket.backtest.multi_strike_historical_approx import SpotSeries, replay_yes_trade_path_with_spot
        from hermes_polymarket.crypto.multi_strike_market import parse_multi_strike_target
        from hermes_polymarket.research.data_cache import ResearchDataCache

        cache = ResearchDataCache()
        market_slugs = [value.strip() for value in args.market_slugs.split(",") if value.strip()]
        vols = [float(value) for value in args.vol_grid.split(",") if value.strip()] if args.vol_mode == "fixed" else [args.annualized_vol]
        edges = [float(value) for value in args.edge_grid.split(",") if value.strip()]
        holds = [int(value) for value in args.hold_grid.split(",") if value.strip()]
        costs = [float(value) for value in args.cost_cents_grid.split(",") if value.strip()]
        rows: list[dict[str, Any]] = []
        market_reports: list[dict[str, Any]] = []
        for market_slug in market_slugs:
            market = cache.load_gamma_market(slug=market_slug)
            if market is None:
                market_reports.append({"market_slug": market_slug, "status": "missing_gamma_market_cache"})
                continue
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
            tokens = json.loads(market.get("clobTokenIds") or "[]") if isinstance(market.get("clobTokenIds"), str) else market.get("clobTokenIds") or []
            yes_token = str(tokens[0]) if tokens else ""
            end_date = market.get("endDate")
            if not condition_id or not yes_token or not end_date:
                market_reports.append({"market_slug": market_slug, "status": "missing_market_fields"})
                continue
            trades = cache.load_polymarket_trades(condition_id=condition_id)
            if not trades:
                market_reports.append({"market_slug": market_slug, "status": "missing_polymarket_trades_cache", "condition_id": condition_id})
                continue
            min_trade_ts_ms = min(trade.timestamp for trade in trades) * 1000
            max_trade_ts_ms = max(trade.timestamp for trade in trades) * 1000
            candle_start = args.spot_start_ts_ms or max(0, min_trade_ts_ms - 60_000)
            candle_end = args.spot_end_ts_ms or (max_trade_ts_ms + max(max(holds) * 1000 if holds else 0, 60_000))
            candles = cache.find_binance_klines(symbol=args.symbol, interval=args.interval, start_ts_ms=candle_start, end_ts_ms=candle_end)
            if not candles:
                market_reports.append(
                    {
                        "market_slug": market_slug,
                        "status": "missing_binance_klines_cache",
                        "condition_id": condition_id,
                        "start_ts_ms": candle_start,
                        "end_ts_ms": candle_end,
                    }
                )
                continue
            parsed_end = datetime.fromisoformat(str(end_date).replace("Z", "+00:00"))
            if parsed_end.tzinfo is None:
                parsed_end = parsed_end.replace(tzinfo=timezone.utc)
            expiry_ts_ms = int(parsed_end.timestamp() * 1000)
            spot_prices = [(int(candle["open_ts_ms"]), float(candle["close"])) for candle in candles]
            target = parse_multi_strike_target(f"{market.get('question') or ''} {market.get('slug') or ''}", current_price=spot_prices[0][1])
            if target is None:
                market_reports.append({"market_slug": market_slug, "status": "target_parse_failed", "condition_id": condition_id})
                continue
            market_reports.append(
                {
                    "market_slug": market_slug,
                    "status": "ok",
                    "condition_id": condition_id,
                    "target_price": target.target_price,
                    "observed_trades": len(trades),
                    "spot_points": len(spot_prices),
                }
            )
            dynamic_vol_by_ts_ms = None
            if args.vol_mode == "realized":
                spot_series = SpotSeries(spot_prices)
                dynamic_vol_by_ts_ms = {
                    trade.timestamp * 1000: vol
                    for trade in trades
                    if (
                        vol := spot_series.realized_annualized_vol(
                            trade.timestamp * 1000,
                            window_seconds=args.vol_window_seconds,
                            min_annualized_vol=args.min_annualized_vol,
                            max_annualized_vol=args.max_annualized_vol,
                        )
                    )
                    is not None
                }
            for vol in vols:
                for edge in edges:
                    for hold in holds:
                        for cost in costs:
                            results, summary = replay_yes_trade_path_with_spot(
                                trades,
                                token_id=yes_token,
                                spot_prices=spot_prices,
                                target_price=target.target_price,
                                expiry_ts_ms=expiry_ts_ms,
                                annualized_vol=vol,
                                edge_threshold=edge,
                                amount_usd=args.amount,
                                hold_seconds=hold,
                                cost_cents=cost,
                                dynamic_vol_window_seconds=args.vol_window_seconds if args.vol_mode == "realized" else None,
                                min_annualized_vol=args.min_annualized_vol,
                                max_annualized_vol=args.max_annualized_vol,
                                dynamic_vol_by_ts_ms=dynamic_vol_by_ts_ms,
                            )
                            row = {
                                "market_slug": market_slug,
                                "condition_id": condition_id,
                                "symbol": args.symbol,
                                "target_price": target.target_price,
                                "annualized_vol": vol,
                                "vol_mode": args.vol_mode,
                                "vol_window_seconds": args.vol_window_seconds if args.vol_mode == "realized" else None,
                                "avg_selected_vol": summary.get("avg_annualized_vol"),
                                "avg_evaluated_vol": summary.get("avg_evaluated_annualized_vol"),
                                "edge_threshold": edge,
                                "hold_seconds": hold,
                                "cost_cents": cost,
                                "amount_usd": args.amount,
                                **summary,
                            }
                            row["robust_score"] = float(row["net_pnl"] or 0.0) - float(row["max_drawdown"] or 0.0)
                            row["passes_promotion_gate"] = bool(
                                int(row["simulated_trades"]) >= args.min_trades
                                and float(row["net_pnl"] or 0.0) > 0
                                and float(row["profit_factor"] or 0.0) >= args.min_profit_factor
                                and float(row["max_drawdown"] or 0.0) <= args.max_drawdown
                            )
                            row["sample_trades"] = [trade.to_dict() for trade in results[: args.sample_trades]]
                            rows.append(row)
        ranked = sorted(
            rows,
            key=lambda row: (
                bool(row.get("passes_promotion_gate")),
                float(row.get("robust_score") or 0.0),
                float(row.get("profit_factor") or 0.0),
                float(row.get("net_pnl") or 0.0),
                int(row.get("simulated_trades") or 0),
            ),
            reverse=True,
        )
        payload = {
            "mode": "multi_strike_sweep_from_cache",
            "data_quality": "research_cache_public_historical",
            "cache_root": str(cache.root),
            "symbol": args.symbol,
            "market_slugs": market_slugs,
            "grids": {
                "annualized_vol": vols,
                "vol_mode": args.vol_mode,
                "vol_window_seconds": args.vol_window_seconds if args.vol_mode == "realized" else None,
                "edge_threshold": edges,
                "hold_seconds": holds,
                "cost_cents": costs,
            },
            "promotion_gate": {
                "min_trades": args.min_trades,
                "min_profit_factor": args.min_profit_factor,
                "max_drawdown": args.max_drawdown,
            },
            "markets": market_reports,
            "rows": ranked,
            "top": ranked[: args.top],
            "warning": "Research-only replay from cached public trade prints and candles; not executable L2 truth.",
        }
        if args.output:
            path = Path(args.output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
            payload["output"] = str(path)
        if args.csv_output:
            csv_path = Path(args.csv_output)
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            fieldnames = [
                "market_slug",
                "symbol",
                "target_price",
                "annualized_vol",
                "vol_mode",
                "vol_window_seconds",
                "avg_selected_vol",
                "avg_evaluated_vol",
                "edge_threshold",
                "hold_seconds",
                "cost_cents",
                "simulated_trades",
                "net_pnl",
                "avg_roi",
                "win_rate",
                "profit_factor",
                "max_drawdown",
                "robust_score",
                "passes_promotion_gate",
                "skipped_below_edge",
                "skipped_no_spot",
                "skipped_no_vol",
            ]
            with csv_path.open("w", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fieldnames)
                writer.writeheader()
                for row in ranked:
                    writer.writerow({field: row.get(field) for field in fieldnames})
            payload["csv_output"] = str(csv_path)
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0

    print(f"unknown multi-strike command: {args.multi_strike_command}")
    return 2


def _market_event_slug(market: dict[str, Any]) -> str | None:
    for key in ("event_slug", "eventSlug", "eventsSlug"):
        value = market.get(key)
        if value:
            return str(value)
    events = market.get("events")
    if isinstance(events, list) and events:
        first = events[0]
        if isinstance(first, dict) and first.get("slug"):
            return str(first["slug"])
    return None


def cmd_crypto_paper_watch(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.artifacts import write_forward_paper_artifacts
    from hermes_polymarket.forward_paper.quality import forward_paper_quality_warnings
    from hermes_polymarket.crypto.l2_preflight import seed_rest_orderbooks
    from hermes_polymarket.crypto.paper_watcher import PaperWatcherConfig, run_crypto_paper_watcher
    from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
    from hermes_polymarket.data_sources.event_bus import EventBus
    from hermes_polymarket.state.orderbook_state import OrderBookState
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
        config_path = getattr(args, "config", None)
        if config_path:
            import yaml

            loaded = yaml.safe_load(Path(config_path).read_text()) or {}
            if not isinstance(loaded, dict):
                print(f"Config file must be a mapping: {config_path}")
                return 2
            market_selection = loaded.get("market_selection") or {}
            stale_quote = loaded.get("stale_quote") or {}
            fair_value = loaded.get("fair_value") or {}
            paper = loaded.get("paper") or {}
            if "min_market_score" in market_selection:
                args.min_market_score = float(market_selection["min_market_score"])
            if "max_reprice_cents" in stale_quote:
                args.stale_quote_max_reprice_cents = float(stale_quote["max_reprice_cents"])
            if "stale_window_ms" in stale_quote:
                args.stale_quote_window_ms = int(stale_quote["stale_window_ms"])
            if "min_edge" in fair_value:
                args.fair_value_min_edge = float(fair_value["min_edge"])
            if "annualized_vol" in fair_value:
                args.fair_value_annualized_vol = float(fair_value["annualized_vol"])
            if "amount_usd" in paper:
                args.amount = float(paper["amount_usd"])
            if "close_open_on_end" in paper:
                args.close_open_on_end = bool(paper["close_open_on_end"])
        symbols = tuple(symbol.strip().lower() for symbol in args.symbols.split(",") if symbol.strip())
        if not symbols:
            print("crypto-paper watch requires at least one symbol")
            return 2
        if not args.from_watchlist and not args.fixture:
            print("crypto-paper watch requires --from-watchlist so paper fills use known Polymarket token IDs.")
            return 2
        seconds = max(1, min(args.seconds, 900))
        watchlist = crypto_market_watchlist(db, active_only=True, limit=args.max_watchlist_markets) if args.from_watchlist else []
        initial_token_ids = tuple(
            dict.fromkeys(
                token_id
                for row in watchlist
                for token_id in (str(row["yes_token_id"]), str(row["no_token_id"]))
                if token_id
            )
        )
        if args.seed_rest_books and initial_token_ids:
            seed_rest_orderbooks(db=db, settings=settings, token_ids=initial_token_ids)
        if args.best_markets_only and watchlist:
            from hermes_polymarket.crypto.market_score import best_watchlist_markets

            best = best_watchlist_markets(db, limit=args.max_watchlist_markets)
            keep = {row["condition_id"] for row in best["markets"] if row.get("recommended_action") == "keep_market"}
            watchlist = [row for row in watchlist if row["condition_id"] in keep]
        token_ids = watchlist_token_ids(db, active_only=True, limit=args.max_watchlist_markets) if args.from_watchlist else ()
        if args.best_markets_only:
            token_ids = tuple(
                dict.fromkeys(
                    token_id
                    for row in watchlist
                    for token_id in (str(row["yes_token_id"]), str(row["no_token_id"]))
                    if token_id
                )
            )
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
            book_state = OrderBookState()
            rest_seed: dict[str, Any] = {}
            if args.seed_rest_books and token_ids:
                rest_seed = seed_rest_orderbooks(db=db, settings=settings, token_ids=token_ids, book_state=book_state)
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
                        use_stale_quote_gate=args.use_stale_quote_gate,
                        stale_quote_max_reprice_cents=args.stale_quote_max_reprice_cents,
                        stale_quote_window_ms=args.stale_quote_window_ms,
                        use_fair_value=args.use_fair_value,
                        fair_value_min_edge=args.fair_value_min_edge,
                        fair_value_annualized_vol=getattr(args, "fair_value_annualized_vol", 0.60),
                        min_market_score=args.min_market_score if args.best_markets_only else 0.0,
                    ),
                    watchlist=watchlist,
                    book_state=book_state,
                    settings=settings,
                )
            finally:
                for task in tasks:
                    task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await asyncio.gather(*tasks)

            summary_dict = summary.to_dict()
            reconciliation: dict[str, Any] = {}
            if args.close_open_on_end:
                from hermes_polymarket.forward_paper.reconciliation import reconcile_open_positions

                reconciliation = reconcile_open_positions(db, run_id=summary.run_id, policy="mark_to_last_bid")
                summary_dict["positions_closed"] = int(summary_dict.get("positions_closed", 0)) + int(reconciliation["closed"])
                summary_dict["run_end_reconciliation"] = reconciliation
            position_report = forward_position_report(db, run_id=summary.run_id, include_fixture=args.fixture)
            warnings = forward_paper_quality_warnings(
                signals=summary.signals_generated,
                closed_positions=position_report["closed"],
                min_move_pct=args.min_move_pct,
                min_strategy_threshold_pct=args.min_strategy_threshold_pct,
            )
            if args.seconds != seconds:
                warnings.append("duration_capped_by_config")
            for warning in reconciliation.get("warnings", []):
                if warning not in warnings:
                    warnings.append(warning)
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
                    "use_stale_quote_gate": args.use_stale_quote_gate,
                    "use_fair_value": args.use_fair_value,
                    "fair_value_min_edge": args.fair_value_min_edge,
                    "fair_value_annualized_vol": getattr(args, "fair_value_annualized_vol", 0.60),
                    "strategy_version": "stale_fair_value_v2" if args.use_fair_value or args.use_stale_quote_gate or args.best_markets_only else "threshold_only_v1",
                    "min_market_score": args.min_market_score if args.best_markets_only else None,
                    "config_path": config_path,
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
                "rest_book_seed": rest_seed,
                "summary": summary_dict,
                "position_report": position_report,
                "reconciliation": reconciliation,
                "quality": quality,
                "artifacts": artifacts,
                "latency_report": crypto_latency_report(db),
            }

        print(json.dumps(asyncio.run(run()), indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_paper_watch_v2(args: argparse.Namespace) -> int:
    args.best_markets_only = True
    args.use_stale_quote_gate = True
    args.use_fair_value = True
    args.healthy_only = True
    if not hasattr(args, "min_market_score"):
        args.min_market_score = 0.75
    if not hasattr(args, "fair_value_min_edge"):
        args.fair_value_min_edge = 0.03
    if not hasattr(args, "stale_quote_max_reprice_cents"):
        args.stale_quote_max_reprice_cents = 1.0
    if not hasattr(args, "stale_quote_window_ms"):
        args.stale_quote_window_ms = 1500
    return cmd_crypto_paper_watch(args)


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


def cmd_crypto_paper_reconcile_open(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.reconciliation import reconcile_open_positions

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        print(
            json.dumps(
                reconcile_open_positions(db, run_id=args.run_id, policy=args.policy),
                indent=2,
                sort_keys=True,
            )
        )
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


def cmd_crypto_paper_v2_diagnostics(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.v2_diagnostics import v2_diagnostics

    db_path = args.db or _settings().database_path
    result = v2_diagnostics(db_path=db_path, run_id=args.run_id, include_fixture=args.include_fixture)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_crypto_paper_strike_calibration(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.strike_calibration import (
        strike_shadow_calibration,
        write_strike_shadow_calibration,
    )

    result = strike_shadow_calibration(args.db, include_fixture=args.include_fixture)
    if args.output:
        output = write_strike_shadow_calibration(result, args.output)
        result = {**result, "artifact": str(output)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_crypto_paper_loss_attribution(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.loss_attribution import expand_db_globs, loss_attribution, write_loss_attribution

    db_paths = expand_db_globs(args.db_glob)
    result = loss_attribution(db_paths, include_fixture=args.include_fixture)
    if args.output:
        output = write_loss_attribution(result, args.output)
        result = {**result, "artifact": str(output)}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def cmd_crypto_paper_shadow_exits(args: argparse.Namespace) -> int:
    from hermes_polymarket.forward_paper.shadow_exit_replay import expand_db_globs, shadow_exit_grid, write_shadow_exit_grid

    db_paths = expand_db_globs(args.db_glob)
    result = shadow_exit_grid(
        db_paths,
        take_profit_cents=[float(value) for value in args.take_profit_cents.split(",") if value.strip()],
        stop_loss_cents=[float(value) for value in args.stop_loss_cents.split(",") if value.strip()],
        timeout_seconds=[int(value) for value in args.timeout_seconds.split(",") if value.strip()],
        include_fixture=args.include_fixture,
    )
    if args.output:
        output = write_shadow_exit_grid(result, args.output)
        result = {**result, "artifact": str(output)}
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

    environment = sub.add_parser("environment")
    environment_sub = environment.add_subparsers(dest="environment_command", required=True)
    environment_show = environment_sub.add_parser("show")
    environment_show.add_argument("--env", choices=["default", "research", "trading_real"], default=None)
    environment_show.set_defaults(func=cmd_environment_show)

    research = sub.add_parser("research")
    research_sub = research.add_subparsers(dest="research_command", required=True)
    research_hypothesis = research_sub.add_parser("hypothesis")
    research_hypothesis_sub = research_hypothesis.add_subparsers(dest="hypothesis_command", required=True)
    hyp_add = research_hypothesis_sub.add_parser("add")
    hyp_add.add_argument("--id", required=True)
    hyp_add.add_argument("--strategy", required=True)
    hyp_add.add_argument("--market-family", required=True)
    hyp_add.add_argument("--claim", required=True)
    hyp_add.add_argument("--status", default="hypothesis")
    hyp_add.add_argument("--data-quality", required=True)
    hyp_add.add_argument("--evidence-json", default="{}")
    hyp_add.add_argument("--next-action", default="")
    hyp_add.add_argument("--proposed-test-json", default="{}")
    hyp_add.add_argument("--result-json", default="{}")
    hyp_add.set_defaults(func=cmd_research)
    hyp_list = research_hypothesis_sub.add_parser("list")
    hyp_list.add_argument("--status", default=None)
    hyp_list.add_argument("--limit", type=int, default=50)
    hyp_list.set_defaults(func=cmd_research)
    hyp_show = research_hypothesis_sub.add_parser("show")
    hyp_show.add_argument("--id", required=True)
    hyp_show.set_defaults(func=cmd_research)
    hyp_update = research_hypothesis_sub.add_parser("update")
    hyp_update.add_argument("--id", required=True)
    hyp_update.add_argument("--status", default=None)
    hyp_update.add_argument("--evidence-json", default=None)
    hyp_update.add_argument("--next-action", default=None)
    hyp_update.add_argument("--result-json", default=None)
    hyp_update.set_defaults(func=cmd_research)
    research_experiments = research_sub.add_parser("experiments")
    research_experiments_sub = research_experiments.add_subparsers(dest="experiments_command", required=True)
    exp_report = research_experiments_sub.add_parser("report")
    exp_report.add_argument("--limit", type=int, default=20)
    exp_report.set_defaults(func=cmd_research)
    research_data = research_sub.add_parser("data")
    research_data_sub = research_data.add_subparsers(dest="data_command", required=True)
    data_status = research_data_sub.add_parser("status")
    data_status.set_defaults(func=cmd_research)
    data_fetch = research_data_sub.add_parser("fetch")
    data_fetch.add_argument("--kind", required=True, choices=["gamma-universe", "gamma-market", "polymarket-trades", "binance-klines"])
    data_fetch.add_argument("--slug", default="")
    data_fetch.add_argument("--condition-id", default="")
    data_fetch.add_argument("--symbol", default="btcusdt", choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    data_fetch.add_argument("--interval", default="1m")
    data_fetch.add_argument("--start-ts-ms", type=int, default=0)
    data_fetch.add_argument("--end-ts-ms", type=int, default=0)
    data_fetch.add_argument("--limit", type=int, default=1000)
    data_fetch.add_argument("--limit-events", type=int, default=300)
    data_fetch.add_argument("--limit-markets", type=int, default=300)
    data_fetch.add_argument("--page-size", type=int, default=300)
    data_fetch.add_argument("--order", default="volume_24hr")
    data_fetch.add_argument("--label", default="")
    data_fetch.set_defaults(func=cmd_research)

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

    multi_strike = sub.add_parser("multi-strike")
    multi_strike_sub = multi_strike.add_subparsers(dest="multi_strike_command", required=True)
    multi_strike_watch = multi_strike_sub.add_parser("paper-watch")
    multi_strike_watch.add_argument("--event-slug", required=True)
    multi_strike_watch.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_watch.add_argument("--amount", type=float, default=5.0)
    multi_strike_watch.add_argument("--edge-threshold", type=float, default=0.08)
    multi_strike_watch.add_argument("--exit-edge-threshold", type=float, default=0.02)
    multi_strike_watch.add_argument("--seconds", type=int, default=3600)
    multi_strike_watch.add_argument("--mark-interval-seconds", type=int, default=300)
    multi_strike_watch.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_watch.add_argument("--min-ask", type=float, default=0.03)
    multi_strike_watch.add_argument("--max-ask", type=float, default=0.60)
    multi_strike_watch.add_argument("--take-profit-cents", type=float, default=5.0)
    multi_strike_watch.add_argument("--stop-loss-cents", type=float, default=5.0)
    multi_strike_watch.add_argument("--timeout-seconds", type=int, default=3600)
    multi_strike_watch.add_argument("--close-open-on-end", action="store_true")
    multi_strike_watch.set_defaults(func=cmd_multi_strike)
    multi_strike_report = multi_strike_sub.add_parser("report")
    multi_strike_report.add_argument("--run-id", required=True)
    multi_strike_report.set_defaults(func=cmd_multi_strike)
    multi_strike_promote = multi_strike_sub.add_parser("promote")
    multi_strike_promote.add_argument("--sweep-json", required=True)
    multi_strike_promote.add_argument("--symbol", default=None, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_promote.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_promote.add_argument("--min-cost-cents", type=float, default=0.0)
    multi_strike_promote.add_argument("--max-cost-cents", type=float, default=1.0)
    multi_strike_promote.add_argument("--min-trades", type=int, default=5)
    multi_strike_promote.add_argument("--min-net-pnl", type=float, default=0.0)
    multi_strike_promote.add_argument("--min-current-edge", type=float, default=0.02)
    multi_strike_promote.add_argument("--min-ask", type=float, default=0.03)
    multi_strike_promote.add_argument("--max-ask", type=float, default=0.80)
    multi_strike_promote.add_argument("--amount", type=float, default=5.0)
    multi_strike_promote.add_argument("--paper-seconds", type=int, default=900)
    multi_strike_promote.add_argument("--limit", type=int, default=10)
    multi_strike_promote.add_argument("--output", default=None)
    multi_strike_promote.set_defaults(func=cmd_multi_strike)
    multi_strike_calibrate = multi_strike_sub.add_parser("calibrate")
    multi_strike_calibrate.add_argument("--event-slug", required=True)
    multi_strike_calibrate.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_calibrate.add_argument("--vol-grid", default="0.4,0.6,0.8,1.0,1.2")
    multi_strike_calibrate.add_argument("--edge-grid", default="0.03,0.05,0.08,0.10,0.15")
    multi_strike_calibrate.add_argument("--output", default=None)
    multi_strike_calibrate.set_defaults(func=cmd_multi_strike)
    multi_strike_hist = multi_strike_sub.add_parser("historical-approx")
    multi_strike_hist.add_argument("--market-slug", required=True)
    multi_strike_hist.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_hist.add_argument("--amount", type=float, default=5.0)
    multi_strike_hist.add_argument("--edge-threshold", type=float, default=0.08)
    multi_strike_hist.add_argument("--hold-seconds", type=int, default=3600)
    multi_strike_hist.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_hist.add_argument("--limit", type=int, default=500)
    multi_strike_hist.add_argument("--output", default=None)
    multi_strike_hist.set_defaults(func=cmd_multi_strike)
    multi_strike_spot = multi_strike_sub.add_parser("historical-spot")
    multi_strike_spot.add_argument("--market-slug", required=True)
    multi_strike_spot.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_spot.add_argument("--amount", type=float, default=5.0)
    multi_strike_spot.add_argument("--edge-threshold", type=float, default=0.08)
    multi_strike_spot.add_argument("--hold-seconds", type=int, default=3600)
    multi_strike_spot.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_spot.add_argument("--vol-mode", choices=["fixed", "realized"], default="fixed")
    multi_strike_spot.add_argument("--vol-window-seconds", type=int, default=86_400)
    multi_strike_spot.add_argument("--min-annualized-vol", type=float, default=0.20)
    multi_strike_spot.add_argument("--max-annualized-vol", type=float, default=2.00)
    multi_strike_spot.add_argument("--interval", default="1m")
    multi_strike_spot.add_argument("--limit", type=int, default=500)
    multi_strike_spot.add_argument("--output", default=None)
    multi_strike_spot.set_defaults(func=cmd_multi_strike)
    multi_strike_sweep = multi_strike_sub.add_parser("sweep")
    multi_strike_sweep.add_argument("--market-slugs", required=True)
    multi_strike_sweep.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_sweep.add_argument("--amount", type=float, default=5.0)
    multi_strike_sweep.add_argument("--vol-grid", default="0.4,0.6,0.8,1.0")
    multi_strike_sweep.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_sweep.add_argument("--vol-mode", choices=["fixed", "realized"], default="fixed")
    multi_strike_sweep.add_argument("--vol-window-seconds", type=int, default=86_400)
    multi_strike_sweep.add_argument("--min-annualized-vol", type=float, default=0.20)
    multi_strike_sweep.add_argument("--max-annualized-vol", type=float, default=2.00)
    multi_strike_sweep.add_argument("--edge-grid", default="0.03,0.05,0.08,0.12")
    multi_strike_sweep.add_argument("--hold-grid", default="900,3600,14400")
    multi_strike_sweep.add_argument("--cost-cents-grid", default="0,1,2,3")
    multi_strike_sweep.add_argument("--interval", default="1m")
    multi_strike_sweep.add_argument("--limit", type=int, default=500)
    multi_strike_sweep.add_argument("--min-trades", type=int, default=20)
    multi_strike_sweep.add_argument("--max-drawdown", type=float, default=10.0)
    multi_strike_sweep.add_argument("--sample-trades", type=int, default=3)
    multi_strike_sweep.add_argument("--top", type=int, default=20)
    multi_strike_sweep.add_argument("--output", default=None)
    multi_strike_sweep.add_argument("--csv-output", default=None)
    multi_strike_sweep.set_defaults(func=cmd_multi_strike)
    multi_strike_sweep_cache = multi_strike_sub.add_parser("sweep-from-cache")
    multi_strike_sweep_cache.add_argument("--market-slugs", required=True)
    multi_strike_sweep_cache.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    multi_strike_sweep_cache.add_argument("--amount", type=float, default=5.0)
    multi_strike_sweep_cache.add_argument("--vol-grid", default="0.4,0.6,0.8,1.0")
    multi_strike_sweep_cache.add_argument("--annualized-vol", type=float, default=0.80)
    multi_strike_sweep_cache.add_argument("--vol-mode", choices=["fixed", "realized"], default="fixed")
    multi_strike_sweep_cache.add_argument("--vol-window-seconds", type=int, default=86_400)
    multi_strike_sweep_cache.add_argument("--min-annualized-vol", type=float, default=0.20)
    multi_strike_sweep_cache.add_argument("--max-annualized-vol", type=float, default=2.00)
    multi_strike_sweep_cache.add_argument("--edge-grid", default="0.03,0.05,0.08,0.12")
    multi_strike_sweep_cache.add_argument("--hold-grid", default="900,3600,14400")
    multi_strike_sweep_cache.add_argument("--cost-cents-grid", default="0,1,2,3")
    multi_strike_sweep_cache.add_argument("--interval", default="1m")
    multi_strike_sweep_cache.add_argument("--spot-start-ts-ms", type=int, default=0)
    multi_strike_sweep_cache.add_argument("--spot-end-ts-ms", type=int, default=0)
    multi_strike_sweep_cache.add_argument("--min-trades", type=int, default=20)
    multi_strike_sweep_cache.add_argument("--min-profit-factor", type=float, default=1.05)
    multi_strike_sweep_cache.add_argument("--max-drawdown", type=float, default=10.0)
    multi_strike_sweep_cache.add_argument("--sample-trades", type=int, default=3)
    multi_strike_sweep_cache.add_argument("--top", type=int, default=20)
    multi_strike_sweep_cache.add_argument("--output", default=None)
    multi_strike_sweep_cache.add_argument("--csv-output", default=None)
    multi_strike_sweep_cache.set_defaults(func=cmd_multi_strike)

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
    mem_add = memories_sub.add_parser("add")
    mem_add.add_argument("--memory-id", required=True)
    mem_add.add_argument("--memory-type", default="semantic", choices=["episodic", "semantic", "procedural"])
    mem_add.add_argument("--status", default="inactive")
    mem_add.add_argument("--strategy-id", default=None)
    mem_add.add_argument("--wallet", default=None)
    mem_add.add_argument("--market-category", default=None)
    mem_add.add_argument("--content-json", required=True)
    mem_add.add_argument("--evidence-json", required=True)
    mem_add.add_argument("--confidence", type=float, default=0.0)
    mem_add.add_argument("--active-in-paper", action="store_true")
    mem_add.set_defaults(func=cmd_learning_memory_add)
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
    crypto_discover_updown = crypto_sub.add_parser("discover-updown")
    crypto_discover_updown.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    crypto_discover_updown.add_argument("--limit", type=int, default=300)
    crypto_discover_updown.add_argument("--debug", action="store_true")
    crypto_discover_updown.set_defaults(func=cmd_crypto_latency_discover_updown)
    crypto_availability = crypto_sub.add_parser("availability-monitor")
    crypto_availability.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    crypto_availability.add_argument("--market-types", default="up_down,strike")
    crypto_availability.add_argument("--poll-seconds", type=int, default=300)
    crypto_availability.add_argument("--duration-seconds", type=int, default=3600)
    crypto_availability.add_argument("--limit-events", type=int, default=1000)
    crypto_availability.add_argument("--limit-markets", type=int, default=1000)
    crypto_availability.add_argument("--min-score", type=float, default=0.75)
    crypto_availability.add_argument("--output", default="artifacts/availability/latest.json")
    crypto_availability.set_defaults(func=cmd_crypto_latency_availability_monitor)
    crypto_universe = crypto_sub.add_parser("universe")
    universe_sub = crypto_universe.add_subparsers(dest="universe_action", required=True)
    universe_scan = universe_sub.add_parser("scan")
    universe_scan.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    universe_scan.add_argument("--limit-events", type=int, default=1000)
    universe_scan.add_argument("--limit-markets", type=int, default=1000)
    universe_scan.add_argument("--output", default="artifacts/universe/latest.json")
    universe_scan.set_defaults(func=cmd_crypto_latency_universe)
    universe_candidates = universe_sub.add_parser("candidates")
    universe_candidates.add_argument("--file", default="artifacts/universe/latest.json")
    universe_candidates.add_argument("--market-type", choices=["up_down", "above_strike", "below_strike", "multi_strike_event", "unsupported"], default=None)
    universe_candidates.add_argument("--min-score", type=float, default=0.0)
    universe_candidates.add_argument("--limit", type=int, default=20)
    universe_candidates.set_defaults(func=cmd_crypto_latency_universe)
    universe_strike = universe_sub.add_parser("strike-candidates")
    universe_strike.add_argument("--event-slug", required=True)
    universe_strike.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    universe_strike.add_argument("--limit", type=int, default=20)
    universe_strike.add_argument("--score-l2", action="store_true")
    universe_strike.add_argument("--current-price-source", choices=["consensus"], default="consensus")
    universe_strike.add_argument("--auto-pick-nearest", action="store_true")
    universe_strike.set_defaults(func=cmd_crypto_latency_universe)
    universe_strike_events = universe_sub.add_parser("strike-events")
    universe_strike_events.add_argument("--symbols", default="btcusdt,ethusdt,solusdt,xrpusdt")
    universe_strike_events.add_argument("--limit-events", type=int, default=1000)
    universe_strike_events.add_argument("--min-candidates", type=int, default=3)
    universe_strike_events.add_argument("--min-score", type=float, default=0.75)
    universe_strike_events.add_argument("--limit", type=int, default=20)
    universe_strike_events.set_defaults(func=cmd_crypto_latency_universe)
    universe_multi_strike = universe_sub.add_parser("multi-strike-candidates")
    universe_multi_strike.add_argument("--event-slug", required=True)
    universe_multi_strike.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    universe_multi_strike.add_argument("--limit", type=int, default=20)
    universe_multi_strike.add_argument("--min-score", type=float, default=0.75)
    universe_multi_strike.add_argument("--min-distance-pct", type=float, default=2.0)
    universe_multi_strike.add_argument("--max-distance-pct", type=float, default=200.0)
    universe_multi_strike.add_argument("--annualized-vol", type=float, default=0.80)
    universe_multi_strike.add_argument("--score-l2", action="store_true")
    universe_multi_strike.add_argument("--current-price-source", choices=["consensus"], default="consensus")
    universe_multi_strike.set_defaults(func=cmd_crypto_latency_universe)
    universe_import_best = universe_sub.add_parser("import-best")
    universe_import_best.add_argument("--file", default="artifacts/universe/latest.json")
    universe_import_best.add_argument("--market-type", choices=["up_down", "above_strike", "below_strike", "multi_strike_event", "unsupported"], default="up_down")
    universe_import_best.add_argument("--limit", type=int, default=5)
    universe_import_best.add_argument("--min-score", type=float, default=0.75)
    universe_import_best.add_argument("--duration-seconds", type=int, default=900)
    universe_import_best.set_defaults(func=cmd_crypto_latency_universe)
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
    watchlist_add_current = watchlist_sub.add_parser("add-current-window")
    watchlist_add_current.add_argument("--slug", required=True)
    watchlist_add_current.add_argument("--symbol", default=None, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    watchlist_add_current.add_argument("--duration-seconds", type=int, default=900)
    watchlist_add_current.add_argument("--yes-direction", choices=["up", "down"], default=None)
    watchlist_add_current.add_argument("--min-sources", type=int, default=2)
    watchlist_add_current.add_argument("--max-deviation-pct", type=float, default=0.25)
    watchlist_clear = watchlist_sub.add_parser("clear")
    watchlist_rotate_strikes = watchlist_sub.add_parser("rotate-strikes")
    watchlist_rotate_strikes.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    watchlist_rotate_strikes.add_argument("--event-slug", required=True)
    watchlist_rotate_strikes.add_argument("--max-markets", type=int, default=2)
    watchlist_rotate_strikes.add_argument("--min-score", type=float, default=0.75)
    watchlist_rotate_strikes.add_argument("--duration-seconds", type=int, default=900)
    watchlist_rotate_strikes.add_argument("--clear-existing", action="store_true")
    watchlist_wait_strike = watchlist_sub.add_parser("wait-for-strike")
    watchlist_wait_strike.add_argument("--symbol", required=True, choices=["btcusdt", "ethusdt", "solusdt", "xrpusdt"])
    watchlist_wait_strike.add_argument("--event-slug", required=True)
    watchlist_wait_strike.add_argument("--max-markets", type=int, default=2)
    watchlist_wait_strike.add_argument("--min-score", type=float, default=0.75)
    watchlist_wait_strike.add_argument("--duration-seconds", type=int, default=900)
    watchlist_wait_strike.add_argument("--poll-seconds", type=int, default=300)
    watchlist_wait_strike.add_argument("--max-attempts", type=int, default=12)
    watchlist_wait_strike.add_argument("--run-preflight", action="store_true")
    watchlist_wait_strike.add_argument("--preflight-seconds", type=int, default=30)
    watchlist_wait_strike.add_argument("--run-smoke", action="store_true")
    watchlist_wait_strike.add_argument("--smoke-seconds", type=int, default=300)
    watchlist_wait_strike.add_argument("--write-artifacts", action="store_true")
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
    watchlist_reference = watchlist_sub.add_parser("set-reference")
    watchlist_reference.add_argument("--condition-id", required=True)
    watchlist_reference.add_argument("--reference-price", type=float, required=True)
    watchlist_reference.add_argument("--window-start-ts", type=int, default=None)
    watchlist_reference.add_argument("--window-end-ts", type=int, default=None)
    watchlist_l2_preflight = watchlist_sub.add_parser("l2-preflight")
    watchlist_l2_preflight.add_argument("--symbol", default=None)
    watchlist_l2_preflight.add_argument("--condition-id", default=None)
    watchlist_l2_preflight.add_argument("--seconds", type=int, default=30)
    watchlist_l2_preflight.add_argument("--require-rest-book", action="store_true")
    watchlist_l2_preflight.add_argument("--require-ws-book", action="store_true")
    watchlist_l2_preflight.add_argument("--require-bbo", action="store_true")
    watchlist_l2_preflight.add_argument("--write-artifacts", action="store_true")
    watchlist_l2_preflight.add_argument("--artifact-dir", default="artifacts/l2_preflight")
    watchlist_score = watchlist_sub.add_parser("score")
    watchlist_score.add_argument("--symbol", default=None)
    watchlist_best = watchlist_sub.add_parser("best")
    watchlist_best.add_argument("--symbol", default=None)
    watchlist_best.add_argument("--limit", type=int, default=5)
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
    crypto_paper_watch.add_argument("--best-markets-only", action="store_true", help="Accepted for campaign-v2 protocol; use watchlist best/score before running.")
    crypto_paper_watch.add_argument("--min-market-score", type=float, default=0.75)
    crypto_paper_watch.add_argument("--use-stale-quote-gate", action="store_true")
    crypto_paper_watch.add_argument("--stale-quote-max-reprice-cents", type=float, default=1.0)
    crypto_paper_watch.add_argument("--stale-quote-window-ms", type=int, default=1500)
    crypto_paper_watch.add_argument("--use-fair-value", action="store_true")
    crypto_paper_watch.add_argument("--fair-value-min-edge", type=float, default=0.03)
    crypto_paper_watch.add_argument("--seed-rest-books", action="store_true")
    crypto_paper_watch.add_argument("--close-open-on-end", action="store_true")
    crypto_paper_watch.add_argument(
        "--healthy-only",
        action="store_true",
        help="Label this forward-paper run as restricted to market-quality-gated opportunities.",
    )
    crypto_paper_watch.set_defaults(func=cmd_crypto_paper_watch)
    crypto_paper_watch_v2 = crypto_paper_sub.add_parser("watch-v2")
    crypto_paper_watch_v2.add_argument("--config", default=None)
    crypto_paper_watch_v2.add_argument("--seconds", type=int, default=900)
    crypto_paper_watch_v2.add_argument("--symbols", default="btcusdt,xrpusdt")
    crypto_paper_watch_v2.add_argument("--from-watchlist", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--max-watchlist-markets", type=int, default=20)
    crypto_paper_watch_v2.add_argument("--amount", type=float, default=5.0)
    crypto_paper_watch_v2.add_argument("--min-move-pct", type=float, default=0.01)
    crypto_paper_watch_v2.add_argument("--max-age-ms", type=int, default=2500)
    crypto_paper_watch_v2.add_argument("--max-deviation-pct", type=float, default=0.25)
    crypto_paper_watch_v2.add_argument("--min-sources", type=int, default=2)
    crypto_paper_watch_v2.add_argument("--cooldown-ms", type=int, default=5000)
    crypto_paper_watch_v2.add_argument("--threshold-grid", default="0.01,0.02,0.03,0.05,0.08")
    crypto_paper_watch_v2.add_argument("--min-strategy-threshold-pct", type=float, default=0.03)
    crypto_paper_watch_v2.add_argument("--write-artifacts", action="store_true")
    crypto_paper_watch_v2.add_argument("--artifact-dir", default="artifacts/campaign_v2")
    crypto_paper_watch_v2.add_argument("--max-event-samples", type=int, default=50)
    crypto_paper_watch_v2.add_argument("--take-profit-cents", type=float, default=8.0)
    crypto_paper_watch_v2.add_argument("--stop-loss-cents", type=float, default=4.0)
    crypto_paper_watch_v2.add_argument("--timeout-seconds", type=int, default=900)
    crypto_paper_watch_v2.add_argument("--disable-rtds", action="store_true")
    crypto_paper_watch_v2.add_argument("--fixture", action="store_true")
    crypto_paper_watch_v2.add_argument("--healthy-only", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--best-markets-only", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--min-market-score", type=float, default=0.75)
    crypto_paper_watch_v2.add_argument("--use-stale-quote-gate", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--stale-quote-max-reprice-cents", type=float, default=1.0)
    crypto_paper_watch_v2.add_argument("--stale-quote-window-ms", type=int, default=1500)
    crypto_paper_watch_v2.add_argument("--use-fair-value", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--fair-value-min-edge", type=float, default=0.03)
    crypto_paper_watch_v2.add_argument("--fair-value-annualized-vol", type=float, default=0.60)
    crypto_paper_watch_v2.add_argument("--seed-rest-books", action="store_true", default=True)
    crypto_paper_watch_v2.add_argument("--close-open-on-end", action="store_true")
    crypto_paper_watch_v2.set_defaults(func=cmd_crypto_paper_watch_v2)
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
    crypto_paper_reconcile = crypto_paper_sub.add_parser("reconcile-open")
    crypto_paper_reconcile.add_argument("--run-id", required=True)
    crypto_paper_reconcile.add_argument("--policy", choices=("mark_to_last_bid", "keep_open"), default="mark_to_last_bid")
    crypto_paper_reconcile.set_defaults(func=cmd_crypto_paper_reconcile_open)
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
    crypto_paper_v2_diagnostics = crypto_paper_sub.add_parser("v2-diagnostics")
    crypto_paper_v2_diagnostics.add_argument("--db", default=None)
    crypto_paper_v2_diagnostics.add_argument("--run-id", default=None)
    crypto_paper_v2_diagnostics.add_argument("--include-fixture", action="store_true")
    crypto_paper_v2_diagnostics.set_defaults(func=cmd_crypto_paper_v2_diagnostics)
    crypto_paper_strike_calibration = crypto_paper_sub.add_parser("strike-calibration")
    crypto_paper_strike_calibration.add_argument("--db", action="append", required=True)
    crypto_paper_strike_calibration.add_argument("--output", default=None)
    crypto_paper_strike_calibration.add_argument("--include-fixture", action="store_true")
    crypto_paper_strike_calibration.set_defaults(func=cmd_crypto_paper_strike_calibration)
    crypto_paper_loss = crypto_paper_sub.add_parser("loss-attribution")
    crypto_paper_loss.add_argument("--db-glob", action="append", required=True)
    crypto_paper_loss.add_argument("--output", default="artifacts/evidence/loss_attribution.json")
    crypto_paper_loss.add_argument("--include-fixture", action="store_true")
    crypto_paper_loss.set_defaults(func=cmd_crypto_paper_loss_attribution)
    crypto_paper_shadow = crypto_paper_sub.add_parser("shadow-exits")
    crypto_paper_shadow.add_argument("--db-glob", action="append", required=True)
    crypto_paper_shadow.add_argument("--output", default="artifacts/evidence/shadow_exits.json")
    crypto_paper_shadow.add_argument("--include-fixture", action="store_true")
    crypto_paper_shadow.add_argument("--take-profit-cents", default="3,5,8,12")
    crypto_paper_shadow.add_argument("--stop-loss-cents", default="2,4,6")
    crypto_paper_shadow.add_argument("--timeout-seconds", default="60,120,300,900")
    crypto_paper_shadow.set_defaults(func=cmd_crypto_paper_shadow_exits)

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
