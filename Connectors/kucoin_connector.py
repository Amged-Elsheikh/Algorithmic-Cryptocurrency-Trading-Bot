import base64
import hashlib
import hmac
import json
import logging
import logging.config
import os
import random
import string
import time
from typing import TYPE_CHECKING, Dict, Union, Literal

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


class KucoinClient(CryptoExchange):
    _loaded = dict()

    def __new__(cls, is_spot: bool, is_test: bool):
        if (client := cls._loaded.get(f"{is_spot} {is_test}")) is None:
            client = super().__new__(cls)
            cls._loaded[f"{is_spot} {is_test}"] = client
        return client

    def __init__(self, is_spot: bool, is_test: bool):
        self._init(is_spot, is_test)
        self.logger = logging.getLogger(__name__)
        super().__init__()
        self._check_internet_connection()
        self.contracts = self._get_contracts()
        self.prices: Dict[str, Price] = dict()

    def _init(self, is_spot: bool, is_test: bool):
        urls = {
            (True, True): ("https://openapi-sandbox.kucoin.com"),
            (True, False): ("https://api.kucoin.com"),
            (False, True): ("https://api-sandbox-futures.kucoin.com"),
            (False, False): ("https://api-futures.kucoin.com"),
        }
        self._base_url = urls[(is_spot, is_test)]
        spot_future = "Spot" if is_spot else "Future"
        real_test = "Test" if is_test else ""
        self._api_key = f"{self.exchange}{spot_future}{real_test}APIKey"
        self._api_secret = self._api_key.replace("APIKey", "APISecret")
        self._passphrase = self._generate_signature(
            os.getenv(self._api_key.replace("APIKey", "Passphrase"))
        )
        return

    @property
    def _is_connected(self):
        response = self._execute_request("/api/v1/timestamp", "GET")
        try:
            response.raise_for_status()
            return True
        except Exception:
            return False

    def _check_internet_connection(self):
        connection_flag = 0
        while not self._is_connected:
            if connection_flag < 5:
                connection_flag += 1
                time.sleep(3)
            else:
                msg = f"{self.exchange} Client failed to connect"
                self.add_log(msg, "warning")
                raise Exception(msg)
        msg = "Internet connection established"
        self.add_log(msg, "info")
        return True

    @property
    def exchange(self):
        return "Kucoin"

    def _execute_request(self, endpoint: str, http_method: str, params=dict()):
        """This argument is used to send all types of requests to the server"""
        try:
            now = str(int(time.time() * 1000))
            data_json = json.dumps(params) if params else ""
            signature = now + http_method + endpoint + data_json
            _header = {
                "KC-API-KEY": os.getenv(self._api_key),
                "KC-API-SIGN": self._generate_signature(signature),
                "KC-API-TIMESTAMP": now,
                "KC-API-PASSPHRASE": self._passphrase,
                "KC-API-KEY-VERSION": "2",
                "Content-Type": "application/json",
            }
            # Generate the signature for the query
            if http_method in ["GET", "DELETE"]:
                response = requests.request(
                    method=http_method,
                    url=self._base_url + endpoint,
                    params=params,
                    headers=_header,
                )
            elif http_method in ["POST", "PUT"]:
                response = requests.request(
                    method=http_method,
                    url=self._base_url + endpoint,
                    data=data_json,
                    headers=_header,
                )
            response.raise_for_status()
            return response
        except RequestException as e:
            self.add_log(f"Request error {e}", "warning")
        except Exception as e:
            self.add_log(f"Error {e}", "error")
        return None

    def _generate_signature(self, query_string: str):
        return base64.b64encode(
            hmac.new(
                key=os.getenv(self._api_secret).encode("utf-8"),
                msg=query_string.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
        )

    # ###################### MARKET DATA FUNCTION #######################
    def _get_contracts(self) -> Dict[str, Contract] | None:
        response = self._execute_request("/api/v2/symbols", "GET")
        if response:
            symbols = response.json()["data"]
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
        params = {"symbol": contract.symbol, "type": interval}
        response = self._execute_request(
            "/api/v1/market/candles", "GET", params
            )
        if response:
            return [
                CandleStick(candle, self.exchange)
                for candle in response.json()["data"][::-1]
            ]
        return None

    def get_price(self, contract: Contract):
        symbol = contract.symbol
        params = {"symbol": symbol}
        response = self._execute_request(
            "/api/v1/market/orderbook/level1", "GET", params
        )
        if response:
            self.prices[symbol] = Price(response.json()["data"], self.exchange)
            self.prices[symbol].symbol = symbol
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
        params = {
            "clientOid": self._generate_client_order_id(),
            "symbol": contract.symbol,
            "side": side.lower(),
            "type": order_type.lower(),
        }
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request("/api/v1/orders", "POST", params)
        if response:
            return self.order_status(response.json()["data"]["orderId"])
        return None

    def order_status(self, order: Union[Order, str]):
        order_id = order.orderId if isinstance(order, Order) else order
        response = self._execute_request(f"/api/v1/orders/{order_id}", "GET")
        if response:
            return Order(response.json()["data"], self.exchange)
        return None

    def delete_order(self, order: Union[Order, str]) -> Order:
        """
        Deleting an order. This argument is helpful for future trades,
        or when applying LIMIT/OCO orders."""
        _id = order.orderId if isinstance(order, Order) else order
        response = self._execute_request(f"/api/v1/orders/{_id}", "DELETE")
        if response:
            return Order(response.json()["data"], self.exchange)
        return None

    # ######################### ACCOUNT Arguments ##########################
    @property
    def balance(self) -> Dict[str, Balance] | None:
        """
        Return the amount of the currently holded assests in the wallet
        """
        response = self._execute_request("/api/v1/accounts", "GET")
        if response:
            balance = {
                asset["currency"]: Balance(asset, self.exchange)
                for asset in response.json()["data"]
                if asset["type"] == "trade"
            }
            return balance
        return None

    @balance.setter
    def balance(self, *args, **kwargs):
        self.add_log("Balance can't be edited manually", "warning")
        return self.balance

    # ########################### Websocket Arguments ########################
    def _start_ws(self):
        # Reopen the websocket connection if it terminated
        ws_init = None
        while ws_init is None:
            ws_init = self._execute_request("/api/v1/bullet-public", "POST")
            if ws_init is None:
                time.sleep(3)
        token = ws_init.json()["data"]["token"]
        ws_url = ws_init.json()["data"]["instanceServers"][0]["endpoint"]
        self._ws_url = f"{ws_url}?token={token}&connectId={int(time.time())}"
        self._ws = websocket.WebSocketApp(
            url=self._ws_url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._ws_on_message,
        )
        while True:
            try:
                if self._ws_connect:
                    # Reconnect unless the interface is closed by the user
                    self._ws.run_forever()
                else:
                    break
            except Exception as e:
                # Update the log about this error
                msg = f"{self.exchange} error in run_forever() method: {e}"
                self.add_log(msg, "warning")
            # Add sleeping interval
            time.sleep(3)

    def new_subscribe(
        self,
        channel: Literal["tickers", "candles"],
        symbol: str,
        interval: str = None,
    ):
        contract = self.contracts[symbol]
        if channel == "tickers":
            self._bookTicket_subscribe(contract)
        elif channel == "candles":
            self._kline_subscribe(contract, interval)

    def _bookTicket_subscribe(self, contract: Contract):
        channel = f"/ticker:{contract.symbol}"
        if contract in self.bookTicker_subscribtion_list:
            self.add_log(f"Already subscribed to {channel}", "info")
            return
        msg = {
            "id": self.id,
            "type": "subscribe",
            "topic": channel,
            "privateChannel": False,
            "response": False,
        }
        # Subscribe to the websocket channel
        self.get_price(contract)
        self._ws.send(json.dumps(msg))
        self.bookTicker_subscribtion_list[contract] = self.id
        self.id += 1
        return

    def _kline_subscribe(self, contract: Contract, interval: str):
        # Make sure the contract is in the bookTicker.
        symbol = contract.symbol
        strategy_key = f"{symbol}_{interval}"
        channel = f"/market/candles:{strategy_key}"
        if contract not in self.bookTicker_subscribtion_list:
            self._bookTicket_subscribe(contract)
        if strategy_key in self.strategy_counter:
            self.strategy_counter[strategy_key]["count"] += 1
            self.add_log(f"Already subscribed to {channel}", "info")
            return
        msg = {
            "id": self.id,
            "type": "subscribe",
            "topic": channel,
            "privateChannel": False,
            "response": False,
        }

        # Subscribe to the websocket channel
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
        if channel == "candles":
            self._kline_unsubscribe(strategy)
        elif channel == "tickers":
            running_contracts = list(
                map(lambda x: x.split("_")[0], self.strategy_counter.keys())
            )
            if symbol in running_contracts:
                msg = (
                    f"{symbol} had a running strategy and "
                    "can't be removed from the watchlist"
                )
                self.add_log(msg, "info")
                return
            self._bookTicker_unsubscribe(symbol)
        return

    def _bookTicker_unsubscribe(self, symbol: str):
        _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
        channel = f"/market/ticker:{symbol}"
        msg = {
            "id": _id,
            "type": "unsubscribe",
            "topic": channel,
            "privateChannel": False,
            "response": False,
        }
        self._ws.send(json.dumps(msg))
        self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
        self.prices.pop(symbol)
        return

    def _kline_unsubscribe(self, strategy: "Strategy"):
        counters_key = strategy.ws_channel_key
        self.running_startegies.pop(strategy.strategy_key)
        self.strategy_counter[counters_key]["count"] -= 1
        if self.strategy_counter[counters_key]["count"] == 0:
            channel = f"/market/candles:{strategy.symbol}_{strategy.interval}"
            msg = {
                "id": self.strategy_counter[counters_key]["id"],
                "type": "unsubscribe",
                "topic": channel,
                "privateChannel": False,
                "response": False,
            }
            self._ws.send(json.dumps(msg))
            self.strategy_counter.pop(counters_key)
        return

    # ########################### Strategy Arguments ##########################
    def _ws_on_message(self, ws: websocket.WebSocketApp, msg):
        """
        This is the argument that will form most of the connections between
        the backend and frontend by automating trades and send data to the UI
        """
        # Read the received message
        data = json.loads(msg)
        if "type" in data and data["type"] == "welcome":
            return
        channel = data["subject"]
        symbol = data["topic"].split(":")[-1]
        if channel == "trade.ticker":
            self._bookTickerMsg(data["data"], symbol)
        elif channel == "trade.candles.update":
            self._klineMsg(data, symbol)
        else:
            return

    def _bookTickerMsg(self, data, symbol):
        """
        bookTicker message is pushed when either one of the bid or ask changes.
        Used to track a trading pairs and calculate unrealized PnL.
        Subscribe to the bookTicker to track a contract pair,
        or when starting new strategy.
        """
        # Update ask/bid prices
        self.prices[symbol].bid = float(data["bestBid"])
        self.prices[symbol].ask = float(data["bestAsk"])
        # Check the status of the order for each running strategy
        for strategy in self.running_startegies.values():
            if symbol == strategy.symbol and hasattr(strategy, "order"):
                if strategy.order.status in ["new", "partially_filled"]:
                    strategy.order = self.order_status(strategy.order)
                elif strategy.order.status == "canceled":
                    self._kline_unsubscribe(strategy)
                    continue
                if strategy.order.status == "filled":
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
        interval = data["topic"].split("_")[-1]
        sent_candle = CandleStick(data["data"]["candles"], self.exchange)
        for strategy in self.running_startegies.values():
            if hasattr(strategy, "order"):
                if [strategy.symbol, strategy.interval] == [symbol, interval]:
                    decision = strategy.parse_trade(sent_candle)
                    self._process_dicision(strategy, decision)
            else:
                self._kline_unsubscribe(strategy)
        return

    def _process_dicision(self, strategy: "Strategy", decision: str):
        if decision == "buy or hodl" and hasattr(strategy, "order"):
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
                    side="buy",
                    order_type="market",
                    size=quantity_margin,
                )
                if order:
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
                    "minimum margin"
                )
                self.add_log(msg, "info")
        elif decision == "sell or don't enter" and hasattr(strategy, "order"):
            self._sell_strategy_asset(strategy)
        return

    def _sell_strategy_asset(self, strategy):
        sell_order = self.make_order(
            contract=self.strategy.contract,
            side="sell",
            order_type="market",
            size=strategy.order.quantity,
        )
        if sell_order:
            while sell_order.status != "filled":
                sell_order = self.order_status(sell_order)
                # time.sleep(2)
            strategy.relaizedPnL += strategy._PnLcalciator(sell_order)
            strategy.order = sell_order
            self._kline_unsubscribe(strategy)
        return

    def _generate_client_order_id(self):
        letters = string.ascii_letters + string.digits + string.punctuation
        random_string = "".join(random.choice(letters) for _ in range(20))
        return random_string
