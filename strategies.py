from abc import ABC, abstractmethod
from typing import Dict, List, Tuple
import re

import numpy as np
import pandas as pd

from Moduls.data_modul import Order, CandleStick

from Connectors.crypto_base_class import CryptoExchange

import warnings

warnings.filterwarnings("ignore")


m = 60
h = 60 * m
d = 24 * h
intervals_to_sec = {
    "1m": m,
    "15m": 15 * m,
    "30m": 30 * m,
    "1h": h,
    "2h": 2 * h,
    "4h": 4 * h,
    "6h": 6 * h,
    "8h": 8 * h,
    "12h": 12 * h,
    "1d": d,
    "2d": 2 * d,
}


class Strategy(ABC):
    new_strategy_id = 1

    def __init__(
        self,
        client: "CryptoExchange",
        symbol: str,
        interval: str,
        tp: float,
        sl: float,
        buy_pct: float,
    ):
        self.client = client
        self.symbol = symbol
        self.contract = self.client.contracts[symbol]
        self.relaizedPnL = 0
        self.unpnl = 0
        self.tp = tp
        self.sl = sl
        self.buy_pct = buy_pct
        self.interval = interval
        interval = re.match(r"[0-9]+[a-zA-Z]", interval).group(0)
        self.timeframe = intervals_to_sec[interval] * 1000
        self.client.new_subscribe("candles", symbol, self.interval)
        self.ws_channel_key = f"{symbol}_{interval}"
        self.strategy_key = f"{self.ws_channel_key}_{Strategy.new_strategy_id}"
        self.client.running_startegies[self.strategy_key] = self
        Strategy.new_strategy_id += 1
        self.candles = self.client.get_candlestick(self.contract, interval)
        data = [
            {
                "timestamp": candle.timestamp,
                "open": candle.open,
                "close": candle.close,
                "high": candle.high,
                "low": candle.low,
                "volume": candle.volume,
            }
            for candle in self.candles
        ]
        self.df = pd.DataFrame(data)
        self.order: Order
        self.client.add_log(f"{self.symbol} Strategy added succesfully.", "info")

    def _update_candles(self, new_candle: CandleStick):
        last_candle = self.df.iloc[-1]
        # Check if the last trade belongs to the last candle
        if new_candle.timestamp == last_candle["timestamp"]:
            last_candle = new_candle
            return "Same candle"
        # Account for missing candles
        missing_candles = (
            new_candle.timestamp - last_candle["timestamp"]
        ) / self.timeframe - 1
        # If there are any missing candles, create them
        for _ in range(int(missing_candles)):
            open_time = last_candle["timestamp"] + self.timeframe
            open_price = close_price = high = low = np.nan
            volume = 0
            self.df.loc[len(self.df)] = [
                open_time,
                open_price,
                close_price,
                high,
                low,
                volume,
            ]
            last_candle = self.df.iloc[-1]
        self.df.loc[len(self.df), :] = [
            new_candle.timestamp,
            new_candle.open,
            new_candle.close,
            new_candle.high,
            new_candle.low,
            new_candle.volume,
        ]
        return "New candle"

    def _PnLcalciator(self, sell_order: Order) -> float:
        sell_margin = sell_order.quantity * sell_order.price
        buy_margin = self.order.quantity * self.order.price
        return sell_margin - buy_margin

    @abstractmethod
    def parse_trade(self, new_candle: CandleStick) -> str:
        pass


