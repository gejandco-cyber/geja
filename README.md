# Signal bot (freqtrade, alerts only)

Sends trade calls to Telegram with **entry, stop loss, TP1 and TP2**. You decide
whether to take each trade on your exchange. The bot runs in `dry_run` (paper money)
and never places real orders. It needs no exchange API keys.

Every call is also paper-traded with the same SL/TP, so Telegram `/profit`,
`/status` and `/performance` show the calls' real track record.

## Example call

```
📈 LONG CALL: SOL/USDT (1h)
Candle: 2026-10-06 21:00 UTC
Entry: 142.35
Stop loss: 139.80 (-1.79%)
TP1: 144.90 (+1.79%, 1R)
TP2: 147.45 (+3.58%, 2R)
RSI: 41.2
```

## Backtest results (read before trusting any call)

Same 10 pairs, Feb 2025 – Oct 2026, 0.1% fees (market fell ~45% over the period):

| Timeframe | Calls | Win rate | Profit factor | Result |
|---|---|---|---|---|
| 1h | 454 | 26% | 0.61 | **-24%** |
| 4h | 97 | 29% | 0.68 | **-8%** |

**This strategy as written loses money.** At 2R you need over 34% wins to break
even after fees. Treat it as a working template for the alert pipeline, not as a
profitable system. Change the logic in `user_data/strategies/SignalStrategy.py`, backtest
again, and only act on calls once the strategy shows an edge on data it wasn't tuned on.

## Setup

1. Create a Telegram bot with [@BotFather](https://t.me/BotFather) and copy the token.
   Send your bot a message, then open
   `https://api.telegram.org/bot<TOKEN>/getUpdates` to find your `chat_id`.
2. `cp .env.example .env` and fill in the token and chat_id.
3. Run it (requires Docker):
   ```
   docker compose up -d
   docker compose logs -f
   ```
   It must run 24/7 (a VPS or always-on machine) to catch signals.

Binance is blocked in some countries (e.g. the US). If so, change
`exchange.name` in `user_data/config.json` to one available to you
(`okx`, `kraken`, `bybit`, ...).

## Backtesting

```
docker compose run --rm freqtrade download-data --timerange 20250101- -t 1h
docker compose run --rm freqtrade backtesting --timerange 20250201- --strategy SignalStrategy
```

## Taking a call manually

- Size each position so hitting the stop loses at most 1–2% of your account:
  `position size = (account × risk%) / (entry − stop)`.
- Place the stop loss on the exchange as soon as you enter.
- Optional: take partial profit at TP1 and move the stop to entry.
- Skip calls where price has already moved well past the entry.
