Sí, pude leerlo. El repo está bastante bien como **base segura**, pero todavía es más un **scaffold + auditoría + paper/dry-run inicial** que un agente operativo.

## Estado actual del repo

Tu README dice que el proyecto está en etapa “Phase 1 audit only”, pero ya veo que Codex avanzó algo más: creó `pyproject.toml`, configs, cliente CLOB V2, simulador de orderbook, risk manager, paper engine, dry-run executor, live executor stub, señales demo y tests. El README mantiene correctamente la decisión central: **no forkear repos externos, construir un proyecto limpio y mantener live trading deshabilitado**. 

La auditoría está bien hecha. Identifica el baseline correcto: CLOB V2, `py-clob-client-v2`, pUSD, host de producción `https://clob.polymarket.com`, fees dinámicas, y rechazo de campos V1 como `feeRateBps`, `nonce` y `taker`. También clasifica bien los repos: `chainstacklabs/polyclaw` como referencia CLOB V2, `agent-next/polymarket-paper-trader` como referencia de paper engine, `PolyWeather` para weather intelligence, y PolyScripts como warning/ignore. 

La arquitectura propuesta también está bien: separa `polymarket`, `execution`, `signals`, `risk`, `storage` y `backtest`, y deja claro que Gamma se usa para discovery/metadata, no para precios ejecutables. 

## Lo que ya está sólido

**1. La seguridad general está bien planteada.**
El prompt guardado prohíbe live trading durante audit/tests/dry-run, prohíbe pedir private keys, obliga a CLOB V2, exige Quarter-Kelly, y bloquea proxy/Cloudflare evasion. 

**2. Dependencias correctas para esta etapa.**
`pyproject.toml` usa Python >=3.11, `py-clob-client-v2`, `httpx`, `pydantic`, `pyyaml`, `rich`, `pandas`, `sqlalchemy`, `rapidfuzz` y `pytest`. 

**3. Config/risk defaults conservadores.**
`risk.yaml` tiene Quarter-Kelly `0.25`, max order `$10`, max market exposure `$25`, max open positions `4`, daily loss `$30`, min edge `3%`, max slippage `2%`, min liquidity `$25`, min hours to expiry `2`, entry bounds `0.03`–`0.97`.  La `risk_policy.md` explica bien por qué no usar full Kelly y cómo se descuenta la probabilidad hacia el precio de mercado. 

**4. El orderbook simulator está bien encaminado.**
Compra caminando asks, venta caminando bids, FOK/FAK, average price, shares, cost, fee placeholder, slippage y estados de rechazo.  Los tests cubren single-level, multi-level, FOK rejection, FAK partial, empty book y sell bid-side. 

**5. Quarter-Kelly está implementado correctamente a nivel básico.**
`adjusted_probability` descuenta hacia mercado y clippea a `[0.05, 0.95]`; `quarter_kelly_size` calcula Kelly con precio ejecutable y aplica `kelly_fraction`.  Los tests validan el discount, edge positivo y no-edge. 

**6. Live está bloqueado.**
`LiveExecutor` solo pasa un gate y luego tira `NotImplementedError`; eso es exactamente lo que queremos en esta etapa. 

## Cosas flojas o que corregiría antes de agregar estrategias

**1. `paper_scan` todavía es placeholder.**
Solo inicializa DB y devuelve cash/open positions/status. No escanea mercados reales ni genera señales todavía. 

**2. `dry_run_order` usa fixtures.**
Aunque acepta `--market`, `--side`, `--amount`, internamente crea un mercado fake con bids/asks fijos. Está bien para testear gates, pero no para validar mercados reales. 

**3. Resolver de mercado demasiado simple.**
`MarketData.resolve_from_gamma(query)` toma el primer resultado de Gamma. Para trading, necesitas resolver por slug/condition ID/token ID, validar `active`, `closed`, `accepting_orders`, `clobTokenIds`, y no aceptar un match ambiguo. 

**4. El sell path tiene una ambigüedad.**
`TradeProposal.amount_usd` se usa como USD, pero `simulate_sell_fill` espera número de shares. En `OrderValidator`, si `side=sell`, pasa `proposal.amount_usd` como shares. Todavía no afecta porque `PaperEngine` solo implementa buy, pero hay que corregirlo antes de soportar sells. 

**5. El risk manager calcula depth total, no depth ejecutable bajo slippage.**
Ahora suma toda la profundidad de asks o bids para `min_orderbook_depth_usd`. Eso puede sobreestimar liquidez si hay órdenes profundas a precios muy malos. Debería calcular “depth within slippage cap” o “depth up to max acceptable price”. 

**6. El cliente privado CLOB V2 está incompleto.**
Está bien que live esté apagado, pero cuando llegue el momento tendrá que crear/derivar API creds, manejar signature type/funder, y validar metadata/tick/neg risk. Ahora `_sdk_client(private=True)` solo crea cliente con key/funder/builder config. 

## Qué podemos agregar del post de `coinman2`

El post de X propone una tesis muy aplicable: no depender de una sola señal, sino construir una stack con capas de brain/orchestration/data/market intelligence/backtest/execution, y presta mucha atención a short-duration crypto, whale/copy-flow, backtesting y data feeds rápidos. 

Mi recomendación: **no agregues “copy trading” directo todavía**. Agrega primero una capa de **real-time data + wallet-flow intelligence + backtesting de copyability**.

## Prioridad 1: agregar un “Real-Time Data Hub”

Tu idea de múltiples fuentes de datos es correcta. El repo necesita una capa que normalice eventos de varias fuentes antes de que las señales decidan algo.

Polymarket tiene tres APIs separadas: Gamma para discovery/market browsing, Data API para posiciones/trades/activity/leaderboards, y CLOB para orderbook/pricing/order management; Gamma y Data API son públicas, mientras CLOB tiene endpoints públicos y trading endpoints autenticados. ([Polymarket Documentation][1])

### Estructura sugerida

```text
src/hermes_polymarket/data_sources/
  __init__.py
  base.py
  event_bus.py
  source_health.py

  polymarket_clob_rest.py
  polymarket_market_ws.py
  polymarket_data_api.py
  polymarket_gamma.py

  binance_stream.py
  crypto_price_state.py

  wallet_flow.py
  wallet_registry.py
```

### Eventos normalizados

```python
MarketBookSnapshot
BestBidAskUpdate
LastTradeUpdate
ExternalCryptoTick
WalletTradeObserved
MarketResolved
SourceHealthUpdate
```

La idea es que las señales no llamen directamente a Binance, Gamma, CLOB, Data API, etc. Las señales leen un `MarketState` normalizado.

## Prioridad 2: Polymarket WebSocket market stream

Ahora tu repo usa REST/smoke. Para estrategias rápidas necesitas WebSocket.

