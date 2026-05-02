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
    report = wallet_sub.add_parser("report")
    report.add_argument("--wallet", default=None)
    report.set_defaults(func=cmd_wallet_flow_report)

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
