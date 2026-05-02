from hermes_polymarket.config import load_settings
from hermes_polymarket.data_sources.base import DataEvent, EventType
from hermes_polymarket.execution.order_validator import OrderValidator
from hermes_polymarket.execution.paper_engine import PaperEngine
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo, TradeProposal
from hermes_polymarket.risk.risk_manager import RiskManager
from hermes_polymarket.storage.db import Database


def test_paper_engine_persists_trade_and_position(tmp_path):
    settings = load_settings()
    db = Database(tmp_path / "paper.sqlite3")
    db.init_schema(1000)
    token = TokenInfo("t", "yes")
    metadata = MarketMetadata("c", 0.01, 1.0, (token,), FeeDetails())
    book = OrderBook("t", bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))
    proposal = TradeProposal("m", "c", "t", "yes", "buy", 5.0, 0.7, 0.5, "test paper")
    engine = PaperEngine(db, OrderValidator(RiskManager(settings)))
    result = engine.buy(proposal, metadata, book, bankroll=1000)
    assert result.accepted is True
    assert len(db.trades()) == 1
    assert len(db.open_positions()) == 1
    db.close()


def test_database_persists_normalized_data_events(tmp_path):
    db = Database(tmp_path / "paper.sqlite3")
    db.init_schema(1000)
    event = DataEvent(
        source="binance",
        event_type=EventType.BINANCE_BOOK_TICKER,
        event_ts_ms=1000,
        received_ts_ms=1250,
        key="btcusdt",
        payload={"best_bid": 100.0, "best_ask": 101.0},
    )
    event_id = db.insert_data_event(event)
    rows = db.data_events(source="binance", event_type=EventType.BINANCE_BOOK_TICKER.value)
    assert event_id > 0
    assert len(rows) == 1
    assert rows[0]["latency_ms"] == 250
    assert "best_bid" in rows[0]["payload_json"]
    db.close()