Polymarket documenta un Market WebSocket público en `wss://ws-subscriptions-clob.polymarket.com/ws/market`; se subscribe con `assets_ids` token IDs y `custom_feature_enabled: true` habilita eventos como `best_bid_ask`, `new_market` y `market_resolved`. ([Polymarket Documentation][2]) El overview también confirma los canales `market`, `user`, `sports` y `RTDS`, y que el market channel no requiere auth; user channel sí requiere auth y usa condition IDs. ([Polymarket Documentation][3])

Agregar:

```text
src/hermes_polymarket/data_sources/polymarket_market_ws.py
```

Funciones:

```python
subscribe_assets(token_ids: list[str])
on_book()
on_price_change()
on_last_trade_price()
on_best_bid_ask()
on_market_resolved()
```

Guardar snapshots en SQLite:

```text
orderbook_snapshots
best_bid_ask_updates
last_trade_updates
source_heartbeats
```

## Prioridad 3: Wallet-flow intelligence, no copy-trading ciego

Polymarket Data API tiene endpoint público `/trades`; soporta filtros como `user`, `side`, `market`, `eventId`, `filterType`, `filterAmount`, `limit` y `offset`, y devuelve campos como `proxyWallet`, `side`, `conditionId`, `size`, `price`, `timestamp`, `slug`, `outcome`, `name` y `transactionHash`. ([Polymarket Documentation][4])

Agregar:

```text
src/hermes_polymarket/signals/wallet_flow_signal.py
src/hermes_polymarket/data_sources/polymarket_data_api.py
src/hermes_polymarket/storage/wallet_flow.py
config/wallets.yaml
```

`config/wallets.yaml`:

```yaml
wallets:
  - name: coinman2
    address: "0x55be7aa03ecfbe37aa5460db791205f7ac9ddca3"
    mode: "signal_only"
    min_trade_size_usd: 100
    max_copy_delay_seconds: 20
    max_entry_worse_cents: 2
    categories: ["crypto", "short_duration"]
```

La lógica correcta:

```text
1. Observar trade de wallet.
2. Fetch CLOB orderbook actual.
3. Ver si todavía es copyable.
4. Simular paper entry.
5. Trackear PnL si se hubiese copiado.
6. Scoring por wallet.
7. Solo emitir señal, no live trade.
```

Métricas importantes:

```text
observed_trades
copyable_trades
average_detection_delay
average_worse_entry_price
paper_copy_pnl
max_drawdown
category_pnl
hold_time_distribution
leader_exit_lag
```

Esto convierte “copy big accounts” en algo medible. Si `coinman2` compra a 0.41 y tú lo ves 14 segundos tarde con best ask 0.47, no copias. Si lo ves a 0.42 y hay liquidez, paper-copy.

## Prioridad 4: Binance / crypto real-time feed

Para el ángulo `coinman2`, esto es clave: BTC/ETH/SOL/XRP short-duration markets. Binance Spot WebSocket documenta streams como `btcusdt@aggTrade`, `btcusdt@trade`, `btcusdt@kline_1m`, `btcusdt@bookTicker`, y permite combined streams; los eventos son real-time o cada 1000ms según stream. ([GitHub][5])

Agregar:

```text
src/hermes_polymarket/data_sources/binance_stream.py
src/hermes_polymarket/signals/crypto_latency_gap_signal.py
src/hermes_polymarket/storage/crypto_ticks.py
```

No lo llames “arbitrage” aún. Llámalo:

```text
crypto_latency_gap_signal
```

Inputs:

```text
Binance last price
Binance 1s/1m kline
Polymarket best_bid_ask
Polymarket last_trade_price
time_to_expiry
contract strike/open reference
orderbook depth
spread
```

Output:

```text
model_probability
confidence
data_latency_ms
price_move_since_window_open
polymarket_repricing_lag
reason
```

Pero en v1: **paper only**.

## Prioridad 5: Real dry-run con mercado real

Antes de wallet-flow o Binance, haría que tu dry-run deje de usar fixtures.

Nuevo flujo:

```text
python -m hermes_polymarket.cli dry-run \
  --market-slug will-bitcoin-rise-or-fall... \
  --outcome YES \
  --amount 5
```

Debe:

```text
1. Resolver market slug/conditionId.
2. Obtener CLOB V2 metadata.
3. Obtener token ID correcto.
4. Obtener orderbook real.
5. Simular fill.
6. Pasar risk manager.
7. Imprimir allow/reject.
8. No firmar ni postear.
```

Esto es el puente crítico entre el scaffold actual y cualquier estrategia real.

## Prioridad 6: backtest / replay layer

El post insiste en backtesting, y tiene razón.  Para tu repo, yo agregaría primero **replay simple**, no un framework enorme.

```text
src/hermes_polymarket/backtest/
  replay_wallet_flow.py
  replay_crypto_ticks.py
  metrics.py
```

Métricas:

```text
PnL
max drawdown
Sharpe-like ratio
hit rate
average entry slippage
average exit slippage
copy delay
missed trades
rejected trades by reason
PnL by market category
```

La gran pregunta para copy-trading no es “¿coinman2 gana?”, sino:

```text
¿Yo gano si entro 5s/15s/30s después con 1–3 cents peor fill?
```

## Prompt para Codex: siguiente fase recomendada

Pégale esto a Codex como siguiente instrucción:

```text
Continue from the current repo state.

Goal: implement the next safe data/intelligence layer before any live trading.

Do not implement live order posting.
Do not ask for private keys.
Do not add proxy/IP-rotation logic.
Keep default mode as paper.
All new strategy outputs must be signal-only and must pass the existing risk manager before paper execution.

Phase A: make dry-run use real public market data
1. Add robust market resolver:
   - resolve by slug, condition_id, or token_id
   - use Gamma only for discovery/metadata
   - use CLOB V2 metadata/orderbook for executable prices
   - reject ambiguous matches
   - reject closed/inactive/non-CLOB markets
2. Update dry-run so it no longer uses fixture orderbook by default.
3. Keep a fixture flag for tests only.
4. Add tests for resolver ambiguity, missing token, closed market, and real-orderbook adapter with mocked responses.

Phase B: add real-time market data layer
1. Create `src/hermes_polymarket/data_sources/`.
2. Implement:
   - `base.py`
   - `event_bus.py`
   - `source_health.py`
   - `polymarket_market_ws.py`
   - `polymarket_data_api.py`
   - `binance_stream.py`
3. Polymarket market WebSocket must support:
   - book
   - price_change
   - last_trade_price
   - best_bid_ask
   - market_resolved
4. Binance stream must support:
   - aggTrade
   - trade
   - kline_1s or kline_1m
   - bookTicker
5. Store all incoming events in SQLite with timestamps and source latency.

Phase C: add wallet-flow signal, not copy-trading
1. Add `config/wallets.yaml`.
2. Add `wallet_registry.py`.
3. Add `wallet_flow_signal.py`.
4. Use Polymarket Data API `/trades` to fetch public trades by wallet address.
5. For every observed wallet trade:
   - fetch current CLOB orderbook
   - compare leader entry price vs current executable price
   - reject if current entry is worse by more than configured cents
   - reject if trade is stale
   - reject if market is illiquid or near expiry
   - simulate paper-copy only
6. Add wallet copyability metrics:
   - observed trades
   - copyable trades
   - average detection delay
   - worse-entry slippage
   - paper PnL
   - max drawdown
   - best/worst categories
7. Do not live trade from wallet flow.

Phase D: fix current issues
1. Fix sell validation: sell amount must be shares, not `amount_usd`.
2. Improve `RiskManager` liquidity check:
   - calculate executable depth within max slippage / max acceptable price
   - do not count full book depth at bad prices
3. Add tests for live gate.
4. Add tests that no legacy V1 fields appear in live order code.
5. Add tests that dry-run never signs or posts orders.

Expected output:
- Updated README
- New data source modules
- New wallet-flow docs
- Tests passing
- Example commands:
  - smoke public data
  - real dry-run
  - wallet-flow paper watch
  - wallet-flow report
```

