import hashlib
import hmac
import json
import logging
import logging.config
import os
import time
from collections import defaultdict
from threading import Thread
from typing import TYPE_CHECKING, Dict, List, Set, Union
from urllib.parse import urlencode

import requests
import websocket
from dotenv import load_dotenv
from requests.exceptions import RequestException
from requests.models import Response

from Moduls.data_modul import Balance, CandleStick, Contract, Order, Price

if TYPE_CHECKING:
    from strategies import Strategy

load_dotenv()


class BinanceClient:
    _loaded = {}
    
    def __new__(cls, is_spot: bool, is_test: bool):
        if (client := cls._loaded.get(f"{is_spot} {is_test}")) is None:
            client = super().__new__(cls)
            cls._loaded[f"{is_spot} {is_test}"] = client
        return client
        
    def __init__(self, is_spot: bool, is_test: bool):
        self._init(is_spot, is_test)
        self._header = {"X-MBX-APIKEY": os.getenv(self._api_key),
                        "Content-Type": "application/json"}
        
        self._http_dict = {"GET": requests.get,
                           "POST": requests.post,
                           "DELETE": requests.delete}
        logging.config.fileConfig("logger.config")
        self.logger = logging.getLogger(__name__)
        # Check internet connection
        self._check_internet_connection()
        self.logger.info("Internet connection established")
        self.contracts = self._get_contracts()
        self.prices = defaultdict(Price)

        # Websocket connection
        self._ws_connect = False
        self.id = 1
        self.bookTicker_subscribtion_list: Dict[Contract, int] = dict()
        # running_startegies key: "symbol_id", value: strategy object
        self.running_startegies: Set[Strategy] = set()
        """Can't a dictionary, because a single contract can have multiple running strategies"""
        self.strategy_counter: Dict[str, Dict[str, int]] = dict()
        """
        when a new strategyy added, the counter will increase, and when strategy is executed/canceled, counter will go down. 
        Once counter reach Zero, unsubscribe the aggTrade channel. The first key is the symbol, and the item is another dictionary.
        For the 2nd dict, the keys are the counter 'count' and the 'id' for the web socket
        """
        
    def run(self):
        self._ws_connect = True
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
        
    @property
    def _is_connected(self):
        response = self._execute_request(endpoint="/fapi/v1/ping", params={}, http_method="GET")
        if response:
            return True
        else:
            return False
        
    def _check_internet_connection(self):
        connection_flag = 0
        while not self._is_connected:
            if connection_flag >= 5:
                msg = "Binance Client failed to connect"
                self.logger.warning(msg)
                raise Exception(msg)
            else:
                connection_flag += 1
                time.sleep(3)
        return True
        
    @property
    def exchange(self):
        return 'Binance'
    
    def _execute_request(self, endpoint: str, params: Dict, http_method: str) -> Response | None:
        """This argument is used to send all types of requests to the server"""
        try:
            # Get the timestamp
            params["timestamp"] = int(time.time() * 1000)
            # Generate the signature for the query
            params["signature"] = self._generate_signature(urlencode(params))

            response = self._http_dict[http_method](self._base_url + endpoint,
                                                    params=params, headers=self._header)
            response.raise_for_status()
            return response
        except RequestException as e:
            self.logger.warning(f"Request error {e}")
        except Exception as e:
            self.logger.error(f"Error: {e}")
        return None

    def _generate_signature(self, query_string: str):
        return hmac.new(os.getenv(self._api_secret).encode("utf-8"),
                        query_string.encode("utf-8"),
                        hashlib.sha256).hexdigest()

    ####################### MARKET DATA FUNCTION #######################
    def _get_contracts(self) -> Dict[str, Contract] | None:
        """Return all exchange contracts."""
        response = self._execute_request(endpoint="/fapi/v1/exchangeInfo",
                                         params={}, http_method="GET")
        if response:
            symbols = response.json()["symbols"]
            contracts = {symbol["symbol"]: Contract(symbol, exchange=self.exchange)
                         for symbol in symbols}
            return contracts
        return None

    def get_candlestick(self, contract: Contract, interval="4h") -> List[CandleStick] | None:
        """Get a list of the historical Candlestickes for given contract."""
        params = {"symbol": contract.symbol, "interval": interval}
        response = self._execute_request(endpoint="/fapi/v1/klines",
                                         params=params, http_method="GET")
        if response:
            return [CandleStick(candle, self.exchange) for candle in response.json()]
        return None

    def get_price(self, contract: Contract) -> Price | None:
        """Get the latest traded price for the contract."""
        response = self._execute_request(endpoint="/fapi/v1/ticker/bookTicker",
                                         params={"symbol": contract.symbol},
                                         http_method="GET")
        if response:
            self.prices[contract.symbol] = Price(response.json(), self.exchange)
            price = self.prices[contract.symbol]
            return price
        return None

    ########################## TRADE Arguments ##########################
    def _make_order(self, contract: Contract, order_side: str, order_type: str, **kwargs) -> Order | None:
        """Make a Buy/Long or Sell/Short order for a given contract. 
        This argument is a private argument and can only be accesed within the connecter,
        when a buying or selling signal is found, or when canceling the runnning strategy"""
        # Add the mandotary parameters
        params = {"symbol": contract.symbol, "side": order_side, "type": order_type}
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request(endpoint="/fapi/v1/order",
                                         params=params, http_method="POST")
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def order_status(self, order: Order) -> Order | None:
        """Get information of a given order."""
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request(endpoint="/fapi/v1/order",
                                         params=params, http_method="GET")
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def delete_order(self, order: Order) -> Order:
        """Deleting an order. This argument is helpful for future trades, or when applying LIMIT/OCO orders."""
        params = {"symbol": order.symbol, "orderId": order.orderId}
        response = self._execute_request(endpoint="/fapi/v1/order",
                                         params=params, http_method="DELETE")
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    ########################## ACCOUNT Arguments ##########################
    @property
    def balance(self) -> Dict[str, Balance] | None:
        """Return the amount of the currently holded assests in the wallet"""
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
        self.logger.warning("Balance can't be edited manually")
        return self.balance

    ############################ Websocket Arguments ############################
    def _start_ws(self):
        self._ws = websocket.WebSocketApp(self._ws_url, 
                                          on_open=self._on_open, on_close=self._on_close,
                                          on_error=self._on_error, on_message=self._on_message)
        # Reopen the websocket connection if it terminated
        while True:
            try:
                if (self._ws_connect): 
                    # Reconnect unless the interface is closed by the user
                    self._ws.run_forever()  # Blocking method that ends only if the websocket connection drops
                else:
                    break
            except Exception as e:
                # Update the log about this error
                self.logger.warning("Binance error in run_forever() method: %s", e)
            # Add sleeping interval
            time.sleep(3)

    def _on_open(self, ws: websocket.WebSocketApp):
        self.logger.info("Websocket connected")
                
    def _on_error(self, ws: websocket.WebSocketApp, error):
        self.logger.error(f"Error: {error}")

    def _on_close(self, ws: websocket.WebSocketApp):
        self._ws_connect = False
        self.logger.info("Websocket disconnect")
        
    def _on_message(self, ws: websocket.WebSocketApp, msg):
        """This is the argument that will form most of the connections between the backend and frontend 
        by automating trades and send data to the UI"""
        # Read the received message
        data = json.loads(msg)
        if "e" in data.keys():
            symbol = data["s"]
            if data["e"] == "bookTicker":
                self._bookTickerMsg(data, symbol)
            
            elif data["e"] == "aggTrade":
                self._aggTradeMsg(data, symbol)

    def new_subscribe(self, symbol="BTCUSDT", channel="bookTicker"):
        params = f"{symbol.lower()}@{channel}"
        if channel == "bookTicker":
            if self.contracts[symbol] in self.bookTicker_subscribtion_list:
                self.logger.info(f"Already subscribed to {params} channel")
            else:
                msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
                # immediatly show current bid and ask prices.
                self.get_price(self.contracts[symbol])
                # Subscribe to the websocket channel
                self._ws.send(json.dumps(msg))
                self.bookTicker_subscribtion_list[self.contracts[symbol]] = self.id
                self.id += 1

        elif channel == "aggTrade":
            # when starting new strategy, make sure the contract is in the bookTicker as well
            if self.contracts[symbol] not in self.bookTicker_subscribtion_list:
                self.new_subscribe(symbol, "bookTicker")
            if symbol in self.strategy_counter.keys():
                self.logger.info(f"Already subscribed to {params} channel")
            else:
                msg = {"method": "SUBSCRIBE", "params": [params], "id": self.id}
                # Subscribe to the websocket channel
                self._ws.send(json.dumps(msg))
                self.strategy_counter[symbol] = {'count': 1, 'id': self.id}
                # Update the aggTrade list from the strategy object
                self.id += 1

    def unsubscribe_channel(self, symbol: str, channel="bookTicker", strategy: Union[None,'Strategy']= None):
        params = [f"{symbol.lower()}@{channel}"]
        
        if channel == "bookTicker":
            _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
            msg = {"method": "UNSUBSCRIBE", 
                   "params": params, "id": _id}
            self._ws.send(json.dumps(msg))
            self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
            self.prices.pop(symbol)
        
        elif channel == "aggTrade":
            self.strategy_counter[symbol]['count'] -= 1
            if self.strategy_counter[symbol]['count'] == 0:
                msg = {"method": "UNSUBSCRIBE", "params": params,
                       "id": self.strategy_counter[symbol]['id']}
                self._ws.send(json.dumps(msg))
                self.strategy_counter.pop(symbol)
                self.running_startegies.pop(strategy)

    ############################ Strategy Arguments ############################
    def _bookTickerMsg(self, data, symbol):
        """
        bookTicker message is pushed when either one of the bid or ask changes.
        Used to track a trading pairs and calculate unrealized PnL.
        
        Subscribe to the bookTicker to track a contract pair, or when starting new strategy.
        """
        # Update ask/bid prices
        self.prices[symbol].bid = float(data["b"])
        self.prices[symbol].ask = float(data["a"])
                
        for strategy in self.running_startegies:
            if symbol == strategy.contract.symbol and strategy.had_assits:
                # Calculate the uPnL only when an order is made
                self._check_tp_sl(strategy)
        return
    
    def _check_tp_sl(self, strategy: 'Strategy'):
        buying_price = strategy.order.price
        unrealizedPnl = (1 - self.prices[strategy.contract.symbol].ask / buying_price) * 100
        # Take Profit or Stop Loss check
        if unrealizedPnl >= strategy.tp or unrealizedPnl <= -1 * strategy.sl:
            self._sell_strategy_asset(strategy)
        return

    def _sell_strategy_asset(self, strategy):
        sell_order = self._make_order(self.contracts[strategy.contract.symbol], 'SELL',
                                      order_type='MARKET', quantity=strategy.order.quantity)
        if sell_order:
            strategy.order = sell_order
            strategy.relaizedPnL += self._PnLcalciator(strategy, sell_order)
            strategy.had_assits = False
        return
    
    @classmethod
    def _PnLcalciator(cls, strategy: 'Strategy', sell_order: Order) ->float:
        sell_margin = sell_order.quantity * sell_order.price
        buy_margin = strategy.order.quantity * strategy.order.price
        return sell_margin - buy_margin
    
    def _aggTradeMsg(self, data, symbol):
        """
        AggTrade message is send when a trade is made.
        Used to update indicators and make trading decision.
        
        Subscribe to this channel when starting new strategy, and cancel the subscribtion once
        all running strategies for a given contract stopped.
        """
        trade_price = float(data['p'])
        volume = float(data['q'])
        timestamp = int(data['T'])
                
        for strategy in self.running_startegies:
            if strategy.is_running:
                if symbol==strategy.contract.symbol:
                    decision = strategy.parse_trade(trade_price, 
                                                    volume, timestamp)
                    self._process_dicision(strategy, decision,
                                           latest_price=trade_price)
            else:
                self.unsubscribe_channel(symbol, 'aggTrade', strategy)
        return
    
    def _process_dicision(self, strategy: 'Strategy', decision: str, latest_price: float):
        if 'buy' in decision and not strategy.had_assits:
            # Binance don't allow less than 10$ transaction
            min_qty_margin = max(10 / latest_price, strategy.contract.minQuantity)
            # USDT or BUSD, etc..
            base_asset = strategy.contract.quoteAsset
            # get the balance information
            balance = self.balance[base_asset] 
            # Calculate the desired money for trade
            buy_margin = balance.availableBalance * strategy.buy_pct
            # calculate order quantity and apply 5% negative slippage
            quantity_margin = (buy_margin/latest_price) * 0.95
            quantity_margin = round(quantity_margin ,
                                    strategy.contract.quantityPrecision)
            
            if quantity_margin > min_qty_margin:
                order = self._make_order(strategy.contract, order_side='BUY',
                                                  order_type='MARKET', quantity=quantity_margin)
                if order:
                    strategy.order = order
                    strategy.had_assits = True
                    self.logger.info(f"""
                          {strategy.order.symbol} buying order was made.
                          Quantity: {strategy.order.quantity}. 
                          Price: {strategy.order.price}
                          """)
            else:
                self.logger.info(f"{self.strategy.contract.symbol} buying option could not be made because the ordered quantity is less than the minimum margin")
        
        elif 'sell' in decision.lower() and strategy.had_assits:
                # If there is an existing order and indicators are not good, SELL
                self._sell_strategy_asset(strategy)
        return
