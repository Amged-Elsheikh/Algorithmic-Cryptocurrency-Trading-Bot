import hashlib
import hmac
import json
import logging
import logging.config
import os
import time
from typing import TYPE_CHECKING, Callable, Dict, Union
from urllib.parse import urlencode

import requests
import websocket
from dotenv import load_dotenv
from requests.exceptions import RequestException
from requests.models import Response

from Connectors.crypto_base_class import CryptoExchange
from Moduls.data_modul import Balance, CandleStick, Contract, Order, Price

if TYPE_CHECKING:
    from strategies import Strategy

load_dotenv()
logging.config.fileConfig('logger.config')


class BinanceClient(CryptoExchange):
    _http_dict: Dict[str, Callable] = {
            'GET': requests.get,
            'POST': requests.post,
            'DELETE': requests.delete
            }
    _loaded = dict()

    def __new__(cls, is_spot: bool, is_test: bool):
        if (client := cls._loaded.get(f'{is_spot} {is_test}')) is None:
            client = super().__new__(cls)
            cls._loaded[f'{is_spot} {is_test}'] = client
        return client

    def __init__(self, is_spot: bool, is_test: bool):
        self._init(is_spot, is_test)
        self._header = {
            'X-MBX-APIKEY': os.getenv(self._api_key),
            'Content-Type': 'application/json',
        }
        self.logger = logging.getLogger(__name__)
        super().__init__()
        self._check_internet_connection()
        self.contracts = self._get_contracts()
        self.prices: Dict[str, Price] = dict()

    def _init(self, is_spot: bool, is_test: bool):
        urls = {
            (True, True): ('https://testnet.binance.vision/api',
                           'wss://testnet.binance.vision/ws'),
            (True, False): ('https://api.binance.com/api',
                            'wss://stream.binance.com:9443/ws'),
            (False, True): ('https://testnet.binancefuture.com',
                            'wss://stream.binancefuture.com/ws'),
            (False, False): ('https://fapi.binance.com',
                             'wss://fstream.binance.com/ws'),
            }
        self._base_url, self._ws_url = urls[(is_spot, is_test)]
        spot_future = 'Spot' if is_spot else 'Future'
        real_test = 'Test' if is_test else ''
        self._api_key = f'{self.exchange}{spot_future}{real_test}APIKey'
        self._api_secret = self._api_key.replace('APIKey', 'APISecret')
        return

    @property
    def _is_connected(self):
        response = self._execute_request(
            endpoint='/fapi/v1/ping',
            params=dict(),
            http_method='GET'
            )
        try:
            response.raise_for_status()
            return True
        except Exception:
            return False

    def _check_internet_connection(self):
        connection_flag = 0
        while not self._is_connected:
            if connection_flag >= 5:
                msg = f'{self.exchange} Client failed to connect'
                self.add_log(msg=msg, level='warning')
                raise Exception(msg)
            else:
                connection_flag += 1
                time.sleep(3)
        msg = 'Internet connection established'
        self.add_log(msg=msg, level='info')
        return True

    @property
    def exchange(self):
        return 'Binance'

    def _execute_request(
        self, endpoint: str, params: Dict, http_method: str
    ) -> Response | None:
        '''This argument is used to send all types of requests to the server'''
        try:
            # Get the timestamp
            params['timestamp'] = int(time.time() * 1000)
            # Generate the signature for the query
            params['signature'] = self._generate_signature(urlencode(params))
            http_method = self._http_dict[http_method]
            response = http_method(
                url=self._base_url + endpoint,
                params=params,
                headers=self._header
                )
            response.raise_for_status()
            return response
        except RequestException as e:
            self.add_log(msg=f'Request error {e}', level='warning')
        except Exception as e:
            self.add_log(msg=f'Error {e}', level='error')
        return None

    def _generate_signature(self, query_string: str):
        return hmac.new(
            key=os.getenv(self._api_secret).encode('utf-8'),
            msg=query_string.encode('utf-8'),
            digestmod=hashlib.sha256,
        ).hexdigest()

    # ###################### MARKET DATA FUNCTION #######################
    def _get_contracts(self) -> Dict[str, Contract] | None:
        '''Return all exchange contracts.'''
        response = self._execute_request(
            endpoint='/fapi/v1/exchangeInfo',
            params=dict(),
            http_method='GET'
            )
        if response:
            symbols = response.json()['symbols']
            contracts = {
                symbol['symbol']: Contract(symbol, exchange=self.exchange)
                for symbol in symbols
            }
            return contracts
        return None

    def get_candlestick(self, contract: Contract, interval: str):
        '''
        Get a list of the historical Candlestickes for given contract.
        '''
        params = {'symbol': contract.symbol, 'interval': interval}
        response = self._execute_request(
            endpoint='/fapi/v1/klines',
            params=params,
            http_method='GET'
            )
        if response:
            return [CandleStick(candle, exchange=self.exchange)
                    for candle in response.json()]
        return None

    def get_price(self, contract: Contract) -> Price | None:
        '''Get the latest traded price for the contract.'''
        response = self._execute_request(
            endpoint='/fapi/v1/ticker/bookTicker',
            params={'symbol': contract.symbol},
            http_method='GET',
        )
        if response:
            self.prices[contract.symbol] = Price(response.json(),
                                                 exchange=self.exchange)
            return self.prices[contract.symbol]
        return None

    # ######################### TRADE Arguments ##########################
    def make_order(self, contract: Contract, *,
                   side: str, order_type: str, **kwargs):
        '''
        Make a Buy/Long or Sell/Short order for a given contract.
        This argument is a private argument and can only be accesed
        within the connecter, when a buying or selling signal is found,
        or when canceling the runnning strategy
        '''
        # Add the mandotary parameters
        params = {
            'symbol': contract.symbol,
            'side': side,
            'type': order_type}
        # Add extra parameters
        params.update(kwargs)
        response = self._execute_request(
            endpoint='/fapi/v1/order',
            params=params,
            http_method='POST'
            )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def order_status(self, order: Order):
        '''Get information of a given order.'''
        params = {'symbol': order.symbol, 'orderId': order.orderId}
        response = self._execute_request(
            endpoint='/fapi/v1/order',
            params=params,
            http_method='GET'
            )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    def delete_order(self, order: Order) -> Order:
        '''
        Deleting an order. This argument is helpful for future trades,
        or when applying LIMIT/OCO orders.'''
        params = {'symbol': order.symbol, 'orderId': order.orderId}
        response = self._execute_request(
            endpoint='/fapi/v1/order',
            params=params,
            http_method='DELETE'
        )
        if response:
            return Order(response.json(), exchange=self.exchange)
        return None

    # ######################### ACCOUNT Arguments ##########################
    @property
    def balance(self) -> Dict[str, Balance] | None:
        '''
        Return the amount of the currently holded assests in the wallet
        '''
        response = self._execute_request(
            endpoint='/fapi/v2/account',
            http_method='GET',
            params=dict()
            )
        if response:
            balance = {asset['asset']: Balance(asset, exchange=self.exchange)
                       for asset in response.json()['assets']}
            return balance
        return None

    @balance.setter
    def balance(self, *args, **kwargs):
        self.add_log(msg="Balance can't be edited manually", level='warning')
        return self.balance

    # ########################### Websocket Arguments ########################
    def _ws_on_message(self, ws: websocket.WebSocketApp, msg):
        '''
        This is the argument that will form most of the connections between
        the backend and frontend by automating trades and send data to the UI
        '''
        # Read the received message
        data = json.loads(msg)
        symbol = data.get('s')
        channel = data.get('e')
        if channel == 'bookTicker':
            self._bookTickerMsg(data, symbol)
        elif channel == 'aggTrade':
            self._aggTradeMsg(data, symbol)
        else:
            return

    def new_subscribe(self, channel='bookTicker', symbol='BTCUSDT'):
        params = f'{symbol.lower()}@{channel}'
        contract = self.contracts[symbol]
        if channel == 'bookTicker':
            self._bookTicket_subscribe(contract, params)
        elif channel == 'aggTrade':
            self._aggTrade_subscribe(contract, params)

    def _bookTicket_subscribe(self, contract: Contract, params: str):
        if contract in self.bookTicker_subscribtion_list:
            self.add_log(
                msg=f'Already subscribed to {params} channel', level='info'
            )
            return
        else:
            msg = {
                'method': 'SUBSCRIBE',
                'params': [params],
                'id': self.id}
            # immediatly show current bid and ask prices.
            self.get_price(contract)
            # Subscribe to the websocket channel
            self._ws.send(json.dumps(msg))
            self.bookTicker_subscribtion_list[contract] = self.id
            self.id += 1
            return

    def _aggTrade_subscribe(self, contract: Contract, params: str):
        # Make sure the contract is in the bookTicker.
        if contract not in self.bookTicker_subscribtion_list:
            self._bookTicket_subscribe(contract, params)

        if contract.symbol in self.strategy_counter:
            self.strategy_counter[contract.symbol]['count'] += 1
            self.add_log(
                msg=f'Already subscribed to {params} channel', level='info'
            )
        else:
            msg = {
                'method': 'SUBSCRIBE',
                'params': [params],
                'id': self.id}
            # Subscribe to the websocket channel
            self._ws.send(json.dumps(msg))
            self.strategy_counter[contract.symbol] = {'count': 1,
                                                      'id': self.id}
            # Update the aggTrade list from the strategy object
            self.id += 1
        return

    def unsubscribe_channel(
        self,
        channel='bookTicker',
        *,
        symbol: Union[str, None] = None,
        strategy: Union['Strategy', None] = None,
    ):
        if channel == 'aggTrade':
            self._aggTrade_unsubscribe(strategy)
        elif channel == 'bookTicker':
            if symbol in self.strategy_counter:
                msg = (f"{symbol} had a running strategy and "
                       "can't be removed from the watchlist")
                self.add_log(msg=msg, level='info')
                return
            self._bookTicker_unsubscribe(symbol)
        return

    def _bookTicker_unsubscribe(self, symbol: str):
        _id = self.bookTicker_subscribtion_list[self.contracts[symbol]]
        msg = {
                'method': 'UNSUBSCRIBE',
                'params': [f'{symbol.lower()}@bookTicker'],
                'id': _id
                }
        self._ws.send(json.dumps(msg))
        self.bookTicker_subscribtion_list.pop(self.contracts[symbol])
        self.prices.pop(symbol)
        return

    def _aggTrade_unsubscribe(self, strategy: 'Strategy'):
        symbol = strategy.symbol
        self.running_startegies.pop(f'{symbol}_{strategy.strategy_id}')
        self.strategy_counter[symbol]['count'] -= 1
        if self.strategy_counter[symbol]['count'] == 0:
            msg = {
                    'method': 'UNSUBSCRIBE',
                    'params': [f'{symbol.lower()}@aggTrade'],
                    'id': self.strategy_counter[symbol]['id'],
                    }
            self._ws.send(json.dumps(msg))
            self.strategy_counter.pop(symbol)
            return

    # ########################### Strategy Arguments ##########################
    def _bookTickerMsg(self, data, symbol):
        '''
        bookTicker message is pushed when either one of the bid or ask changes.
        Used to track a trading pairs and calculate unrealized PnL.
        Subscribe to the bookTicker to track a contract pair,
        or when starting new strategy.
        '''
        # Update ask/bid prices
        self.prices[symbol].bid = float(data['b'])
        self.prices[symbol].ask = float(data['a'])
        # Check the status of the order for each running strategy
        for strategy in self.running_startegies.values():
            if symbol == strategy.symbol and hasattr(strategy, 'order'):
                if strategy.order.status in ['NEW', 'PARTIALLY_FILLED']:
                    strategy.order = self.order_status(strategy.order)
                elif strategy.order.status in ['CANCELED', 'REJECTED',
                                               'EXPIRED']:
                    self._aggTrade_unsubscribe(strategy=strategy)
                    strategy.is_running = False
                    continue
                if strategy.order.status == 'FILLED':
                    # Calculate the uPnL only when an order is made
                    self._check_tp_sl(strategy)
        return

    def _aggTradeMsg(self, data, symbol):
        '''
        AggTrade message is send when a trade is made.
        Used to update indicators and make trading decision.

        Subscribe to this channel when starting new strategy, and cancel the
        subscribtion once all running strategies for a given contract stopped.
        '''
        trade_price = float(data['p'])
        volume = float(data['q'])
        timestamp = int(data['T'])
        for strategy in self.running_startegies.values():
            if strategy.is_running:
                if symbol == strategy.contract.symbol:
                    decision = strategy.parse_trade(
                        trade_price,
                        volume,
                        timestamp
                        )
                    self._process_dicision(
                        strategy=strategy,
                        decision=decision,
                        latest_price=trade_price)
            else:
                self._aggTrade_unsubscribe(strategy=strategy)
        return

    def _process_dicision(
        self, strategy: 'Strategy', decision: str, latest_price: float
    ):
        if decision == 'buy or hodl':
            if not strategy.had_assits:
                # Binance don't allow less than 10$ transaction
                min_qty_margin = max(10 / latest_price,
                                     strategy.contract.minQuantity)
                # USDT or BUSD, etc..
                base_asset = strategy.contract.quoteAsset
                # get the balance information
                balance = self.balance[base_asset].availableBalance
                # Calculate the desired money for trade
                buy_margin = balance * strategy.buy_pct
                # calculate order quantity and apply 5% negative slippage
                quantity_margin = (buy_margin / latest_price) * 0.95
                quantity_margin = round(
                    quantity_margin, strategy.contract.quantityPrecision
                )
                if quantity_margin > min_qty_margin:
                    order = self.make_order(
                        strategy.contract,
                        side='BUY',
                        order_type='MARKET',
                        quantity=quantity_margin,
                    )
                    if order:
                        strategy.order = order
                        strategy.had_assits = True
                        msg = (
                            f'{strategy.order.symbol} buying order was made. '
                            f'Quantity: {strategy.order.quantity}. '
                            f'Price: {strategy.order.price}'
                        )
                        self.add_log(msg=msg, level='info')
                else:
                    msg = (
                        f'could not buy {self.strategy.contract.symbol}'
                        'because the ordered quantity is less than the'
                        'minimum margin'
                    )
                    self.add_log(msg=msg, level='info')
            else:
                pass  # Hold the assets
        elif decision == "sell or don't enter":
            if strategy.had_assits:
                # sell when there is an existing order and poor indicators
                self._sell_strategy_asset(strategy)
            else:
                pass  # Do not enter
        return

    def _sell_strategy_asset(self, strategy):
        sell_order = self.make_order(
            contract=self.strategy.contract,
            side='SELL',
            order_type='MARKET',
            quantity=strategy.order.quantity,
        )
        if sell_order:
            while sell_order.status != "FILLED":
                sell_order = self.order_status(sell_order)
                # time.sleep(2)
            strategy.relaizedPnL += strategy._PnLcalciator(sell_order)
            strategy.order = sell_order
            strategy.had_assits = False
        return
