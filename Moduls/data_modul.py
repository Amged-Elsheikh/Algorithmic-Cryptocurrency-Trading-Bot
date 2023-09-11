from typing import Dict, List, Union

from math import log10


class Contract:
    def __init__(self, response: Dict, exchange: str):
        self.exchange = exchange
        if exchange == "Binance":
            self.symbol: str = response["symbol"]  # BTCUSDT
            self.baseAsset: str = response["baseAsset"]  # BTC
            self.quoteAsset: str = response["quoteAsset"]  # USDT
            self.pricePrecision = int(response["quotePrecision"])
            self.quantityPrecision = int(response["baseAssetPrecision"])
            for filter_ in response["filters"]:
                if filter_["filterType"] != "LOT_SIZE":
                    continue
                self.minQuantity = float(filter_["minQty"])
                self.maxQuantity = float(filter_["maxQty"])
                self.stepSize = float(filter_["stepSize"])
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
            self.timestamp = int(response[0])  # Open timestamp
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
    def __init__(self, response, exchange, price: Union[float, None] = None):
        self.exchange = exchange
        if exchange == "Binance":
            self.symbol: str = response["symbol"]
            self.orderId = str(response["orderId"])
            self.time: int = response["workingTime"]
            self.price = float(response["price"]) if price is None else price
            self.quantity = float(response["origQty"])
            self.status: str = response["status"]
            self.type: str = response["type"]
            self.side: str = response["side"]
        elif exchange == "Kucoin":
            self.orderId = str(response.get("id"))
            self.time = int(response.get("createdAt"))
            self.symbol: str = response.get("symbol")
            self.price = float(response.get("price")) if price is None else price
            self.quantity = float(response.get("size"))
            self.is_closed: bool = not response.get("isActive")
            self.type: str = response.get("type")
            self.side: str = response.get("side")
            if response.get("size") == response.get("dealSize"):
                self.status = "filled"
            elif response.get("dealSize") == "0" and response.get("isActive"):
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
            self.availableBalance = float(response["free"])
            self.totalBalance = float(response["free"]) + float(response["locked"])
        elif exchange == "Kucoin":
            self.asset: str = response["currency"]  # USDT
            self.availableBalance = float(response["balance"])
            self.totalBalance = float(response["free"]) + float(response["locked"])
