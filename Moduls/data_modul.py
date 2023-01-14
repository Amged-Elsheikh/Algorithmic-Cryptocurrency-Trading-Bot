from typing import *


class Contract:
    def __init__(self, response: Dict, exchange: str):
        self.exchange = exchange
        if exchange == 'Binance':
            self.symbol: str = response['symbol'] # BTCUSDT
            self.baseAsset: str = response['baseAsset'] # BTC
            self.quoteAsset: str = response['quoteAsset'] # USDT
            self.pricePrecision = int(response['pricePrecision'])
            self.quantityPrecision = int(response['quantityPrecision'])
            self.minQuantity = float(response['filters'][2]['minQty'])
            
    
class CandleStick:
    def __init__(self, response: List, exchange: str):
        if exchange == 'Binance':
            self.timestamp: int = response[0]
            self.open = float(response[1])
            self.high = float(response[2])
            self.low = float(response[3])
            self.close = float(response[4])
            self.volume = float(response[5])
            
            
class Price:
    def __init__(self, response: Dict[str, str], exchange: str):
        if exchange == 'Binance':
            self.exchange = 'Binance'
            self.symbol: str = response['symbol']
            self.bid = float(response['bidPrice'])
            self.ask = float(response['askPrice'])
            

class Order:
    def __init__(self, response, exchange):
        if exchange == 'Binance':
            self.orderId: int = response['orderId']
            self.time: int = response['updateTime']
            self.symbol: str = response['symbol']
            self.status: str = response['status']
            self.price = float(response['avgPrice'])
            self.quantity = int(response['origQty']) if '.' not in response['origQty']\
                else float(response['origQty'])
            self.is_closed: bool = response['closePosition']
            self.type: str = response['type']
            self.side: str = response['side']
            
class Balance:
    def __init__(self, response, exchange):
        if exchange == 'Binance':
            self.asset: str = response['asset']
            self.balance = float(response['walletBalance'])
            self.pnl = float(response['unrealizedProfit'])
            self.availableBalance = float(response['availableBalance'])
            
            