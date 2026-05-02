from hermes_polymarket.config import load_settings
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

