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
    def __init__(self, is_spot: bool, is_test: bool):
        self.exchange = "Binance"
        
        self._init(is_spot, is_test)
        self._header = {"X-MBX-APIKEY": os.getenv(self._api_key),
                        "Content-Type": "application/json"}
        
        self._http_dict = {"GET": requests.get,
                           "POST": requests.post,
                           "DELETE": requests.delete}
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
        self.running_startegies: Set[Strategy] = set()
        self.strategy_counter: Dict[str, Dict[str, int]] = dict()
        """
        when a new strategyy added, the counter will increase, and when strategy is executed/canceled, counter will go down. 
        Once counter reach Zero, unsubscribe the aggTrade channel. The first key is the symbol, and the item is another dictionary.
        For the 2nd dict, the keys are the counter 'count' and the 'id' for the web socket
        """
        self._reconnect = True
        t = Thread(target=self._start_ws)
        t.start()
        
    def _init(self, is_spot: bool, is_test: bool):
        # Spot Trading
        # Test Net
        if is_spot and is_test:
            self._base_url = 'https://testnet.binance.vision/api'
            self._ws_url = 'wss://testnet.binance.vision/ws'
        # Real Spot trading
        elif is_spot and not is_test:
            self._base_url = 'https://api.binance.com/api'
            self._ws_url = 'wss://stream.binance.com:9443/ws'
        
        # Future Trading
        # Test net
        elif not is_spot and is_test:
            self._base_url = 'https://testnet.binancefuture.com'
            self._ws_url = 'wss://stream.binancefuture.com/ws'
        # Real Future
        elif not is_spot and not is_test:
            self._base_url = 'https://fapi.binance.com'
            self._ws_url = 'wss://fstream.binance.com/ws'
            
        self._api_key = f"Binance{'Spot' if is_spot else 'Future'}{'Test' if is_test else ''}APIKey"
        self._api_secret = self._api_key.replace('APIKey', 'APISecret')     
    
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
            os.getenv(self._api_secret).encode("utf-8"),
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
            symbol = data["s"]
            if data["e"] == "bookTicker": # Used to track a trading pairs and calculate PnL
                """
                bookTicker message is pushed when either of the bid or ask changes. 
                Subscribe to the bookTicker to track a contract pair, or when starting new strategy
                """
                # If new untracked symbol
                if symbol not in self.prices.keys():
                    self.prices[symbol] = self.get_price(self.contracts[symbol])
                # Update ask/bid prices
                self.prices[symbol].bid = data["b"]
                self.prices[symbol].ask = data["a"]
                
                for strategy in self.running_startegies:
                    if symbol == strategy.contract.symbol and strategy.had_assits:
                        # Calculate the uPnL only when an order is made
                        self._check_tp_sl(strategy)
                        break
            
            elif data["e"] == "aggTrade": # Used to update indicators and make trading decision
                """
                AggTrade message is send when a trade is made. 
                Subscribe to this channel when starting new strategy, and cancel the subscribtion once the strategy is stopped.
                """
                trade_price = float(data['p'])
                volume = float(data['q'])
                timestamp = int(data['t'])
                
                for strategy in self.running_startegies:
                    if strategy.is_running:
                        if symbol==strategy.contract.symbol:
                            decision = strategy.parse_trade(trade_price, volume, timestamp)
                            self._process_dicision(strategy, decision, latest_price=trade_price)
                            break
                    else:
                        self.unsubscribe_channel(symbol, 'aggTrade', strategy)

    def _check_tp_sl(self, strategy: 'Strategy'):
        buying_price = strategy.order.price
        pnl = (1 - self.prices[strategy.contract.symbol].ask / buying_price) * 100
        # Take Profit or Stop Loss check
        if pnl > 0 and pnl >= strategy.tp:
            self._take_profit(strategy)
        elif pnl < 0 and abs(pnl)>= strategy.sl:
            self._stop_loss(strategy)
                
    def _on_error(self, ws: websocket.WebSocketApp, error):
        print(f"Error: {error}")

    def _on_close(self, ws: websocket.WebSocketApp):
        print("Websoccet disconnect")

    def _stop_loss(self, strategy: 'Strategy'):
        sell_order = self._make_order(self.contracts[strategy.contract.symbol], 'SELL',
                                      order_type='MARKET', quantity=strategy.order.quantity)
        if sell_order:
            strategy.had_assits = False
            strategy.relaizedPnL -= (strategy.order.quantity * strategy.order.price) - (sell_order.quantity * sell_order.price)
            self.order = sell_order
            
    def _take_profit(self, strategy: 'Strategy'):
        sell_order = self._make_order(self.contracts[strategy.contract.symbol], 'SELL',
                                      order_type='MARKET', quantity=strategy.order.quantity/2)
        if sell_order:
            strategy.relaizedPnL += (sell_order.quantity * sell_order.price) - (strategy.order.quantity * strategy.order.price)
            strategy.order = sell_order       
    
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
            if symbol not in self.strategy_counter.keys():
                msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
                # Subscribe to the websocket channel
                self.ws.send(json.dumps(msg))
                self.strategy_counter[symbol] = {'count': 1, 'id': self.id}
                # Update the aggTrade list from the strategy object
                self.id += 1

    def unsubscribe_channel(self, symbol: str, channel="bookTicker", strategy: Union[None,'Strategy']= None):
        params = [f"{symbol.lower()}@{channel}"]
        
        if channel == "bookTicker":
            _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
            msg = {"method": "UNSUBSCRIBE", 
                   "params": params, "id": _id}
            self.ws.send(json.dumps(msg))
            self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
            self.prices.pop(symbol)
        
        elif channel == "aggTrade":
            self.strategy_counter[symbol]['count'] -= 1
            if self.strategy_counter[symbol]['count'] == 0:
                msg = {"method": "UNSUBSCRIBE", "params": params,
                       "id": self.strategy_counter[symbol]['id']}
                self.ws.send(json.dumps(msg))
                self.strategy_counter.pop(symbol)
                self.running_startegies.pop(strategy)

    def _process_dicision(self, strategy: 'Strategy', decision: str, latest_price: float):
        if 'buy' in decision.lower and not strategy.had_assits:
            # Binance don't allow less than 10$ transaction
            min_qty_margin = max(10/latest_price, strategy.contract.minQuantity)
            base_asset = strategy.contract.quoteAsset # USDT or BUSD, etc..
            balance = self.balance[base_asset] # get the balance information 
            
            buy_margin = balance.availableBalance * strategy.buy_pct # Calculate the desired money for trade
            
             # calculate order quantity and apply 5% negative slippage
            quantity_margin = round((buy_margin/latest_price)*0.95 ,strategy.contract.quantityPrecision) # 
            
            if quantity_margin > min_qty_margin:
                strategy.order = self._make_order(strategy.contract, order_side='BUY',
                                                  order_type='MARKET', quantity=quantity_margin)
                if strategy.order:
                    strategy.had_assits = True
                    print(f"{strategy.order.symbol} buying order was made. Quantity: {strategy.order.quantity}. Price: {strategy.order.price}")
                # Update Dashboard to start tracking running orders
            else:
                print(f"{self.strategy.contract.symbol} buying option could not be made because the ordered quantity is less than the minimum margin")
        
        elif 'sell' in decision.lower() and strategy.had_assits:
                # If there is an existing order and indicators are not good, SELL
                sell_order = self._make_order(strategy.contract, order_side='SELL',
                                              order_type='MARKET', quantity=strategy.order.quantity)
                if sell_order:
                    strategy.relaizedPnL -= (strategy.order.quantity * strategy.order.price) - (sell_order.quantity * sell_order.price)
                    strategy.order = sell_order
                    strategy.had_assits = False