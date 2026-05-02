# Risk Policy

The project is paper-first. Live trading is disabled until explicit gates and all quality checks pass.

## Quarter-Kelly

Position sizing uses binary share Kelly with executable entry price:

```text
b = (1 - entry_price) / entry_price
q = 1 - win_prob
full_kelly = (b * win_prob - q) / b
quarter_kelly = 0.25 * max(0, full_kelly)
```

Full Kelly is not used because probability estimates are noisy, CLOB liquidity is finite, spreads move, and short-window markets can reprice faster than the model.

## Probability Discount

Raw model probabilities are discounted toward executable market price:

```text
p_adjusted = market_price + confidence_discount * (model_probability - market_price)
```

Default `confidence_discount` is capped at `0.50`. Final probability is clipped to `[0.05, 0.95]`.

## Default Caps

- `KELLY_FRACTION = 0.25`
- `MAX_ORDER_USD = 10`
- `MAX_MARKET_EXPOSURE_USD = 25`
- `MAX_OPEN_POSITIONS = 4`
- `DAILY_LOSS_LIMIT_USD = 30`
- `MAX_PORTFOLIO_EXPOSURE_PCT = 0.20`
- `MIN_EDGE = 0.03`
- `MAX_SLIPPAGE = 0.02`
- `MIN_ORDERBOOK_DEPTH_USD = 25`
- `MIN_HOURS_TO_EXPIRY = 2`
- `ALLOW_LIVE_TRADING = false`

## Circuit Breakers

Reject:

- no usable orderbook
- insufficient executable liquidity
- slippage above cap
- entry price below `0.03` or above `0.97`
- adjusted edge below `0.03`
- adjusted edge above `0.30` without manual approval
- daily loss limit breach
- max open positions breach
- per-market or portfolio exposure breach
- near-expiry markets

## Live Activation

Live order posting must require:

- `ALLOW_LIVE_TRADING=true`
- explicit CLI `--live`
- private key loaded from `.env`
- V2 market metadata available
- order passes shared validator
- max order size cap
- daily loss limit
- max open positions
- max per-market exposure

No proxy/IP rotation, geo bypass, or Cloudflare evasion is allowed.