## Mi recomendación final

Tu repo está en una buena dirección. No agregaría “copy-trading live”. Agregaría estas tres cosas en orden:

1. **Real dry-run con mercado real**
2. **Real-time data hub: Polymarket WS + Binance WS + Data API**
3. **Wallet-flow signal engine con paper-copy/backtest**

Eso convierte la idea del post de X en un sistema medible y seguro: múltiples fuentes de datos, señales auditables, copyability real, y todo pasando por Quarter-Kelly + risk manager antes de siquiera pensar en live.

[1]: https://docs.polymarket.com/api-reference "Introduction - Polymarket Documentation"
[2]: https://docs.polymarket.com/market-data/websocket/market-channel "Market Channel - Polymarket Documentation"
[3]: https://docs.polymarket.com/developers/CLOB/websocket/wss-overview "Overview - Polymarket Documentation"
[4]: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets "Get trades for a user or markets - Polymarket Documentation"
[5]: https://github.com/binance/binance-spot-api-docs/blob/master/web-socket-streams.md "binance-spot-api-docs/web-socket-streams.md at master · binance/binance-spot-api-docs · GitHub"

Sí. La forma más útil de llevar esto al repo es crear una **capa de datos en tiempo real** separada de las señales. El post que subiste enfatiza que el edge está en “missing data, missing validation, missing discipline, missing speed”; esa idea encaja perfecto con tu repo: primero construir ojos/telemetría, luego señales, luego paper/backtest, y recién después live. 

## Fuentes gratis o casi gratis que usaría

### 1. Polymarket Market WebSocket — prioridad máxima

Es la fuente más importante para tu agente porque da **orderbook, price changes, last trade price, best bid/ask, new markets y market resolved**. El canal es público, no requiere auth, y se subscribe por token IDs; `custom_feature_enabled: true` activa `best_bid_ask`, `new_market` y `market_resolved`. ([Polymarket Documentation][1])

Uso:

```text
- Saber si el mercado se movió.
- Mantener best bid/ask fresco.
- Detectar stale quotes.
- Medir spread/depth real.
- Alimentar paper engine sin hacer REST polling agresivo.
```

### 2. Polymarket RTDS — muy útil para crypto/equities

Polymarket RTDS tiene un WebSocket público en `wss://ws-live-data.polymarket.com`. Para crypto, puede streamear precios Binance y Chainlink de `btcusdt`, `ethusdt`, `solusdt`, `xrpusdt`; también tiene equity/ETF/forex/commodities vía Pyth, aunque algunas cosas pueden tener condiciones comerciales. Para crypto no requiere auth según la documentación. ([Polymarket Documentation][2])

Esto es excelente porque te da una fuente externa **ya alineada con el ecosistema Polymarket**.

Uso:

```text
- Comparar Polymarket orderbook vs Binance/Chainlink.
- Medir lag.
- Crear crypto_latency_gap_signal.
- Validar si tu Binance local coincide con RTDS.
```

### 3. Polymarket Data API — wallet flow / copyability

El endpoint `/trades` de Data API es público y permite filtrar por `user`, `market`, `eventId`, `side`, `limit`, `offset`, `filterType` y `filterAmount`. La respuesta trae `proxyWallet`, `side`, `conditionId`, `size`, `price`, `timestamp`, `slug`, `outcome`, `transactionHash`, etc. ([Polymarket Documentation][3])

Uso:

```text
- Observar coinman2 u otras wallets.
- Calcular si sus trades eran copyables.
- Paper-copy con retraso real.
- Detectar consenso entre wallets.
```

### 4. Polymarket CLOB REST — snapshots, dry-run, backfill

El endpoint `/book` devuelve orderbook por token ID, con `bids`, `asks`, `min_order_size`, `tick_size`, `neg_risk` y `last_trade_price`. ([Polymarket Documentation][4]) El endpoint `/clob-markets/{condition_id}` devuelve tokens, minimum order size, minimum tick size, base fees, RFQ status y fee details. ([Polymarket Documentation][5]) El endpoint `/prices-history` puede backfillear historia por asset ID con intervalos como `1m`, `1h`, `1d`, `all`, etc. ([Polymarket Documentation][6])

Uso:

```text
- Resolver mercado real para dry-run.
- Backfill cuando el WebSocket se cae.
- Validar metadata antes de paper/live.
- Obtener price history para backtest básico.
```

### 5. Binance Spot WebSocket — mejor fuente externa para crypto short-duration

Binance Spot WebSocket soporta raw streams y combined streams. Los streams se acceden como `/ws/<stream>` o `/stream?streams=...`, símbolos en lowercase, `aggTrade` y `trade` son real-time, `kline_1s` actualiza cada 1000ms, `bookTicker` actualiza best bid/ask en real-time. También hay límites: 5 mensajes entrantes por segundo, máximo 1024 streams por conexión, desconexión esperada a las 24h. ([Binance Developers][7])

Uso:

```text
- BTC/ETH/SOL/XRP price movement.
- 1s candles.
- Best bid/ask del mercado spot.
- Confirmar price shock antes de Polymarket.
```

### 6. Coinbase Advanced Trade WebSocket — buena segunda fuente crypto

Coinbase Advanced Trade tiene endpoint público `wss://advanced-trade-ws.coinbase.com`. Canales públicos: `ticker`, `ticker_batch`, `market_trades`, `level2`, `candles`, `heartbeats`, `status`. Recomiendan subscribirse a `heartbeats` para evitar cierres por inactividad. ([Coinbase Developer Docs][8])

Uso:

```text
- Cross-check con Binance.
- Detectar si un movimiento es exchange-specific.
- Reducir falsos positivos por wick/local liquidity.
```

### 7. Kraken WebSocket — tercera fuente crypto gratis

Kraken WebSocket v2 tiene canal `ticker` para level 1 market data, best bid/offer y trades; también canal `ohlc` para candles. Las updates se generan por trade events. ([Kraken Docs][9])

Uso:

