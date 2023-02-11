from typing import *

import numpy as np
import pandas as pd

from Moduls.data_modul import *
if TYPE_CHECKING:
    from Connectors.binance_connectore import BinanceClient

import warnings
warnings.filterwarnings('ignore')


m = 60
h = 60 * m
d = 24 * h
intervals_to_sec = { "1m": m, "15m": 15 * m, "30m": 30 * m, 
                    "1h": h, "2h": 2 * h, "4h": 4 * h, "8h": 8 * h,
                    "12h": 12 * h, "1d": d, "2d": 2 * d}
class Strategy:

    def __init__(self, client: 'BinanceClient', symbol: str, interval: str,
                 ema: Dict[str, int], macd: Dict[str, int], tp: float, sl: float,
                 buy_pct: float, af=0.02, af_max=0.2, af_step=0.02, rsi=24):
        # running_strategies variable is a dictionary where the key is the symbol and the values is another
        self.client = client
        if self.client.exchange=='Binance':
            # To unsubscribe a channel in binance, you need to provide an id
            self.id = self.client.id
            
        self.contract = self.client.contracts[symbol]
        self.timeframe = intervals_to_sec[interval] * 1000
        
        candles = self.candles = self.client.get_candlestick(self.contract, interval)
        self.order: List[Order] = []
        self.had_assits = False
        self.is_running = True
        """Use this to remove the strategy from the connector after it's been closed"""
        
        self.relaizedPnL = 0
        self.tp = tp # Take profit
        self.sl = sl # Stop Loss
        self.buy_pct = buy_pct # The percentage of available balance to use for the trade

        columns = ["timestamp", "open", "close", "high", "low", "volume"]
        
        data = {'timestamp': [self.candles[i].timestamp for i in range(len(self.candles))],
                'open': [self.candles[i].open for i in range(len(self.candles))],
                'close': [self.candles[i].close for i in range(len(self.candles))],
                'high': [self.candles[i].high for i in range(len(self.candles))],
                'low': [self.candles[i].low for i in range(len(self.candles))],
                'volume': [self.candles[i].volume for i in range(len(self.candles))]}

        self.df = pd.DataFrame(data)
        # Load technical indicator parameters
        self.ema = ema
        self.macd = macd
        self.rsi = rsi
        # for parabolic SAR, keep track of the extreme value
        self._ep = self.df.loc[0, "high"]
        self._sar: List[float] = [self.df.loc[0, "low"]]
        self._af_step = af_step
        self._af_init = self._af = af
        self._af_max = af_max
        self._trend = "up"  # intialize as a up trend
        
        self.client.running_startegies.add(self)
        self.client.new_subscribe(symbol, 'aggTrade')
        print('Strategy added succesfully.')

    def _update_candles(self, price: float, volume: float, timestamp: int) -> str:
        """
        price: Last tranasaction price
        size: Last transaction quantity
        timestamp: the time of the last transaction in ns
        """
        # Check if the last trade belongs to the last candle
        if timestamp < self.df.iloc[-1].timestamp + self.timeframe:
            self.df.iloc[-1].close = price
            self.df.iloc[-1].volume += volume
            if price > self.df.iloc[-1].high:
                self.df.iloc[-1].high = price
            elif price < self.df.iloc[-1].low:
                self.df.iloc[-1].low = price
            return "same candle"

        # For new candle, there might be some missing candles
        else:
            # Account for missing candles
            missing_candles = (timestamp - last_candle.timestamp) // self.timeframe - 1
            # If there are any missing candles, create them
            for _ in range(missing_candles):
                last_candle = self.df.iloc[-1]
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

            last_candle = self.df.iloc[-1]
            open_time = last_candle.timestamp + self.timeframe
            self.df.loc[len(self.df), :] = [
                open_time,
                price,
                price,
                price,
                price,
                volume,
            ]
            return "new candle"

    def parse_trade(self, price: float, volume: float, timestamp: int) -> str:
        """
        This function will keep updating the technical indicators values and trade if needed
        """
        self._update_candles(price, volume, timestamp)
        
        ema_check = 3 * int(self._EMA(self.ema['slow']) < self._EMA(self.ema['fast']))

        macd, macd_signal = self._MACD()
        rsi = self._RSI()
        _ = self._parabolic_sar()
        confidence = ema_check + self.macd_eval(macd, macd_signal) + self.RSI_eval(rsi.iloc[-1]) + self.sar_eval(self._trend)

        if confidence >= 7:
            return 'buy or hodl'
        elif confidence >= 5:
            return 'hodl'
        else:
            "sell or don't enter"

    def _EMA(self, window: int) -> float:
        return self.df["close"].ewm(span=window, ignore_na=True).mean().iloc[-1]

    def _MACD(self) -> Tuple[float, float]:
        slow_macd = self._EMA(self.macd["slow"])
        fast_macd = self._EMA(self.macd["fast"])
        macd_signal = self._EMA(self.macd["signal"])
        return slow_macd - fast_macd, macd_signal

    def _RSI(self) -> float:
        df = self.df.copy()
        
        df['diff'] = df["close"].diff()
        
        df['up'] = np.where(df['diff'] > 0, df['diff'], 0)
        df['down'] = np.where(df['diff'] < 0, abs(df['diff']), 0)
        
        gain = df['up'].rolling(self.rsi).mean()
        loss = df['down'].rolling(self.rsi).mean()
        
        rs = gain / loss
        # Calculate the RSI
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def _parabolic_sar(self, calc_all=False) -> float:
        """
        https://raposa.trade/blog/the-complete-guide-to-calculating-the-parabolic-sar-in-python/
        """
        if calc_all:
            data = self.df
        else:
            data = self.df.iloc[-2:]

        for i in data.index[1:]:
            low = self.df.loc[i, "low"]
            high = self.df.loc[i, "high"]
            if high:  # Make sure there was a trade
                if self._trend == "up":
                    if self._sar[-1] > low:
                        # Trend reverse
                        self._trend = "down"
                        self._af = self._af_init
                        sar = self._ep
                        self._ep = low
                        sar = sar - self._af * (sar - self._ep)
                        sar = max(sar, high)

                    else:
                        if high > self._ep:
                            # Trend continue
                            self._ep = high
                            self._af = min(self._af + self._af_step, self._af_max)
                        sar = self._sar[-1] + self._af * (self._ep - self._sar[-1])
                        sar = min(sar, low)

                elif self._trend == "down":
                    if high < self._sar[-1]:
                        # Reversal
                        self._trend = "up"
                        self._af = self._af_init
                        sar = self._ep
                        self._ep = high
                        sar = sar + self._af * (self._ep - sar)
                        sar = min(sar, low)
                    else:
                        if low < self._ep:
                            self._ep = low
                            self._af = min(self._af + self._af_step, self._af_max)
                        sar = self._sar[-1] - self._af * (sar - self._ep)
                        sar = max(sar, high)
            else:
                sar = self._sar[-1]
            self._sar.append(sar)
            return sar
    
    @classmethod
    def RSI_eval(cls, rsi: float) -> int:
        if rsi >= 90:
            return 3
        elif rsi >= 80:
            return 2
        elif rsi >= 65:
            return 1
        elif rsi > 50:
            return 0
        else:
            return -1

    @classmethod
    def macd_eval(cls, macd: float, macd_signal: float) -> int:
        if macd > macd_signal:
            if macd_signal > 0:
                return 3
            elif macd > 0:
                return 2
            else:
                return 1
        else:
            if macd_signal < 0 or macd < 0:
                return -2
            else:
                return -1

    @classmethod
    def sar_eval(cls, trend: str) -> int:
        return 3 if trend == "up" else 0