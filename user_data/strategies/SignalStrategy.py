"""
SignalStrategy - trade calls with entry, stop loss and take profit.

It runs in dry-run mode only (paper money). On each new candle it checks for a
setup and sends a Telegram message with the trade call. You decide whether to
take the trade on your exchange.

The bot also opens a paper trade for every call and closes it at the same
stop loss / take profit, so /profit and /status in Telegram show how the calls
are actually performing.

Setup (long only, spot):
  - Trend filter: close > EMA200 and EMA50 > EMA200
  - Pullback: RSI(14) crosses back above 40 after dipping below it
  - Volume above its 20-candle average
Levels (ATR based):
  - Stop loss = entry - 1.5 * ATR(14)
  - TP1       = entry + 1.5 * ATR (1R, consider moving SL to entry here)
  - TP2       = entry + 3.0 * ATR (2R, paper trade exits here)
"""

from datetime import datetime, timedelta

import talib.abstract as ta
from pandas import DataFrame

from freqtrade.exchange import timeframe_to_minutes, timeframe_to_prev_date
from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute


class SignalStrategy(IStrategy):
    INTERFACE_VERSION = 3

    timeframe = "1h"
    can_short = False

    # Exits are handled by custom_stoploss / custom_exit from the ATR levels.
    minimal_roi = {"0": 100}
    stoploss = -0.15  # hard safety net only
    use_custom_stoploss = True
    use_exit_signal = True  # required for custom_exit (TP) to be called

    startup_candle_count = 250
    process_only_new_candles = True

    atr_sl_mult = 1.5
    atr_tp1_mult = 1.5
    atr_tp2_mult = 3.0

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        dataframe["ema50"] = ta.EMA(dataframe, timeperiod=50)
        dataframe["ema200"] = ta.EMA(dataframe, timeperiod=200)
        dataframe["rsi"] = ta.RSI(dataframe, timeperiod=14)
        dataframe["atr"] = ta.ATR(dataframe, timeperiod=14)
        dataframe["vol_ma"] = dataframe["volume"].rolling(20).mean()

        dataframe["sl_price"] = dataframe["close"] - self.atr_sl_mult * dataframe["atr"]
        dataframe["tp1_price"] = dataframe["close"] + self.atr_tp1_mult * dataframe["atr"]
        dataframe["tp2_price"] = dataframe["close"] + self.atr_tp2_mult * dataframe["atr"]
        return dataframe

    def populate_entry_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        rsi_cross_up = (dataframe["rsi"] > 40) & (dataframe["rsi"].shift(1) <= 40)
        dataframe.loc[
            (dataframe["close"] > dataframe["ema200"])
            & (dataframe["ema50"] > dataframe["ema200"])
            & rsi_cross_up
            & (dataframe["volume"] > dataframe["vol_ma"])
            & (dataframe["atr"] > 0),
            ["enter_long", "enter_tag"],
        ] = (1, "trend_pullback")

        last = dataframe.iloc[-1]
        if last.get("enter_long") == 1:
            self._send_call(metadata["pair"], last)
        return dataframe

    def populate_exit_trend(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        return dataframe

    def _send_call(self, pair: str, row) -> None:
        entry = row["close"]
        sl = row["sl_price"]
        risk_pct = (entry - sl) / entry * 100
        msg = (
            f"📈 LONG CALL: {pair} ({self.timeframe})\n"
            f"Candle: {row['date']:%Y-%m-%d %H:%M} UTC\n"
            f"Entry: {entry:.6g}\n"
            f"Stop loss: {sl:.6g} (-{risk_pct:.2f}%)\n"
            f"TP1: {row['tp1_price']:.6g} (+{risk_pct * self.atr_tp1_mult / self.atr_sl_mult:.2f}%, 1R)\n"
            f"TP2: {row['tp2_price']:.6g} (+{risk_pct * self.atr_tp2_mult / self.atr_sl_mult:.2f}%, 2R)\n"
            f"RSI: {row['rsi']:.1f}\n"
            f"Not financial advice. Size so a stop-out costs ≤1-2% of your account."
        )
        self.dp.send_msg(msg)

    def _levels(self, pair: str, trade: Trade) -> tuple[float, float] | None:
        """Return (sl, tp2) from the signal candle, cached on the trade."""
        sl = trade.get_custom_data("sl_price")
        tp = trade.get_custom_data("tp2_price")
        if sl is not None and tp is not None:
            return sl, tp

        dataframe, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        # Trade opens on the candle after the signal candle.
        signal_date = timeframe_to_prev_date(self.timeframe, trade.open_date_utc) - timedelta(
            minutes=timeframe_to_minutes(self.timeframe)
        )
        candle = dataframe.loc[dataframe["date"] == signal_date]
        if candle.empty:
            return None
        sl = float(candle["sl_price"].iloc[0])
        tp = float(candle["tp2_price"].iloc[0])
        trade.set_custom_data("sl_price", sl)
        trade.set_custom_data("tp2_price", tp)
        return sl, tp

    def custom_stoploss(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        after_fill: bool,
        **kwargs,
    ) -> float | None:
        levels = self._levels(pair, trade)
        if levels is None:
            return None
        return stoploss_from_absolute(levels[0], current_rate, is_short=trade.is_short)

    def custom_exit(
        self,
        pair: str,
        trade: Trade,
        current_time: datetime,
        current_rate: float,
        current_profit: float,
        **kwargs,
    ) -> str | None:
        levels = self._levels(pair, trade)
        if levels is not None and current_rate >= levels[1]:
            return "take_profit_2R"
        return None
