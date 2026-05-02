import pytest

from hermes_polymarket.polymarket.market_data import MarketData
from hermes_polymarket.polymarket.types import FeeDetails, MarketMetadata, OrderBook, OrderBookLevel, TokenInfo


class FakeGamma:
    def __init__(self, markets):
        self.markets = markets

    def markets_by_slug(self, slug):
        return [m for m in self.markets if m.get("slug") == slug]

    def markets_by_condition_id(self, condition_id):
        return [m for m in self.markets if m.get("conditionId") == condition_id]

    def markets_by_token_id(self, token_id):
        return [m for m in self.markets if token_id in m.get("clobTokenIds", [])]

    def search_markets(self, query, limit=10):
        return self.markets[:limit]


class FakeClob:
    def __init__(self):
        self.metadata = MarketMetadata(
            "0x" + "a" * 64,
            0.01,
            5.0,
            (TokenInfo("11111111111111111111", "Yes"), TokenInfo("22222222222222222222", "No")),
            FeeDetails(),
        )

    def get_clob_market_info(self, condition_id):
        assert condition_id == self.metadata.condition_id
        return self.metadata

    def get_orderbook(self, token_id):
        return OrderBook(token_id, bids=(OrderBookLevel(0.49, 100),), asks=(OrderBookLevel(0.50, 100),))


def _market(**overrides):
    data = {
        "conditionId": "0x" + "a" * 64,
        "slug": "will-test-pass",
        "question": "Will test pass?",
        "active": True,
        "closed": False,
        "clobTokenIds": ["11111111111111111111", "22222222222222222222"],
        "outcomes": ["Yes", "No"],
        "outcomePrices": ["0.50", "0.50"],
    }
    data.update(overrides)
    return data


def test_resolver_resolves_exact_slug_and_orderbook():
    resolved = MarketData(FakeClob(), FakeGamma([_market()])).resolve_orderbook("will-test-pass", outcome="YES")
    assert resolved.market.condition_id == "0x" + "a" * 64
    assert resolved.token.token_id == "11111111111111111111"
    assert resolved.book.best_ask == 0.50


def test_resolver_resolves_token_id_without_outcome():
    resolved = MarketData(FakeClob(), FakeGamma([_market()])).resolve_orderbook("22222222222222222222")
    assert resolved.token.outcome == "No"


def test_resolver_rejects_ambiguous_search():
    gamma = FakeGamma([_market(slug="a"), _market(slug="b")])
    with pytest.raises(LookupError, match="Ambiguous"):
        MarketData(FakeClob(), gamma).resolve_market("test query", identifier_type="search")


def test_resolver_rejects_closed_market():
    gamma = FakeGamma([_market(closed=True)])
    with pytest.raises(ValueError, match="closed"):
        MarketData(FakeClob(), gamma).resolve_market("will-test-pass", identifier_type="slug")