```text
- Tercera fuente para consensus price.
- Validar movimientos de BTC/ETH.
- Evitar depender 100% de Binance.
```

### 8. Open-Meteo — weather markets

Open-Meteo es gratis para non-commercial use, no requiere API key, y ofrece JSON forecasts con modelos globales/regionales. ([Open Meteo][10])

Uso:

```text
- Weather markets.
- Ensemble/high temperature probability.
- Backtesting de forecast vs settlement.
```

### 9. AviationWeather.gov — METAR/TAF gratis

AviationWeather.gov tiene API de METAR/TAF en JSON/GeoJSON/CSV/XML; da datos mundiales, recomienda limitar requests y documenta máximo 100 requests/min. También provee cache files actualizados, por ejemplo METAR cada minuto y TAF cada 10 minutos. ([Aviation Weather Center][11])

Uso:

```text
- Observaciones airport/settlement.
- Última temperatura oficial.
- TAF como confirmación intraday.
```

### 10. GDELT — noticias near-real-time gratis

GDELT 2.0 actualiza Event/GKG/Mentions cada 15 minutos, traduce noticias de muchas lenguas, mide themes/emotions y publica listas CSV/BigQuery. ([blog.gdeltproject.org][12])

Uso:

```text
- News markets.
- Geopolitical/political signal proposals.
- Event detection, no live execution.
```

### 11. SEC EDGAR — filings real-time, sin key

La SEC dice que `data.sec.gov` provee APIs JSON sin auth/API key. Submissions y XBRL se actualizan durante el día en real-time; submissions tienen delay típico menor a un segundo y XBRL bajo un minuto, aunque puede variar en picos. ([SEC][13])

Uso:

```text
- Markets sobre empresas, earnings, filings, approvals.
- 8-K / 10-Q / 10-K event alerts.
```

### 12. FRED — macro gratis con API key

FRED API es gratis pero requiere API key. No es real-time tick-by-tick, pero sirve para macro markets: CPI, unemployment, yields, GDP, releases. ([FRED][14])

Uso:

```text
- Macro markets.
- Calendar/release context.
- Anchoring for LLM/news signals.
```

---

## Arquitectura que le pediría a Codex

Agrega esto:

```text
src/hermes_polymarket/data_sources/
  base.py
  event_bus.py
  source_health.py

  polymarket_market_ws.py
  polymarket_rtds.py
  polymarket_data_api.py
  polymarket_clob_rest.py
  polymarket_gamma.py

  binance_stream.py
  coinbase_stream.py
  kraken_stream.py

  open_meteo.py
  aviation_weather.py
  gdelt.py
  sec_edgar.py
  fred_macro.py

src/hermes_polymarket/state/
  market_state.py
  crypto_state.py
  wallet_state.py

src/hermes_polymarket/signals/
  wallet_flow_signal.py
  crypto_latency_gap_signal.py
  source_consensus.py
```

La idea:

```text
Data sources -> EventBus -> StateStore -> Signals -> RiskManager -> PaperEngine/DryRun
```

No dejes que las señales llamen APIs directamente. Las señales deben leer un estado normalizado.

---

## Snippets para guiar a Codex

### 1. Tipos base: `data_sources/base.py`

```python
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from time import time
from typing import Any


class EventType(str, Enum):
    POLY_BOOK = "poly_book"
    POLY_PRICE_CHANGE = "poly_price_change"
    POLY_BEST_BID_ASK = "poly_best_bid_ask"
    POLY_LAST_TRADE = "poly_last_trade"
    POLY_MARKET_RESOLVED = "poly_market_resolved"

    RTDS_CRYPTO_PRICE = "rtds_crypto_price"
    BINANCE_TRADE = "binance_trade"
    BINANCE_BOOK_TICKER = "binance_book_ticker"
    BINANCE_KLINE = "binance_kline"
    COINBASE_TICKER = "coinbase_ticker"
    KRAKEN_TICKER = "kraken_ticker"

    WALLET_TRADE = "wallet_trade"
    WEATHER_FORECAST = "weather_forecast"
    METAR = "metar"
    TAF = "taf"
    NEWS_EVENT = "news_event"
    SEC_FILING = "sec_filing"
    MACRO_OBSERVATION = "macro_observation"


@dataclass(frozen=True)
class DataEvent:
    source: str
    event_type: EventType
    event_ts_ms: int | None
    received_ts_ms: int
    key: str
    payload: dict[str, Any] = field(default_factory=dict)

    @property
    def latency_ms(self) -> int | None:
        if self.event_ts_ms is None:
            return None
        return self.received_ts_ms - self.event_ts_ms


def now_ms() -> int:
    return int(time() * 1000)
```

### 2. Event bus: `data_sources/event_bus.py`

```python
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from hermes_polymarket.data_sources.base import DataEvent


class EventBus:
    def __init__(self, maxsize: int = 100_000):
        self._queue: asyncio.Queue[DataEvent] = asyncio.Queue(maxsize=maxsize)

    async def publish(self, event: DataEvent) -> None:
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # Fail closed: drop newest and let health metrics report pressure.
            # Alternative: drop oldest with a ring buffer.
            pass

    async def stream(self) -> AsyncIterator[DataEvent]:
        while True:
            yield await self._queue.get()
```

### 3. Polymarket Market WebSocket: `data_sources/polymarket_market_ws.py`

```python
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus

POLY_MARKET_WS = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


_EVENT_MAP = {
    "book": EventType.POLY_BOOK,
    "price_change": EventType.POLY_PRICE_CHANGE,
    "best_bid_ask": EventType.POLY_BEST_BID_ASK,
    "last_trade_price": EventType.POLY_LAST_TRADE,
    "market_resolved": EventType.POLY_MARKET_RESOLVED,
}


def _event_ts(payload: dict) -> int | None:
    ts = payload.get("timestamp")
    if ts is None:
        return None
    try:
        return int(float(ts))
    except (TypeError, ValueError):
        return None


async def run_polymarket_market_ws(
    bus: EventBus,
    asset_ids: Iterable[str],
    reconnect_delay: float = 2.0,
) -> None:
    asset_ids = [str(x) for x in asset_ids if x]
    if not asset_ids:
        raise ValueError("asset_ids cannot be empty")

    sub = {
        "assets_ids": asset_ids,
        "type": "market",
        "custom_feature_enabled": True,
    }

    while True:
        try:
            async with websockets.connect(POLY_MARKET_WS, ping_interval=10, ping_timeout=10) as ws:
                await ws.send(json.dumps(sub))

                async for raw in ws:
                    # Some servers can send arrays/batches.
                    msg = json.loads(raw)
                    messages = msg if isinstance(msg, list) else [msg]

                    for payload in messages:
                        if not isinstance(payload, dict):
                            continue

                        event_type_raw = payload.get("event_type")
                        event_type = _EVENT_MAP.get(event_type_raw)
                        if event_type is None:
                            continue

                        key = str(payload.get("asset_id") or payload.get("market") or "unknown")
                        await bus.publish(
                            DataEvent(
                                source="polymarket_market_ws",
                                event_type=event_type,
                                event_ts_ms=_event_ts(payload),
                                received_ts_ms=now_ms(),
                                key=key,
                                payload=payload,
                            )
                        )
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="polymarket_market_ws",
                    event_type=EventType.POLY_PRICE_CHANGE,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)
```

