import hashlib
import hmac
import json
import logging
import logging.config
import os
import time
from typing import TYPE_CHECKING, Dict, Literal, Union
from urllib.parse import urlencode

import requests
import websocket
from dotenv import load_dotenv
from requests.exceptions import RequestException

from Connectors.crypto_base_class import CryptoExchange
from Moduls.data_modul import Balance, CandleStick, Contract, Order, Price

if TYPE_CHECKING:
    from strategies import Strategy

load_dotenv()
logging.config.fileConfig("logger.config")


class BinanceClient(CryptoExchange):
    def __init__(self, is_test: bool):
        self.logger = logging.getLogger(__name__)
        super().__init__()
        self._endpoints = {
            "ping": "/v3/ping",
            "exchangeInfo": "/v3/exchangeInfo",
            "klines": "/v3/klines",
            "ticker": "/v3/ticker/bookTicker",
            "order": "/v3/order",
            "account": "/v3/account",
        }
        if is_test:
            self._base_url = "https://testnet.binance.vision/api"
            self._ws_url = "wss://testnet.binance.vision/ws"
        else:
            self._base_url = "https://api.binance.com/api"
            self._ws_url = "wss://stream.binance.com:9443/ws"
        # self._check_internet_connection()
        self.prices: Dict[str, Price] = dict()
        self.contracts = self._get_contracts()
        self.getBalance()

    @property
    def _is_connected(self):
        endpoint = self._endpoints["ping"]
        response = self._execute_request(endpoint, "GET", need_sign=False)
        try:
            response.raise_for_status()
            return True
        except Exception:
            return False

    def _check_internet_connection(self):
        connection_flag = 0
        while not self._is_connected:
            if connection_flag >= 5:
                msg = f"{self.exchange} Client failed to connect"
                self.add_log(msg, "error")
                raise Exception(msg)
            else:
                connection_flag += 1
                time.sleep(3)
        msg = "Internet connection established"
        self.add_log(msg, "info")
        return True

    @property
    def exchange(self):
        return "Binance"

    def _execute_request(
        self, endpoint: str, http_method: str, params=dict(), need_sign=True
    ):
        """This argument is used to send all types of requests to the server"""
        headers = {
            "X-MBX-APIKEY": os.getenv("BinanceSpotAPIKey"),
            "Content-Type": "application/json",
        }
        try:
            if need_sign:
                params["timestamp"] = int(time.time() * 1000)
                params["signature"] = self._generate_signature(urlencode(params))
            response = requests.request(
                http_method, self._base_url + endpoint, params=params, headers=headers
            )
            response.raise_for_status()
            return response
        except RequestException as e:
            self.add_log(f"Request Error msg: {response.text} {e}", "error")
        except Exception as e:
            self.add_log(f"Error {e}", "error")
        return

    def _generate_signature(self, query_string: str):
        return hmac.new(
            key=os.getenv("BinanceSpotAPISecret").encode("utf-8"),
            msg=query_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    # ###################### MARKET DATA FUNCTION #######################
    def _get_contracts(self):
        endpoint = self._endpoints["exchangeInfo"]
        response = self._execute_request(endpoint, "GET", need_sign=False)
        if response:
            contracts = {
                symbol["symbol"]: Contract(symbol, self.exchange)
                for symbol in response.json()["symbols"]
            }
            return contracts
        return

    def get_candlestick(self, contract: Contract, interval: str):
        """
        Get a list of the historical Candlestickes for given contract.
        """
        endpoint = self._endpoints["klines"]
        params = {"symbol": contract.symbol, "interval": interval}
        response = self._execute_request(endpoint, "GET", params, need_sign=False)
        if response:
            return [CandleStick(candle, self.exchange) for candle in response.json()]
        return

    def get_price(self, contract: Union[Contract, str]):
        """Get the latest traded price for the contract."""
        endpoint = self._endpoints["ticker"]
        symbol = contract if isinstance(contract, str) else contract.symbol
        params = {"symbol": symbol}
        response = self._execute_request(endpoint, "GET", params, need_sign=False)
        if response:
            self.prices[symbol] = Price(response.json(), self.exchange)
            return self.prices[symbol]
        return

    # ######################### TRADE Arguments ##########################
    def make_order(self, contract: Contract, *, side: str, order_type: str, **kwargs):
        """
        Make a Buy/Long or Sell/Short order for a given contract.
        This argument is a private argument and can only be accesed
        within the connecter, when a buying or selling signal is found,
        or when canceling the runnning strategy
        """
        endpoint = self._endpoints["order"]
        # Add the mandotary parameters
        params = {"symbol": contract.symbol, "side": side, "type": order_type}
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request(endpoint, "POST", params)
        if response:
            order = Order(response.json(), self.exchange)
            return self.order_status(order)
        return

    def order_status(self, order: Order):
        """Get information of a given order."""
        endpoint = self._endpoints["order"]
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request(endpoint, "GET", params)
        if response:
            return Order(response.json(), self.exchange, price=order.price)
        return

    def delete_order(self, order: Order) -> Order:
        """
        Deleting an order. This argument is helpful for future trades,
        or when applying LIMIT/OCO orders."""
        endpoint = self._endpoints["order"]
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request(endpoint, "DELETE", params)
        if response:
            return Order(response.json(), self.exchange)
        return

    # ######################### ACCOUNT Arguments ##########################
    def getBalance(self):
        """
        Update the amount of the currently holded assests in the wallet
        """
        endpoint = self._endpoints["account"]
        response = self._execute_request(endpoint, "GET")
        if response:
            self.balance = {
                asset["asset"]: Balance(asset, self.exchange)
                for asset in response.json()["balances"]
            }
            return self.balance
        return

    # ########################### Websocket Arguments ########################
    def new_subscribe(
        self, channel: Literal["tickers", "candles"], symbol, interval=""
    ):
        contract = self.contracts.get(symbol)
        if not contract:
            self.add_log(msg=f"{symbol} is not correct", level="error")
        elif channel == "tickers":
            self._bookTicket_subscribe(contract)
        elif channel == "candles":
            self._kline_subscribe(contract, interval)
        return

    def _bookTicket_subscribe(self, contract: Contract):
        params = f"{contract.symbol.lower()}@bookTicker"
        if contract in self.bookTicker_subscribtion_list:
            self.add_log(f"Already subscribed to {params}", "info")
            return
        msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
        # immediatly show current bid and ask prices.
        self.get_price(contract)
        self._ws.send(json.dumps(msg))
        self.bookTicker_subscribtion_list[contract] = self.id
        self.id += 1
        return

    def _kline_subscribe(self, contract: Contract, interval: str):
        # Make sure the contract is in the bookTicker.
        if contract not in self.bookTicker_subscribtion_list:
            self._bookTicket_subscribe(contract)
        symbol = contract.symbol
        strategy_key = f"{symbol}_{interval}"
        if strategy_key in self.strategy_counter:
            self.strategy_counter[strategy_key]["count"] += 1
            return
        params = f"{symbol.lower()}@kline_{interval}"
        msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
        self._ws.send(json.dumps(msg))
        self.strategy_counter[strategy_key] = {"count": 1, "id": self.id}
        self.id += 1
        return

    def unsubscribe_channel(
        self,
        channel: Literal["tickers", "candles"],
        *,
        symbol: str = None,
        strategy: "Strategy" = None,
    ):
        if channel == "tickers":
            self._bookTicker_unsubscribe(symbol)
        elif channel == "candles":
            self._kline_unsubscribe(strategy)
        return

    def _bookTicker_unsubscribe(self, symbol: str):
        running_strategies = [x.split("_")[0] for x in self.strategy_counter.keys()]
        if symbol in running_strategies:
            msg = (
                f"{symbol} had a running strategy and "
                "can't be removed from the watchlist"
            )
            self.add_log(msg, "info")
            return
        _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
        msg = {
            "method": "UNSUBSCRIBE",
            "params": [f"{symbol.lower()}@bookTicker"],
            "id": _id,
        }
        self._ws.send(json.dumps(msg))
        self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
        self.prices.pop(symbol)
        return

    def _kline_unsubscribe(self, strategy: "Strategy"):
        symbol = strategy.symbol
        interval = strategy.interval
        counters_key = strategy.ws_channel_key
        self.running_startegies.pop(strategy.strategy_key)
        self.strategy_counter[counters_key]["count"] -= 1
        if self.strategy_counter[counters_key]["count"] == 0:
            msg = {
                "method": "UNSUBSCRIBE",
                "params": [f"{symbol.lower()}@kline_{interval}"],
                "id": self.strategy_counter[counters_key]["id"],
            }
            self._ws.send(json.dumps(msg))
            self.strategy_counter.pop(counters_key)
        return

    # ########################### Strategy Arguments ##########################
    def _on_message(self, ws: websocket.WebSocketApp, msg):
        data = json.loads(msg)
        channel = data.get("e")
        symbol = data.get("s")
        # Spot websocket API does not show event name in case of bookTicker
        if channel == "bookTicker" or (channel is None and "a" in data and "b" in data):
            self._bookTickerMsg(data, symbol)
        elif channel == "kline":
            self._klineMsg(data, symbol)
        else:
            return

    def _bookTickerMsg(self, data, symbol):
        self.prices[symbol].bid = float(data["b"])
        self.prices[symbol].ask = float(data["a"])
        # Check the status of the order for each running strategy
        for strategy in list(self.running_startegies.values()):
            if symbol != strategy.symbol or not hasattr(strategy, "order"):
                continue
            if strategy.order.status in ["CANCELED", "REJECTED", "EXPIRED"]:
                self._kline_unsubscribe(strategy)
                continue
            elif strategy.order.status in ["NEW", "PARTIALLY_FILLED"]:
                strategy.order = self.order_status(strategy.order)
            if strategy.order.status == "FILLED":
                # Calculate the uPnL only when an order is made
                self._check_tp_sl(strategy)
        return

    def _klineMsg(self, data, symbol):
        """
        AggTrade message is send when a trade is made.
        Used to update indicators and make trading decision.

        Subscribe to this channel when starting new strategy, and cancel the
        subscribtion once all running strategies for a given contract stopped.
        """
        data = data["k"]
        candle = [data[i] for i in ["t", "o", "h", "l", "c", "v"]]
        sent_candle = CandleStick(candle, self.exchange)
        for strategy in list(self.running_startegies.values()):
            if strategy.ws_channel_key == f'{symbol}_{data["i"]}':
                decision = strategy.parse_trade(sent_candle)
                self._process_dicision(strategy, decision)
        return

    def _process_dicision(self, strategy: "Strategy", decision: str):
        if decision == "buy or hodl" and not hasattr(strategy, "order"):
            self._buy_with_strategy(strategy)
            self.getBalance()
        elif decision == "sell or don't enter" and hasattr(strategy, "order"):
            self._sell_with_strategy(strategy)
            self.getBalance()
        return

    def _buy_with_strategy(self, strategy: "Strategy"):
        latest_price = strategy.df["close"].iloc[-1]
        base_asset = strategy.contract.quoteAsset
        balance = self.balance[base_asset].availableBalance
        buy_margin = balance * strategy.buy_pct
        quantity_margin = (buy_margin / latest_price) * 0.95
        stepSize = strategy.contract.stepSize
        quantity_margin = round(quantity_margin / stepSize) * stepSize
        if quantity_margin < strategy.contract.minQuantity:
            msg = (
                f"could not buy {self.strategy.contract.symbol}"
                "because the ordered quantity is less than the"
                "minimum margin. Strategy is removed"
            )
            self.add_log(msg, "info")
            self._kline_unsubscribe(strategy)
            return
        order = self.make_order(
            strategy.contract,
            side="BUY",
            order_type="MARKET",
            quantity=quantity_margin,
        )
        if order:
            order.price = latest_price
            order = self.order_status(order)
            strategy.order = order
            msg = (
                f"{strategy.order.symbol} buying order was made. "
                f"Quantity: {strategy.order.quantity}. "
                f"Price: {strategy.order.price}"
            )
            self.add_log(msg, "info")
        return

    def _sell_with_strategy(self, strategy: "Strategy"):
        sell_order = self.make_order(
            contract=strategy.contract,
            side="SELL",
            order_type="MARKET",
            quantity=strategy.order.quantity,
        )
        if sell_order:
            sell_order.price = strategy.df["close"].iloc[-1]
            while sell_order.status != "FILLED":
                sell_order = self.order_status(sell_order)
                time.sleep(2)
            strategy.relaizedPnL += strategy._PnLcalciator(sell_order)
            strategy.order = sell_order
            self._kline_unsubscribe(strategy)
        return

    def close(self):
        self._ws.close()
