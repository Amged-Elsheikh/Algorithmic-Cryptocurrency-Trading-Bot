from typing import Dict, List

from math import log10


class Contract:
    def __init__(self, response: Dict, exchange: str):
        self.exchange = exchange
        if exchange == "Binance":
            self.symbol: str = response["symbol"]  # BTCUSDT
            self.baseAsset: str = response["baseAsset"]  # BTC
            self.quoteAsset: str = response["quoteAsset"]  # USDT
            self.pricePrecision = int(response["pricePrecision"])
            self.quantityPrecision = int(response["quantityPrecision"])
            self.minQuantity = float(response["filters"][2]["minQty"])
        elif exchange == "Kucoin":
            self.symbol: str = response["symbol"]  # BTCUSDT
            self.baseAsset: str = response["baseCurrency"]  # BTC
            self.quoteAsset: str = response["quoteCurrency"]  # USDT
            self.pricePrecision = -log10(float(response["quoteIncrement"]))
            self.quantityPrecision = -log10(float(response["baseIncrement"]))
            self.minQuantity = float(response["baseMinSize"])


class CandleStick:
    def __init__(self, response: List, exchange: str):
        self.exchange = exchange
        if exchange == "Binance":
            self.timestamp = int(response[0])
            self.open = float(response[1])
            self.high = float(response[2])
            self.low = float(response[3])
            self.close = float(response[4])
            self.volume = float(response[5])
        elif exchange == "Kucoin":
            self.timestamp = int(response[0])
            self.open = float(response[1])
            self.close = float(response[2])
            self.high = float(response[3])
            self.low = float(response[4])
            self.volume = float(response[5])


class Price:
    def __init__(self, response: Dict[str, str], exchange: str):
        self.exchange = exchange
        if exchange == "Binance":
            self.exchange = "Binance"
            self.symbol = response["symbol"]
            self.bid = float(response["bidPrice"])
            self.ask = float(response["askPrice"])
        elif exchange == "Kucoin":
            self.exchange = "Kucoin"
            self.symbol: str
            self.bid = float(response["bestBid"])
            self.ask = float(response["bestAsk"])


class Order:
    def __init__(self, response, exchange):
        self.exchange = exchange
        if exchange == "Binance":
            self.orderId = str(response["orderId"])
            self.time: int = response["updateTime"]
            self.symbol: str = response["symbol"]
            self.status: str = response["status"]
            self.price = float(response["avgPrice"])
            self.quantity = float(response["origQty"])
            self.is_closed: bool = response["closePosition"]
            self.type: str = response["type"]
            self.side: str = response["side"]
        elif exchange == "Kucoin":
            self.orderId = str(response.get("id"))
            self.time = int(response.get("createdAt"))
            self.symbol: str = response.get("symbol")
            self.price = float(response.get("price"))
            self.quantity = float(response.get("size"))
            self.is_closed: bool = not response.get("isActive")
            self.type: str = response.get("type")
            self.side: str = response.get("side")
            if response.get("size") == response.get("dealSize"):
                self.status = "filled"
            elif response.get("dealSize") == '0' and response.get("isActive"):
                self.status = "new"
            elif response.get("cancelExist"):
                self.status = "canceled"
            else:
                self.status = "partially_filled"


class Balance:
    def __init__(self, response: Dict, exchange):
        self.exchange = exchange
        if exchange == "Binance":
            self.asset: str = response["asset"]  # USDT
            self.pnl = float(response["unrealizedProfit"])
            self.availableBalance = float(response["availableBalance"])
        elif exchange == "Kucoin":
            self.asset: str = response["currency"]  # USDT
            self.pnl = None
            self.availableBalance = float(response["available"])
