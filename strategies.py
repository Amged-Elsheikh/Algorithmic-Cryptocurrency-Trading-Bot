from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Dict, List, Tuple

import numpy as np
import pandas as pd

from Moduls.data_modul import Order

if TYPE_CHECKING:
    from Connectors.binance_connector import BinanceClient

import warnings

warnings.filterwarnings("ignore")


m = 60
h = 60 * m
d = 24 * h
intervals_to_sec = {"1m": m, "15m": 15 * m, "30m": 30 * m, "1h": h,
                    "2h": 2 * h, "4h": 4 * h, "8h": 8 * h, "12h": 12 * h,
                    "1d": d, "2d": 2 * d}


class Strategy(ABC):
    new_strategy_id = 1

    def __init__(
        self,
        client: "BinanceClient",
        symbol: str,
        interval: str,
        tp: float,
        sl: float,
        buy_pct: float,
    ):
        # running_strategies variable is a dictionary where the key is the
        # symbol and the values is another
        self.client = client
        # To unsubscribe a channel in binance, you need to provide an id
        self.symbol = symbol
        self.contract = self.client.contracts[symbol]
        self.timeframe = intervals_to_sec[interval] * 1000

        self.client.new_subscribe(channel="aggTrade", symbol=self.symbol)
        self.client.logger.info("Strategy added succesfully.")
        self.id = self.client.strategy_counter[self.symbol]["id"]
        self.strategy_id = Strategy.new_strategy_id

        self.candles = self.client.get_candlestick(self.contract, interval)
        self.order: Order
        self.had_assits = False
        self.is_running = True
        """
        Used to remove the strategy from the connector after it's been closed
        """
        self.relaizedPnL = 0
        self.unpnl = 0
        self.tp = tp  # Take profit
        self.sl = sl  # Stop Loss
        self.buy_pct = (
            buy_pct  # The percentage of available balance to use for the trade
        )
        candles_range = range(len(self.candles))
        data = {
            "timestamp": [self.candles[i].timestamp for i in candles_range],
            "open": [self.candles[i].open for i in candles_range],
            "close": [self.candles[i].close for i in candles_range],
            "high": [self.candles[i].high for i in candles_range],
            "low": [self.candles[i].low for i in candles_range],
            "volume": [self.candles[i].volume for i in candles_range],
        }
        self.df = pd.DataFrame(data)
        self.client.running_startegies[f"{self.symbol}_{self.strategy_id}"] =\
            self
        Strategy.new_strategy_id += 1

    def _update_candles(self, price: float, volume: float, timestamp: int):
        """
        price: Last tranasaction price
        size: Last transaction quantity
        timestamp: the time of the last transaction in ns
        """
        n = len(self.df) - 1
        # Check if the last trade belongs to the last candle
        if timestamp < self.df.loc[n, "timestamp"] + self.timeframe:
            self.df.loc[n, "close"] = price
            self.df.loc[n, "volume"] += volume
            if price > self.df.loc[n, "high"]:
                self.df.loc[n, "high"] = price
            elif price < self.df.loc[n, "low"]:
                self.df.loc[n, "low"] = price
            return "Same candle"
        # For new candle, there might be some missing candles
        else:
            last_candle = self.df.loc[n]
            # Account for missing candles
            missing_candles = int(
                (timestamp - last_candle.timestamp) / self.timeframe - 1
            )
            # If there are any missing candles, create them
            for _ in range(missing_candles):
                open_time = last_candle.timestamp + self.timeframe
                open_ = close = high = low = np.nan
                volume = 0
                self.df.loc[len(self.df), :] = [
                    open_time,
                    open_,
                    close,
                    high,
                    low,
                    volume,
                ]
                last_candle = self.df.loc[n]
            # Update the last candle
            last_candle = self.df.loc[n]
            open_time = last_candle.timestamp + self.timeframe
            self.df.loc[len(self.df), :] = [
                open_time,
                price,
                price,
                price,
                price,
                volume,
            ]
            return "New candle"

    @abstractmethod
    def parse_trade(self, price: float, volume: float, timestamp: int) -> str:
        pass


class TechnicalStrategies(Strategy):
    def __init__(
        self,
        client: "BinanceClient",
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

    def parse_trade(self, price: float, volume: float, timestamp: int) -> str:
        """
        This function will keep updating the technical indicators values
        and trade if needed
        """
        candle = self._update_candles(price, volume, timestamp)
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

        if confidence >= 7:
            return "buy or hodl"
        elif confidence >= 4:
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