### 4. Polymarket RTDS crypto prices: `data_sources/polymarket_rtds.py`

```python
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus

RTDS_WS = "wss://ws-live-data.polymarket.com"


async def _keepalive(ws) -> None:
    while True:
        await asyncio.sleep(5)
        await ws.send("PING")


async def run_polymarket_rtds_crypto(
    bus: EventBus,
    symbols: Iterable[str] = ("btcusdt", "ethusdt", "solusdt", "xrpusdt"),
    reconnect_delay: float = 2.0,
) -> None:
    filters = ",".join(s.lower() for s in symbols)
    sub = {
        "action": "subscribe",
        "subscriptions": [
            {
                "topic": "crypto_prices",
                "type": "update",
                "filters": filters,
            }
        ],
    }

    while True:
        try:
            async with websockets.connect(RTDS_WS, ping_interval=None) as ws:
                await ws.send(json.dumps(sub))
                keepalive = asyncio.create_task(_keepalive(ws))
                try:
                    async for raw in ws:
                        if raw == "PONG":
                            continue
                        msg = json.loads(raw)
                        if msg.get("topic") != "crypto_prices":
                            continue
                        payload = msg.get("payload") or {}
                        symbol = str(payload.get("symbol") or "").lower()
                        if not symbol:
                            continue
                        await bus.publish(
                            DataEvent(
                                source="polymarket_rtds",
                                event_type=EventType.RTDS_CRYPTO_PRICE,
                                event_ts_ms=int(payload.get("timestamp") or msg.get("timestamp") or 0),
                                received_ts_ms=now_ms(),
                                key=symbol,
                                payload=payload,
                            )
                        )
                finally:
                    keepalive.cancel()
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="polymarket_rtds",
                    event_type=EventType.RTDS_CRYPTO_PRICE,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)
```

### 5. Binance combined stream: `data_sources/binance_stream.py`

```python
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus


def _binance_url(symbols: Iterable[str]) -> str:
    streams: list[str] = []
    for s in symbols:
        sym = s.lower()
        streams.extend([
            f"{sym}@aggTrade",
            f"{sym}@bookTicker",
            f"{sym}@kline_1s",
        ])
    joined = "/".join(streams)
    return f"wss://stream.binance.com:9443/stream?streams={joined}"


def _normalize(raw_data: dict) -> tuple[EventType | None, str, int | None, dict]:
    event = raw_data.get("e")

    if event == "aggTrade":
        return (
            EventType.BINANCE_TRADE,
            str(raw_data["s"]).lower(),
            int(raw_data.get("T") or raw_data.get("E") or 0),
            {
                "symbol": raw_data["s"],
                "price": float(raw_data["p"]),
                "qty": float(raw_data["q"]),
                "trade_ts": raw_data.get("T"),
                "event_ts": raw_data.get("E"),
                "maker_side": raw_data.get("m"),
            },
        )

    if event == "kline":
        k = raw_data["k"]
        return (
            EventType.BINANCE_KLINE,
            str(k["s"]).lower(),
            int(raw_data.get("E") or 0),
            {
                "symbol": k["s"],
                "interval": k["i"],
                "open": float(k["o"]),
                "high": float(k["h"]),
                "low": float(k["l"]),
                "close": float(k["c"]),
                "volume": float(k["v"]),
                "is_closed": bool(k["x"]),
                "start_ts": k["t"],
                "end_ts": k["T"],
            },
        )

    # bookTicker messages in combined streams do not include "e"
    if {"u", "s", "b", "a"}.issubset(raw_data.keys()):
        return (
            EventType.BINANCE_BOOK_TICKER,
            str(raw_data["s"]).lower(),
            None,
            {
                "symbol": raw_data["s"],
                "best_bid": float(raw_data["b"]),
                "best_bid_qty": float(raw_data["B"]),
                "best_ask": float(raw_data["a"]),
                "best_ask_qty": float(raw_data["A"]),
                "update_id": raw_data["u"],
            },
        )

    return None, "unknown", None, raw_data


async def run_binance_stream(
    bus: EventBus,
    symbols: Iterable[str] = ("btcusdt", "ethusdt", "solusdt", "xrpusdt"),
    reconnect_delay: float = 2.0,
) -> None:
    url = _binance_url(symbols)

    while True:
        try:
            async with websockets.connect(url, ping_interval=None) as ws:
                async for raw in ws:
                    msg = json.loads(raw)
                    data = msg.get("data") or msg
                    event_type, key, event_ts, payload = _normalize(data)
                    if event_type is None:
                        continue
                    await bus.publish(
                        DataEvent(
                            source="binance",
                            event_type=event_type,
                            event_ts_ms=event_ts,
                            received_ts_ms=now_ms(),
                            key=key,
                            payload=payload,
                        )
                    )
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="binance",
                    event_type=EventType.BINANCE_TRADE,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)
```

### 6. Coinbase ticker fallback: `data_sources/coinbase_stream.py`

```python
from __future__ import annotations

import asyncio
import json
from collections.abc import Iterable

import websockets

from hermes_polymarket.data_sources.base import DataEvent, EventType, now_ms
from hermes_polymarket.data_sources.event_bus import EventBus

COINBASE_WS = "wss://advanced-trade-ws.coinbase.com"


async def run_coinbase_ticker(
    bus: EventBus,
    product_ids: Iterable[str] = ("BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD"),
    reconnect_delay: float = 2.0,
) -> None:
    products = list(product_ids)
    messages = [
        {"type": "subscribe", "channel": "heartbeats"},
        {"type": "subscribe", "channel": "ticker", "product_ids": products},
    ]

    while True:
        try:
            async with websockets.connect(COINBASE_WS, ping_interval=20, ping_timeout=20) as ws:
                for msg in messages:
                    await ws.send(json.dumps(msg))

                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("channel") != "ticker":
                        continue
                    for event in msg.get("events", []):
                        for ticker in event.get("tickers", []):
                            product_id = ticker.get("product_id")
                            price = ticker.get("price")
                            if not product_id or price is None:
                                continue
                            await bus.publish(
                                DataEvent(
                                    source="coinbase",
                                    event_type=EventType.COINBASE_TICKER,
                                    event_ts_ms=None,
                                    received_ts_ms=now_ms(),
                                    key=product_id.lower(),
                                    payload={
                                        "product_id": product_id,
                                        "price": float(price),
                                        "raw": ticker,
                                    },
                                )
                            )
        except Exception as exc:
            await bus.publish(
                DataEvent(
                    source="coinbase",
                    event_type=EventType.COINBASE_TICKER,
                    event_ts_ms=None,
                    received_ts_ms=now_ms(),
                    key="connection_error",
                    payload={"error": str(exc)},
                )
            )
            await asyncio.sleep(reconnect_delay)
```

