"""Command line interface for safe local operation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from datetime import datetime, timezone
from typing import Any

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
        )
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


def cmd_crypto_latency_discover(_: argparse.Namespace) -> int:
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        payload = crypto_latency_report(db)
        payload["status"] = "discover_skeleton"
        payload["message"] = "Crypto market discovery is measurement-only; no live trading or order posting is implemented."
        print(json.dumps(payload, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_crypto_latency_record(args: argparse.Namespace) -> int:
    from hermes_polymarket.storage.crypto_latency import crypto_latency_report

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        payload = crypto_latency_report(db)
        payload["status"] = "record_skeleton"
        payload["seconds"] = args.seconds
        payload["message"] = "Safe skeleton only: wire live public WS orchestration in a later local-L2 recorder step."
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
    crypto_discover.set_defaults(func=cmd_crypto_latency_discover)
    crypto_record = crypto_sub.add_parser("record")
    crypto_record.add_argument("--seconds", type=int, default=300)
    crypto_record.set_defaults(func=cmd_crypto_latency_record)
    crypto_report = crypto_sub.add_parser("report")
    crypto_report.set_defaults(func=cmd_crypto_latency_report)
    crypto_opps = crypto_sub.add_parser("opportunities")
    crypto_opps.add_argument("--limit", type=int, default=50)
    crypto_opps.set_defaults(func=cmd_crypto_latency_opportunities)

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
