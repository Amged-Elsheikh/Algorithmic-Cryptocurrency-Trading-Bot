import hashlib
import hmac
import json
import logging
import logging.config
import os
import time
from typing import TYPE_CHECKING, Dict, Literal
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
    _loaded = dict()

    def __new__(cls, is_spot: bool, is_test: bool):
        if (client := cls._loaded.get(f"{is_spot} {is_test}")) is None:
            client = super().__new__(cls)
            cls._loaded[f"{is_spot} {is_test}"] = client
        return client

    def __init__(self, is_spot: bool, is_test: bool):
        self._init(is_spot, is_test)
        self._header = {
            "X-MBX-APIKEY": os.getenv(self._api_key),
            "Content-Type": "application/json",
        }
        self.logger = logging.getLogger(__name__)
        super().__init__()
        self._check_internet_connection()
        self.contracts = self._get_contracts()
        self.prices: Dict[str, Price] = dict()

    def _init(self, is_spot: bool, is_test: bool):
        urls = {
            (True, True): (
                "https://testnet.binance.vision/api",
                "wss://testnet.binance.vision/ws",
            ),
            (True, False): (
                "https://api.binance.com/api",
                "wss://stream.binance.com:9443/ws",
            ),
            (False, True): (
                "https://testnet.binancefuture.com",
                "wss://stream.binancefuture.com/ws",
            ),
            (False, False): (
                "https://fapi.binance.com",
                "wss://fstream.binance.com/ws",
            ),
        }
        self._base_url, self._ws_url = urls[(is_spot, is_test)]
        spot_future = "Spot" if is_spot else "Future"
        real_test = "Test" if is_test else ""
        self._api_key = f"{self.exchange}{spot_future}{real_test}APIKey"
        self._api_secret = self._api_key.replace("APIKey", "APISecret")
        return

    @property
    def _is_connected(self):
        response = self._execute_request("/fapi/v1/ping", "GET")
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
                self.add_log(msg, "warning")
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

    def _execute_request(self, endpoint: str, http_method: str, params=dict()):
        """This argument is used to send all types of requests to the server"""
        try:
            # Get the timestamp
            params["timestamp"] = int(time.time() * 1000)
            # Generate the signature for the query
            params["signature"] = self._generate_signature(urlencode(params))
            response = requests.request(
                method=http_method,
                url=self._base_url + endpoint,
                params=params,
                headers=self._header,
            )
            response.raise_for_status()
            return response
        except RequestException as e:
            self.add_log(f"Request error {e}", "warning")
        except Exception as e:
            self.add_log(f"Error {e}", "error")
        return None

    def _generate_signature(self, query_string: str):
        return hmac.new(
            key=os.getenv(self._api_secret).encode("utf-8"),
            msg=query_string.encode("utf-8"),
            digestmod=hashlib.sha256,
        ).hexdigest()

    # ###################### MARKET DATA FUNCTION #######################
    def _get_contracts(self):
        response = self._execute_request("/fapi/v1/exchangeInfo", "GET")
        if response:
            symbols = response.json()["symbols"]
            contracts = {
                symbol["symbol"]: Contract(symbol, self.exchange)
                for symbol in symbols
            }
            return contracts
        return None

    def get_candlestick(self, contract: Contract, interval: str):
        """
        Get a list of the historical Candlestickes for given contract.
        """
        params = {"symbol": contract.symbol, "interval": interval}
        response = self._execute_request("/fapi/v1/klines", "GET", params)
        if response:
            return [CandleStick(candle, self.exchange)
                    for candle in response.json()]
        return None

    def get_price(self, contract: Contract):
        """Get the latest traded price for the contract."""
        params = {"symbol": contract.symbol}
        response = self._execute_request(
            "/fapi/v1/ticker/bookTicker", "GET", params
            )
        if response:
            symbol = contract.symbol
            self.prices[symbol] = Price(response.json(), self.exchange)
            return self.prices[symbol]
        return None

    # ######################### TRADE Arguments ##########################
    def make_order(
        self, contract: Contract, *, side: str, order_type: str, **kwargs
    ):
        """
        Make a Buy/Long or Sell/Short order for a given contract.
        This argument is a private argument and can only be accesed
        within the connecter, when a buying or selling signal is found,
        or when canceling the runnning strategy
        """
        # Add the mandotary parameters
        params = {"symbol": contract.symbol, "side": side, "type": order_type}
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request("/fapi/v1/order", "POST", params)
        if response:
            return Order(response.json(), self.exchange)
        return None

    def order_status(self, order: Order):
        """Get information of a given order."""
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request("/fapi/v1/order", "GET", params)
        if response:
            return Order(response.json(), self.exchange)
        return None

    def delete_order(self, order: Order) -> Order:
        """
        Deleting an order. This argument is helpful for future trades,
        or when applying LIMIT/OCO orders."""
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request("/fapi/v1/order", "DELETE", params)
        if response:
            return Order(response.json(), self.exchange)
        return None

    # ######################### ACCOUNT Arguments ##########################
    @property
    def balance(self):
        """
        Return the amount of the currently holded assests in the wallet
        """
        response = self._execute_request("/fapi/v2/account", "GET")
        if response:
            balance = {
                asset["asset"]: Balance(asset, self.exchange)
                for asset in response.json()["assets"]
            }
            return balance
        return None

    @balance.setter
    def balance(self, *args, **kwargs):
        self.add_log("Balance can't be edited manually", "warning")
        return self.balance

    # ########################### Websocket Arguments ########################
    def new_subscribe(
        self, channel: Literal["tickers", "candles"], symbol, interval=""
    ):
        contract = self.contracts[symbol]
        if channel == "tickers":
            self._bookTicket_subscribe(contract)
        elif channel == "candles":
            self._kline_subscribe(contract, interval)

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
        running_contracts = set(
            map(lambda x: x.split("_")[0], self.strategy_counter.keys())
        )
        if symbol in running_contracts:
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
    def _ws_on_message(self, ws: websocket.WebSocketApp, msg):
        data = json.loads(msg)
        channel = data.get("e")
        symbol = data.get("s")
        if channel == "bookTicker":
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
            if symbol != strategy.symbol or hasattr(strategy, "order"):
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
            key = f'{symbol}_{data["i"]}'
            if hasattr(strategy, "order") and strategy.ws_channel_key == key:
                decision = strategy.parse_trade(sent_candle)
                self._process_dicision(strategy, decision)
            else:
                self._kline_unsubscribe(strategy)
        return

    def _process_dicision(self, strategy: "Strategy", decision: str):
        if decision == "buy or hodl" and not hasattr(strategy, "order"):
            latest_price = strategy.df["close"].iloc[-1]
            min_qty = 10 / latest_price
            base_asset = strategy.contract.quoteAsset
            balance = self.balance[base_asset].availableBalance
            buy_margin = balance * strategy.buy_pct
            quantity_margin = (buy_margin / latest_price) * 0.95
            quantity_margin = round(
                quantity_margin, strategy.contract.quantityPrecision
            )
            if quantity_margin > min_qty:
                order = self.make_order(
                    strategy.contract,
                    side="BUY",
                    order_type="MARKET",
                    quantity=quantity_margin,
                )
                if order:
                    order = self.order_status(order)
                    strategy.order = order
                    msg = (
                        f"{strategy.order.symbol} buying order was made. "
                        f"Quantity: {strategy.order.quantity}. "
                        f"Price: {strategy.order.price}"
                    )
                    self.add_log(msg, "info")
            else:
                msg = (
                    f"could not buy {self.strategy.contract.symbol}"
                    "because the ordered quantity is less than the"
                    "minimum margin. Strategy is removed"
                )
                self.add_log(msg, "info")
                self._kline_unsubscribe(strategy)
        elif decision == "sell or don't enter" and hasattr(strategy, "order"):
            # sell when there is an existing order and poor indicators
            self._sell_strategy_asset(strategy)
        return

    def _sell_strategy_asset(self, strategy):
        sell_order = self.make_order(
            contract=self.strategy.contract,
            side="SELL",
            order_type="MARKET",
            quantity=strategy.order.quantity,
        )
        if sell_order:
            while sell_order.status != "FILLED":
                sell_order = self.order_status(sell_order)
                time.sleep(2)
            strategy.relaizedPnL += strategy._PnLcalciator(sell_order)
            strategy.order = sell_order
            self._kline_unsubscribe(strategy)
        return
