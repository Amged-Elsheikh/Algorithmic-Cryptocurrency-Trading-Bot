import asyncio
import logging
import hashlib
import json
import hmac
import os
import time
from typing import *
from urllib.parse import urlencode
from threading import Thread

import requests
import websocket
from dotenv import load_dotenv
from requests.exceptions import RequestException

from Moduls.data_modul import *

if TYPE_CHECKING:
    from strategies import Strategy

load_dotenv()


class BinanceClient:
    def __init__(self):
        self.exchange = "Binance"
        self._base_url = "https://testnet.binancefuture.com"
        self._ws_url = "wss://stream.binancefuture.com/ws"
        self._header = {
            "X-MBX-APIKEY": os.getenv("BinanceFutureTestAPIKey"),
            "Content-Type": "application/json",
        }

        self._http_dict = {
            "GET": requests.get,
            "POST": requests.post,
            "DELETE": requests.delete,
        }
        self.logger = logging.getLogger("log_module")

        # Check internet connection

        connection_flag = 0
        while not self._is_connected():
            if connection_flag >= 5:
                msg = "Binance Client failed to connect"
                self.logger.warning(msg)
                raise Exception(msg)
            else:
                flag += 1
                time.sleep(3)

        self.logger.info("Client connected Successfuly")
        self.contracts = self._get_contracts()
        self.prices: Dict[str, Price] = dict()

        # Websocket connection
        self.id = 1
        self.bookTicker_subscribtion_list: Dict[Contract, int] = dict()
        # running_startegies key: "symbol_id", value: strategy object
        self.running_startegies: Dict[str, Strategy] = dict()
        
        self._reconnect = True
        t = Thread(target=self._start_ws)
        t.start()

    def _execute_request(self, endpoint: str, params: Dict, http_method: str):
        try:
            # Get the timestamp
            params["timestamp"] = int(time.time() * 1000)
            # Generate the signature for the query
            params["signature"] = self._generate_signature(urlencode(params))

            response = self._http_dict[http_method](
                self._base_url + endpoint, params=params, headers=self._header
            )
            response.raise_for_status()
            return response

        except RequestException as e:
            print(f"Request error {e}")
        except Exception as e:
            print(f"Error: {e}")
        return False

    def _generate_signature(self, query_string: str):
        return hmac.new(
            os.getenv("BinanceFutureTestAPISecret").encode("utf-8"),
            query_string.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _is_connected(self, print_status=False):
        response = self._execute_request(
            endpoint="/fapi/v1/ping", params={}, http_method="GET"
        )
        if response:
            return True
        else:
            return False

    ####################### MARKET DATA FUNCTION #######################
    def _get_contracts(self) -> Dict[str, Contract] | None:
        response = self._execute_request(
            endpoint="/fapi/v1/exchangeInfo", params={}, http_method="GET"
        )
        if response:
            data = response.json()["symbols"]
            contracts = {
                symbol["symbol"]: Contract(symbol, exchange=self.exchange)
                for symbol in data
            }
            return contracts
        return None

    def get_candlestick(self, contract: Contract, interval="4h") -> List[CandleStick]:
        params = {"symbol": contract.symbol, "interval": interval}
        response = self._execute_request(
            endpoint="/fapi/v1/klines", params=params, http_method="GET"
        )
        if response:
            return [CandleStick(candle, self.exchange) for candle in response.json()]
        return None

    def get_price(self, contract: Contract) -> Price | None:
        response = self._execute_request(
            endpoint="/fapi/v1/ticker/bookTicker",
            params={"symbol": contract.symbol},
            http_method="GET",
        )
        if response:
            self.prices[contract.symbol] = Price(response.json(), self.exchange)
            price = self.prices[contract.symbol]
            return price
        return None

    ########################## TRADE FUNCTION ##########################
    def _make_order(
        self, contract: Contract, order_side: str, order_type: str, **kwargs
    ) -> Order | None:
        # Add the mandotary parameters
        params = {"symbol": contract.symbol, "side": order_side, "type": order_type}
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request(
            endpoint="/fapi/v1/order", params=params, http_method="POST"
        )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def order_status(self, order: Order) -> Order:
        params = {"symbol": order.symbol, "orderId": order.orderId}

        response = self._execute_request(
            endpoint="/fapi/v1/order", params=params, http_method="GET"
        )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def delete_order(self, order: Order) -> Order:
        params = {"symbol": order.symbol, "orderId": order.orderId}

        response = self._execute_request(
            endpoint="/fapi/v1/order", params=params, http_method="DELETE"
        )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    ########################## ACCOUNT ##########################
    @property
    def balance(self) -> Dict[str, Balance] | None:
        endpoint = "/fapi/v2/account"
        response = self._execute_request(endpoint, http_method='GET', params={})
        if response:
            balance: Dict[str, Balance]
            data = response.json()["assets"]
            balance = {asset["asset"]: Balance(asset, "Binance") for asset in data}
            return balance
        return None

    @balance.setter
    def balance(self, *args, **kwargs):
        print("Balance can't be edited manually")
        return self.balance

    ############################ Websocket ############################
    def _start_ws(self):
        self.ws = websocket.WebSocketApp(
            self._ws_url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        # Reopen the websocket connection if it terminated
        while True:
            try:
                if (
                    self._reconnect
                ):  # Reconnect unless the interface is closed by the user
                    self.ws.run_forever()  # Blocking method that ends only if the websocket connection drops
                else:
                    break
            except Exception as e:
                # Update the log about this error
                print("Binance error in run_forever() method: %s", e)
            # Add sleeping interval
            time.sleep(3)

    def _on_open(self, ws: websocket.WebSocketApp):
        print("Websocket connected")

    def _on_message(self, ws: websocket.WebSocketApp, msg):
        data = json.loads(msg)
        if "e" in data.keys():
            if data["e"] == "bookTicker":
                """bookTicker message is pushed when either of the bid or ask changes"""
                symbol = data["s"]
                # If new untracked symbol
                if symbol not in self.prices.keys():
                    self.prices[symbol] = self.get_price(self.contracts[symbol])
                # Update ask/bid prices
                self.prices[symbol].bid = data["b"]
                self.prices[symbol].ask = data["a"]

                if symbol in self.current_strategies.keys():
                    self.current_strategies[symbol] = self.prices[symbol]

            elif data["e"] == "aggTrade":
                """AggTrade message is send when a trade is made"""
                symbol = data["s"]
                for symbol_id, strategy in self.running_startegies.items():
                    if strategy.is_running:
                        if symbol==symbol_id.split("_")[0]:
                            decision = strategy.parse_trade()
                            self._process_dicision(strategy, decision, latest_price=float(data['p']))
                    else:
                        self.running_startegies.pop(symbol_id)

    def _on_error(self, ws: websocket.WebSocketApp, error):
        print(f"Error: {error}")

    def _on_close(self, ws: websocket.WebSocketApp):
        print("Websoccet disconnect")

    def new_subscribe(self, symbol="BTCUSDT", channel="bookTicker"):
        params = f"{symbol.lower()}@{channel}"
        if channel == "bookTicker":
            if self.contracts[symbol] in self.bookTicker_subscribtion_list:
                print(f"Already subscribed to {params} channel")
            else:
                msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
                # immediatly show current bid and ask prices.
                self.get_price(self.contracts[symbol])
                # Subscribe to the websocket channel
                self.ws.send(json.dumps(msg))

                self.bookTicker_subscribtion_list[self.contracts[symbol]] = self.id
                self.id += 1

        elif channel == "aggTrade":
            msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
            # Subscribe to the websocket channel
            self.ws.send(json.dumps(msg))
            # Update the aggTrade list from the strategy object
            self.id += 1

    def unsubscribe_channel(self, symbol: str, channel="bookTicker"):
        params = [f"{symbol.lower()}@{channel}"]
        if channel == "bookTicker":
            _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
            msg = {"method": "UNSUBSCRIBE", 
                   "params": params, "id": _id}
            self.ws.send(json.dumps(msg))
            self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
            self.prices.pop(symbol)
        
        elif channel == "aggTrade":
            pass

    def _process_dicision(self, strategy: Strategy, decision:str, latest_price: float):
        if decision == "buy or hodl":
            if strategy.order is None:
                # Binance don't allow less than 10$ transaction
                min_qty_margin = max(10/latest_price, strategy.contract.minQuantity)
                base_asset = strategy.contract.quoteAsset
                balance = self.balance[base_asset]
                
                buy_margin = balance.availableBalance * strategy.buy_pct
                quantity_margin = round(buy_margin/latest_price, strategy.contract.quantityPrecision)
                
                if quantity_margin > min_qty_margin:
                    strategy.order = self._make_order(strategy.contract, order_side='BUY',
                                                      order_type='MARKET', quantity=quantity_margin)
                else:
                    print(f"{self.strategy.contract.symbol} buying option could not be made because the ordered quantity is less than the minimum margin")