### 7. Polymarket Data API wallet trades: `data_sources/polymarket_data_api.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


DATA_API = "https://data-api.polymarket.com"


@dataclass(frozen=True)
class WalletTrade:
    wallet: str
    side: str
    condition_id: str
    asset_id: str
    outcome: str
    price: float
    size: float
    timestamp: int
    slug: str
    title: str
    tx_hash: str
    raw: dict[str, Any]


class PolymarketDataApi:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        self.client.close()

    def get_trades_for_wallet(
        self,
        wallet: str,
        *,
        limit: int = 100,
        offset: int = 0,
        side: str | None = None,
        min_cash: float | None = None,
    ) -> list[WalletTrade]:
        params: dict[str, Any] = {
            "user": wallet,
            "limit": limit,
            "offset": offset,
            "takerOnly": "true",
        }
        if side:
            params["side"] = side.upper()
        if min_cash is not None:
            params["filterType"] = "CASH"
            params["filterAmount"] = min_cash

        res = self.client.get(f"{DATA_API}/trades", params=params)
        res.raise_for_status()
        rows = res.json()
        out: list[WalletTrade] = []

        for row in rows if isinstance(rows, list) else []:
            try:
                out.append(
                    WalletTrade(
                        wallet=str(row["proxyWallet"]),
                        side=str(row["side"]),
                        condition_id=str(row["conditionId"]),
                        asset_id=str(row["asset"]),
                        outcome=str(row["outcome"]),
                        price=float(row["price"]),
                        size=float(row["size"]),
                        timestamp=int(row["timestamp"]),
                        slug=str(row.get("slug") or ""),
                        title=str(row.get("title") or ""),
                        tx_hash=str(row.get("transactionHash") or ""),
                        raw=row,
                    )
                )
            except (KeyError, TypeError, ValueError):
                continue

        return out
```

### 8. Wallet-flow copyability filter: `signals/wallet_flow_signal.py`

```python
from __future__ import annotations

from dataclasses import dataclass

from hermes_polymarket.data_sources.polymarket_data_api import WalletTrade
from hermes_polymarket.polymarket.orderbook import simulate_buy_fill
from hermes_polymarket.polymarket.types import OrderBook
from hermes_polymarket.signals.base import Signal


@dataclass(frozen=True)
class CopyabilityDecision:
    copyable: bool
    reason: str
    leader_price: float
    our_avg_price: float = 0.0
    worse_by_cents: float = 0.0
    latency_seconds: float | None = None


def evaluate_copyability(
    trade: WalletTrade,
    book: OrderBook,
    *,
    now_ts: int,
    max_delay_seconds: int = 20,
    max_worse_cents: float = 2.0,
    min_trade_cash: float = 100.0,
    paper_amount_usd: float = 5.0,
) -> CopyabilityDecision:
    trade_cash = trade.price * trade.size
    if trade_cash < min_trade_cash:
        return CopyabilityDecision(False, "leader_trade_too_small", trade.price)

    delay = now_ts - trade.timestamp
    if delay > max_delay_seconds:
        return CopyabilityDecision(False, "stale_wallet_trade", trade.price, latency_seconds=delay)

    if trade.side.upper() != "BUY":
        return CopyabilityDecision(False, "only_buy_copy_supported_v1", trade.price, latency_seconds=delay)

    fill = simulate_buy_fill(book, paper_amount_usd, order_type="fok")
    if not fill.filled:
        return CopyabilityDecision(False, f"not_executable:{fill.status}", trade.price, latency_seconds=delay)

    worse = (fill.avg_price - trade.price) * 100.0
    if worse > max_worse_cents:
        return CopyabilityDecision(
            False,
            "entry_too_late_or_too_expensive",
            trade.price,
            fill.avg_price,
            worse,
            delay,
        )

    return CopyabilityDecision(
        True,
        "copyable_for_paper",
        trade.price,
        fill.avg_price,
        worse,
        delay,
    )


def wallet_trade_to_signal(
    trade: WalletTrade,
    decision: CopyabilityDecision,
    *,
    wallet_score: float,
) -> Signal | None:
    if not decision.copyable:
        return None

    # Signal only. Probability is intentionally modest.
    # Wallet flow should boost confidence, not override market/orderbook.
    model_probability = min(0.65, max(0.52, 0.50 + wallet_score * 0.10))
    confidence = min(0.45, max(0.10, 0.15 + wallet_score * 0.20))

    return Signal(
        market_id=trade.condition_id,
        outcome=trade.outcome,
        model_probability=model_probability,
        confidence=confidence,
        reason=(
            f"Wallet-flow signal: {trade.wallet} bought {trade.outcome} "
            f"at {trade.price:.3f}; paper entry {decision.our_avg_price:.3f}; "
            f"worse_by={decision.worse_by_cents:.2f}c; delay={decision.latency_seconds}s"
        ),
        sources=("polymarket_data_api", "wallet_flow"),
    )
```

### 9. Crypto latency gap signal: `signals/crypto_latency_gap_signal.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from math import exp

from hermes_polymarket.signals.base import Signal


@dataclass(frozen=True)
class CryptoMarketContext:
    market_id: str
    outcome_up: str
    binance_price: float
    window_open_price: float
    polymarket_yes_ask: float
    polymarket_no_ask: float
    seconds_to_expiry: float
    spread: float
    source_latency_ms: int


def sigmoid(x: float) -> float:
    return 1.0 / (1.0 + exp(-x))


def make_crypto_latency_gap_signal(ctx: CryptoMarketContext) -> Signal | None:
    if ctx.window_open_price <= 0:
        return None
    if ctx.seconds_to_expiry <= 15:
        return None
    if ctx.spread > 0.04:
        return None
    if ctx.source_latency_ms > 1500:
        return None

    move_pct = (ctx.binance_price - ctx.window_open_price) / ctx.window_open_price

    # Conservative mapping: small moves should not create huge probabilities.
    # Tune by backtest only.
    p_up = sigmoid(move_pct * 350.0)
    p_up = min(0.80, max(0.20, p_up))

    market_up = ctx.polymarket_yes_ask
    market_down = ctx.polymarket_no_ask

    up_edge = p_up - market_up
    down_edge = (1.0 - p_up) - market_down

    if up_edge < 0.03 and down_edge < 0.03:
        return None

    if up_edge >= down_edge:
        return Signal(
            market_id=ctx.market_id,
            outcome="yes",
            model_probability=p_up,
            confidence=0.35,
            reason=(
                f"Crypto latency signal: move={move_pct:.4%}, "
                f"p_up={p_up:.3f}, yes_ask={market_up:.3f}, "
                f"seconds_to_expiry={ctx.seconds_to_expiry:.1f}"
            ),
            sources=("binance", "polymarket_market_ws"),
        )

    return Signal(
        market_id=ctx.market_id,
        outcome="no",
        model_probability=1.0 - p_up,
        confidence=0.35,
        reason=(
            f"Crypto latency signal: move={move_pct:.4%}, "
            f"p_down={1.0 - p_up:.3f}, no_ask={market_down:.3f}, "
            f"seconds_to_expiry={ctx.seconds_to_expiry:.1f}"
        ),
        sources=("binance", "polymarket_market_ws"),
    )