class TechnicalStrategies(Strategy):
    def __init__(
        self,
        client: "CryptoExchange",
        symbol: str,
        interval: str,
        tp: float,
        sl: float,
        buy_pct: float,
        ema: Dict[str, int],
        macd: Dict[str, int],
        af=0.02,
        af_max=0.2,
        af_step=0.02,
        rsi=12,
    ):
        super().__init__(client, symbol, interval, tp, sl, buy_pct)
        # Load technical indicator parameters
        self.ema = ema
        self.macd = macd
        self.rsi = rsi
        # for parabolic SAR, keep track of the extreme value
        self._ep = self.df.loc[0, "high"]
        self._sar: List[float] = []
        self._af_step = af_step
        self._af_init = self._af = af
        self._af_max = af_max
        self._SAR()

    def parse_trade(self, new_candle: CandleStick) -> str:
        """
        This function will keep updating the technical indicators values
        and trade if needed
        """
        candle = self._update_candles(new_candle)
        ema_fast = self._EMA(self.ema["fast"]).iloc[-1]
        ema_slow = self._EMA(self.ema["slow"]).iloc[-1]
        ema_check = 3 * int(ema_fast > ema_slow)

        macd, macd_signal = self._MACD()
        rsi = self._RSI()
        if candle == "New candle":
            self._SAR()
        confidence = (
            ema_check
            + self._macd_eval(macd, macd_signal)
            + self._RSI_eval(rsi)
            + 3 * int(self._upTrend)
        )

        if confidence >= 6:
            return "buy or hodl"
        elif confidence < 3:
            return "sell or don't enter"

    def _EMA(self, window: int) -> pd.Series:
        return self.df["close"].ewm(span=window).mean()

    def _MACD(self) -> Tuple[float, float]:
        slow_macd = self._EMA(self.macd["slow"])
        fast_macd = self._EMA(self.macd["fast"])
        macd = fast_macd - slow_macd
        macd_signal = macd.ewm(span=self.macd["signal"]).mean()
        macd_signal = macd - macd_signal
        return macd.iloc[-1], macd_signal.iloc[-1]

    def _RSI(self) -> float:
        diff = self.df["close"].diff()
        up = diff.where(diff > 0, 0)
        down = diff.where(diff < 0, 0)
        down *= -1
        gain = up.ewm(span=self.rsi, min_periods=self.rsi).mean().iloc[-1]
        loss = down.ewm(span=self.rsi, min_periods=self.rsi).mean().iloc[-1]
        rsi = 100 if loss == 0 else 100 - (100 / (1 + (gain / loss)))
        return np.round(rsi, 2)

    def _SAR(self):
        if not self._sar:
            self._calculate_first_sar()

        low = self.df.loc[:, "low"].iloc[-1]
        high = self.df.loc[:, "high"].iloc[-1]
        sar = self._sar[-1]

        if self._upTrend:
            if sar > low:
                reversal = True
                self._downTrend = True
                sar = max(self._ep, high)
                self._ep = low
                self._af = self._af_step
            else:
                reversal = False
        elif self._downTrend:
            if sar < high:
                reversal = True
                self._upTrend = True
                sar = min(self._ep, low)
                self._ep = high
                self._af = self._af_step
            else:
                reversal = False

        if not reversal:
            if self._upTrend and high > self._ep:
                self._ep = high
                self._af = min(self._af_max, self._af + self._af_step)
            elif self._downTrend and low < self._ep:
                self._ep = low
                self._af = min(self._af_max, self._af + self._af_step)

        if self._upTrend:
            sar = min(sar, min(self.df.loc[:, "low"].iloc[-3:-1]))
        elif self._downTrend:
            sar = max(sar, max(self.df.loc[:, "high"].iloc[-3:-1]))

        sar += self._af * (self._ep - sar)
        self._sar.append(sar)
        return

    def _calculate_first_sar(self):
        prev_low = self.df.loc[:, "low"].iloc[-2]
        prev_high = self.df.loc[:, "high"].iloc[-2]
        prev_close = self.df.loc[:, "close"].iloc[-2]
        curr_low = self.df.loc[:, "low"].iloc[-1]
        curr_high = self.df.loc[:, "high"].iloc[-1]
        curr_close = self.df.loc[:, "close"].iloc[-1]
        if curr_close > prev_close:
            self._upTrend = True
            self._ep = curr_high
            sar = prev_low
        else:
            self._downTrend = True
            self._ep = curr_low
            sar = prev_high

        sar = sar + self._af_init * (self._ep - sar)
        self._sar.append(sar)
        return

    def _RSI_eval(self, rsi: float) -> int:
        if rsi >= 70:
            return 3
        elif rsi >= 60:
            return 2
        elif rsi >= 50:
            return 1
        elif rsi >= 40:
            return 0
        elif rsi >= 30:
            return -1
        else:
            return -10

    def _macd_eval(self, macd: float, macd_signal: float) -> int:
        if macd > macd_signal:
            if macd_signal > 0:
                return 3
            elif macd > 0:
                return 2
            else:
                return 1
        else:
            if macd_signal < 0:
                return -3
            else:
                return -2

    @property
    def _downTrend(self):
        return not self._upTrend

    @_downTrend.setter
    def _downTrend(self, value: bool):
        self._upTrend = not value
