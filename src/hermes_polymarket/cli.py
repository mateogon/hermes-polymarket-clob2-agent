"""Command line interface for safe local operation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

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
    from hermes_polymarket.data_sources.polymarket_data_api import PolymarketDataApi
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry

    registry = WalletRegistry.load()
    wallet = registry.by_name(args.wallet)
    client = PolymarketDataApi()
    try:
        trades = client.get_trades_for_wallet(wallet.address, limit=args.limit, min_cash=args.min_cash)
        print(json.dumps({"wallet": wallet.name, "address": wallet.address, "trades": [trade.raw for trade in trades]}, indent=2, sort_keys=True))
    finally:
        client.close()
    return 0


def cmd_wallet_flow_replay(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay import replay_wallet_trades
    from hermes_polymarket.backtest.wallet_replay_models import ReplayRunConfig
    from hermes_polymarket.backtest.wallet_replay_storage import insert_replay_run, insert_replay_trade
    from hermes_polymarket.data_sources.wallet_registry import WalletRegistry

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallet = WalletRegistry.load().by_name(args.wallet)
        delays = tuple(int(value) for value in args.delay.split(",") if value.strip())
        config = ReplayRunConfig(wallet=wallet.address, delays_seconds=delays, mode=args.mode.replace("-", "_"), paper_amount_usd=args.amount)
        run_id, results, summary = replay_wallet_trades([], config)
        insert_replay_run(
            db,
            run_id=run_id,
            wallet=wallet.address,
            mode=config.mode,
            data_quality=config.data_quality,
            delays=list(config.delays_seconds),
            config={"wallet_name": wallet.name, "amount": args.amount},
            metrics=summary,
        )
        for result in results:
            insert_replay_trade(db, result.to_storage_dict())
        print(json.dumps({"run_id": run_id, "wallet": wallet.name, "summary": summary}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_score(args: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay_models import ExitModel, ReplayTradeResult
    from hermes_polymarket.backtest.wallet_replay_storage import replay_trades
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
        print(json.dumps({"wallet": wallet.name, "score": score.score, "components": score.components, "sample_size": score.sample_size}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


def cmd_wallet_flow_leaderboard(_: argparse.Namespace) -> int:
    from hermes_polymarket.backtest.wallet_replay_storage import replay_trades

    settings = _settings()
    db = Database(settings.database_path)
    db.init_schema(settings.initial_bankroll)
    try:
        wallets = sorted({row["wallet"] for row in replay_trades(db)})
        print(json.dumps({"wallets": wallets}, indent=2, sort_keys=True))
    finally:
        db.close()
    return 0


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
    fetch.add_argument("--min-cash", type=float, default=None)
    fetch.set_defaults(func=cmd_wallet_flow_fetch)
    replay = wallet_sub.add_parser("replay")
    replay.add_argument("--wallet", required=True)
    replay.add_argument("--delay", default="0,2,5,15,30,120,600")
    replay.add_argument("--mode", default="historical-approx", choices=["historical-approx", "local-l2"])
    replay.add_argument("--amount", type=float, default=5.0)
    replay.set_defaults(func=cmd_wallet_flow_replay)
    score = wallet_sub.add_parser("score")
    score.add_argument("--wallet", required=True)
    score.set_defaults(func=cmd_wallet_flow_score)
    leaderboard = wallet_sub.add_parser("leaderboard")
    leaderboard.set_defaults(func=cmd_wallet_flow_leaderboard)
    report = wallet_sub.add_parser("report")
    report.add_argument("--wallet", default=None)
    report.set_defaults(func=cmd_wallet_flow_report)

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