```

### 10. Open-Meteo forecast client: `data_sources/open_meteo.py`

```python
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class DailyForecast:
    date: str
    temp_max: float
    temp_min: float | None = None


class OpenMeteoClient:
    def __init__(self, client: httpx.Client | None = None):
        self.client = client or httpx.Client(timeout=15.0)

    def close(self) -> None:
        self.client.close()

    def daily_temperature(
        self,
        *,
        latitude: float,
        longitude: float,
        timezone: str,
        unit: str = "fahrenheit",
        forecast_days: int = 7,
        model: str | None = None,
    ) -> list[DailyForecast]:
        params = {
            "latitude": latitude,
            "longitude": longitude,
            "daily": "temperature_2m_max,temperature_2m_min",
            "temperature_unit": unit,
            "timezone": timezone,
            "forecast_days": forecast_days,
        }
        if model:
            params["models"] = model

        res = self.client.get("https://api.open-meteo.com/v1/forecast", params=params)
        res.raise_for_status()
        data = res.json()
        daily = data.get("daily") or {}

        out: list[DailyForecast] = []
        for date, hi, lo in zip(
            daily.get("time", []),
            daily.get("temperature_2m_max", []),
            daily.get("temperature_2m_min", []),
        ):
            if hi is None:
                continue
            out.append(DailyForecast(date=str(date), temp_max=float(hi), temp_min=float(lo) if lo is not None else None))
        return out
```

### 11. AviationWeather METAR/TAF client: `data_sources/aviation_weather.py`

```python
from __future__ import annotations

from typing import Any

import httpx

AWC_BASE = "https://aviationweather.gov/api/data"


class AviationWeatherClient:
    def __init__(self, client: httpx.Client | None = None):
        headers = {"User-Agent": "hermes-polymarket-clob2-agent/0.1 contact:local"}
        self.client = client or httpx.Client(timeout=15.0, headers=headers)

    def close(self) -> None:
        self.client.close()

    def metar(self, station_ids: list[str]) -> list[dict[str, Any]]:
        res = self.client.get(
            f"{AWC_BASE}/metar",
            params={"ids": ",".join(station_ids), "format": "json"},
        )
        res.raise_for_status()
        data = res.json()
        return data if isinstance(data, list) else []

    def taf(self, station_ids: list[str]) -> list[dict[str, Any]]:
        res = self.client.get(
            f"{AWC_BASE}/taf",
            params={"ids": ",".join(station_ids), "format": "json"},
        )
        res.raise_for_status()
        data = res.json()
        return data if isinstance(data, list) else []
```

### 12. SEC EDGAR filings monitor: `data_sources/sec_edgar.py`

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class Filing:
    cik: str
    form: str
    filing_date: str
    accession_number: str
    primary_document: str


class SecEdgarClient:
    def __init__(self, client: httpx.Client | None = None):
        headers = {
            "User-Agent": "hermes-polymarket-clob2-agent research@example.local",
        }
        self.client = client or httpx.Client(timeout=20.0, headers=headers)

    def close(self) -> None:
        self.client.close()

    def submissions(self, cik: str) -> dict[str, Any]:
        padded = str(cik).lstrip("CIK").zfill(10)
        res = self.client.get(f"https://data.sec.gov/submissions/CIK{padded}.json")
        res.raise_for_status()
        return res.json()

    def latest_filings(self, cik: str, forms: set[str] | None = None, limit: int = 20) -> list[Filing]:
        data = self.submissions(cik)
        recent = (data.get("filings") or {}).get("recent") or {}
        forms_col = recent.get("form", [])
        dates_col = recent.get("filingDate", [])
        acc_col = recent.get("accessionNumber", [])
        doc_col = recent.get("primaryDocument", [])

        out: list[Filing] = []
        for form, date, acc, doc in zip(forms_col, dates_col, acc_col, doc_col):
            if forms and form not in forms:
                continue
            out.append(Filing(str(cik), str(form), str(date), str(acc), str(doc)))
            if len(out) >= limit:
                break
        return out
```

---

## Esquema SQLite mínimo para data events

Agrégale a `storage/models.py`:

```sql
CREATE TABLE IF NOT EXISTS data_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  event_type TEXT NOT NULL,
  event_ts_ms INTEGER,
  received_ts_ms INTEGER NOT NULL,
  latency_ms INTEGER,
  key TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_data_events_source_key
ON data_events (source, key, received_ts_ms);

CREATE INDEX IF NOT EXISTS idx_data_events_type_key
ON data_events (event_type, key, received_ts_ms);

CREATE TABLE IF NOT EXISTS source_health (
  source TEXT PRIMARY KEY,
  last_seen_ts_ms INTEGER NOT NULL,
  last_latency_ms INTEGER,
  messages_seen INTEGER NOT NULL DEFAULT 0,
  errors_seen INTEGER NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'unknown',
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallet_watchlist (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  wallet TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL DEFAULT 'signal_only',
  min_trade_size_usd REAL NOT NULL DEFAULT 100,
  max_copy_delay_seconds INTEGER NOT NULL DEFAULT 20,
  max_entry_worse_cents REAL NOT NULL DEFAULT 2,
  enabled INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS wallet_flow_observations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  wallet TEXT NOT NULL,
  condition_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  leader_price REAL NOT NULL,
  leader_size REAL NOT NULL,
  leader_trade_ts INTEGER NOT NULL,
  observed_ts_ms INTEGER NOT NULL,
  current_avg_price REAL,
  worse_by_cents REAL,
  copyable INTEGER NOT NULL,
  reject_reason TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

---

## Fuente consensus: reduce falsos positivos

Agrega un módulo `signals/source_consensus.py` para no confiar en un solo feed.

```python
from __future__ import annotations

from dataclasses import dataclass
from statistics import median


@dataclass(frozen=True)
class PriceReading:
    source: str
    symbol: str
    price: float
    received_ts_ms: int
    latency_ms: int | None = None


@dataclass(frozen=True)
class ConsensusPrice:
    symbol: str
    price: float
    sources: tuple[str, ...]
    max_deviation_pct: float
    stale_sources: tuple[str, ...]


def consensus_price(
    readings: list[PriceReading],
    *,
    now_ms: int,
    max_age_ms: int = 2_500,
    max_deviation_pct_allowed: float = 0.25,
) -> ConsensusPrice | None:
    fresh = [r for r in readings if now_ms - r.received_ts_ms <= max_age_ms]
    stale = [r.source for r in readings if now_ms - r.received_ts_ms > max_age_ms]

    if len(fresh) < 2:
        return None

    px = [r.price for r in fresh]
    center = median(px)
    max_dev = max(abs(p - center) / center * 100 for p in px)

    if max_dev > max_deviation_pct_allowed:
        return None

    return ConsensusPrice(
        symbol=fresh[0].symbol,
        price=center,
        sources=tuple(r.source for r in fresh),
        max_deviation_pct=max_dev,
        stale_sources=tuple(stale),
    )
```

Uso:

```text
Para crypto_latency_gap_signal, exige al menos 2 fuentes frescas:
- Binance + Polymarket RTDS
- o Binance + Coinbase
- o Binance + Kraken
```

---

## Comandos nuevos para el agente

```bash
# Stream de datos Polymarket para token IDs
python -m hermes_polymarket.cli data poly-ws --asset-id TOKEN1 --asset-id TOKEN2

# Stream de Binance
python -m hermes_polymarket.cli data binance --symbol btcusdt --symbol ethusdt

# Stream RTDS
python -m hermes_polymarket.cli data rtds --symbol btcusdt --symbol solusdt

# Wallet watch paper-only
python -m hermes_polymarket.cli wallets watch --name coinman2 --mode paper

# Reporte de copyability
python -m hermes_polymarket.cli wallets report --name coinman2

# Crypto latency paper signal
python -m hermes_polymarket.cli signal crypto-latency --market-slug SLUG --mode paper

# Weather data smoke
python -m hermes_polymarket.cli data weather-smoke --city "New York" --station KLGA
```

---

## Prompt compacto para Codex

Pégale esto junto al plan anterior:

```text
Implement a free real-time data layer for the existing hermes-polymarket-clob2-agent repo.

Rules:
- No live trading.
- No private keys.
- No proxy/IP-rotation logic.
- All outputs are paper/signal-only.
- Keep CLOB V2-only policy.
- Do not let signal modules call external APIs directly; they must consume normalized events/state.

Add dependencies:
- websockets>=12
- optionally aiosqlite>=0.20 if you choose async DB writes

Implement:
1. `src/hermes_polymarket/data_sources/base.py`
   - DataEvent
   - EventType
   - now_ms()

2. `src/hermes_polymarket/data_sources/event_bus.py`
   - async queue-based EventBus

3. `src/hermes_polymarket/data_sources/polymarket_market_ws.py`
   - subscribe to Polymarket market WS
   - support book, price_change, best_bid_ask, last_trade_price, market_resolved
   - publish normalized DataEvents

4. `src/hermes_polymarket/data_sources/polymarket_rtds.py`
   - subscribe to RTDS crypto_prices for btcusdt, ethusdt, solusdt, xrpusdt
   - publish normalized price events
   - send PING every 5 seconds

5. `src/hermes_polymarket/data_sources/binance_stream.py`
   - combined stream for aggTrade, bookTicker, kline_1s
   - publish normalized trade/book/kline events

6. Optional fallback sources:
   - `coinbase_stream.py` ticker + heartbeats
   - `kraken_stream.py` ticker

7. `src/hermes_polymarket/data_sources/polymarket_data_api.py`
   - fetch `/trades` by wallet
   - return typed WalletTrade objects

8. `src/hermes_polymarket/signals/wallet_flow_signal.py`
   - evaluate copyability
   - reject stale trades
   - reject worse entry > max cents
   - reject non-executable orderbook
   - produce Signal only, not trade

9. `src/hermes_polymarket/signals/crypto_latency_gap_signal.py`
   - consume Binance/RTDS/CLOB state
   - produce conservative Signal only
   - require source freshness and max spread

10. `src/hermes_polymarket/signals/source_consensus.py`
   - compute consensus price from multiple sources
   - reject if feeds disagree too much or are stale

11. Weather/free data:
   - `open_meteo.py`
   - `aviation_weather.py`

12. SQLite schema:
   - data_events
   - source_health
   - wallet_watchlist
   - wallet_flow_observations

13. CLI:
   - `data poly-ws`
   - `data rtds`
   - `data binance`
   - `wallets watch`
   - `wallets report`
   - `signal crypto-latency`

14. Tests:
   - parse Polymarket WS book event
   - parse best_bid_ask event
   - parse Binance aggTrade/bookTicker/kline
   - source consensus rejects stale/divergent sources
   - wallet flow rejects stale/worse-entry trades
   - wallet flow creates signal only when copyable
   - data modules never import live executor
   - no private key required

Do not implement live order posting.
```

---

## Mi orden recomendado

1. **Polymarket real dry-run con orderbook real**
2. **Polymarket Market WS + CLOB REST snapshots**
3. **Binance + RTDS crypto feeds**
4. **source consensus / source health**
5. **wallet-flow paper-copy**
6. **crypto latency gap paper signal**
7. **weather/METAR modules**
8. **backtest/replay**

Con eso, tu agente deja de ser “un bot que adivina” y pasa a ser una **máquina de observación + validación + paper execution**, que es exactamente lo que necesitas antes de live.

[1]: https://docs.polymarket.com/market-data/websocket/market-channel?utm_source=chatgpt.com "Market Channel - Polymarket Documentation"
[2]: https://docs.polymarket.com/market-data/websocket/rtds?utm_source=chatgpt.com "Real-Time Data Socket - Polymarket Documentation"
[3]: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets "Get trades for a user or markets - Polymarket Documentation"
[4]: https://docs.polymarket.com/api-reference/market-data/get-order-book "Get order book - Polymarket Documentation"
[5]: https://docs.polymarket.com/api-reference/markets/get-clob-market-info "Get CLOB market info - Polymarket Documentation"
[6]: https://docs.polymarket.com/api-reference/markets/get-prices-history "Get prices history - Polymarket Documentation"
[7]: https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams "WebSocket Streams | Binance Open Platform"
[8]: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels?utm_source=chatgpt.com "Advanced Trade WebSocket Channels - Coinbase Developer Documentation"
[9]: https://docs.kraken.com/api/docs/websocket-v2/ticker?utm_source=chatgpt.com "Ticker (Level 1) | Kraken API Center"
[10]: https://open-meteo.com/?utm_source=chatgpt.com "🌤️ Free Open-Source Weather API | Open-Meteo.com"
[11]: https://www.connect.aviationweather.gov/data/api/?utm_source=chatgpt.com "Data API"
[12]: https://blog.gdeltproject.org/gdelt-2-0-our-global-world-in-realtime/ "GDELT 2.0: Our Global World in Realtime – The GDELT Project"
[13]: https://www.sec.gov/edgar/sec-api-documentation?utm_source=chatgpt.com "SEC.gov | EDGAR Application Programming Interfaces (APIs)"
[14]: https://fred.stlouisfed.org/docs/api/fred/fred/?utm_source=chatgpt.com "St. Louis Fed Web Services: FRED® API"