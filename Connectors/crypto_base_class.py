import logging
import time
from abc import ABC, abstractmethod, abstractproperty
from collections import deque, namedtuple
from threading import Thread
from typing import TYPE_CHECKING, Dict, List, Union

import websocket
from requests.models import Response

from Moduls.data_modul import Balance, CandleStick, Contract, Order, Price

if TYPE_CHECKING:
    from strategies import Strategy


class CryptoExchange(ABC):

    def __init__(self):
        self._queue_tuple = namedtuple('Logs', 'msg, level')
        self.logger: logging.Logger
        self.log_map = {
            'debug': self.logger.debug,
            'info': self.logger.info,
            'warning': self.logger.warning,
            'error': self.logger.error,
        }
        self.log_queue = deque()
        self._queue_tuple = namedtuple('Logs', 'msg, level')
        # Websocket connection
        self._ws_connect = False
        self.id = 1
        self.bookTicker_subscribtion_list: Dict[Contract, int] = dict()
        '''
        running_startegies key: 'symbol_id'.\n
        value: strategy object, to be used later in the UI
        '''
        self.running_startegies: Dict[str, Strategy] = dict()
        '''
        A single contract can have multiple running strategies.
        key: symbol_id\n,
        value: strategy object, to be used later in the UI
        '''
        self.strategy_counter: Dict[str, Dict[str, int]] = dict()
        '''
        when a new strategyy added, the counter will increase, and when
        strategy is executed/canceled, counter will go down. Once counter
        reach Zero, unsubscribe the aggTrade channel. The first key is the
        symbol, and the item is another dictionary. For the 2nd dict,
        the keys are the counter 'count' and the 'id' for the web socket
        '''

    @abstractmethod
    def _init(self, is_spot: bool, is_test: bool) -> None:
        pass

    @abstractproperty
    def exchange(self) -> str:
        pass

    def run(self):
        self._ws_connect = True
        t = Thread(target=self._start_ws)
        t.start()

    @abstractmethod
    def _execute_request(
        endpoint: str, params: Dict, http_method: str
    ) -> Union[Response, None]:
        pass

    @abstractmethod
    def _generate_signature(self, query_string: str) -> str:
        pass

    @abstractproperty
    def _is_connected(self) -> bool:
        pass

    @abstractmethod
    def _check_internet_connection(self) -> bool:
        pass

    @abstractmethod
    def _get_contracts(self) -> Union[Dict[str, Contract], None]:
        pass

    @abstractmethod
    def get_candlestick(
        self, contract: Contract, interval: str
    ) -> Union[List[CandleStick], None]:
        pass

    @abstractmethod
    def get_price(self, contract: Contract) -> Union[Price, None]:
        pass

    @abstractmethod
    def make_order(self, contract: Contract, **kwargs) -> Union[Order, None]:
        pass

    @abstractmethod
    def order_status(self, order: Order) -> Union[Order, None]:
        pass

    @abstractmethod
    def delete_order(self, order: Order) -> Union[Order, None]:
        pass

    @abstractproperty
    def balance(self) -> Union[Dict[str, Balance], None]:
        pass

    @balance.setter
    def balance(self, *args, **kwargs) -> Dict[str, Balance]:
        self.add_log(msg="Balance can't be edited manually", level='warning')
        return self.balance

    def _start_ws(self):
        self._ws = websocket.WebSocketApp(
            url=self._ws_url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._ws_on_message,
        )
        # Reopen the websocket connection if it terminated
        while True:
            try:
                if self._ws_connect:
                    # Reconnect unless the interface is closed by the user
                    self._ws.run_forever()
                else:
                    break
            except Exception as e:
                # Update the log about this error
                self.add_log(
                    msg=f'{self.exchange} error in run_forever() method: {e}',
                    level='warning',
                )
            # Add sleeping interval
            time.sleep(3)

    def _on_open(self, ws: websocket.WebSocketApp):
        self.add_log(msg='Websocket connected', level='info')

    def _on_error(self, ws: websocket.WebSocketApp, error):
        self.add_log(msg=f'Error: {error}', level='error')

    def _on_close(self, ws: websocket.WebSocketApp):
        self._ws_connect = False
        self.add_log(msg='Websocket disconnect', level='info')

    @abstractmethod
    def _ws_on_message(self, ws: websocket.WebSocketApp, msg):
        pass

    def add_log(self, msg: str, level: str):
        self.log_map[level.lower()](msg)
        msg = f'{self.exchange} Connector: {msg}'
        self.log_queue.append(self._queue_tuple(msg, level))

    # ########################### Websocket Arguments ########################
    # ########################### Websocket Arguments ########################
    # ########################### Websocket Arguments ########################
    @abstractmethod
    def new_subscribe(self, channel: str, symbol: str) -> None:
        pass

    @abstractmethod
    def unsubscribe_channel(
        self,
        channel='bookTicker',
        *,
        symbol: Union[str, None] = None,
        strategy: Union['Strategy', None] = None,
    ) -> None:
        pass

    # ########################### Strategy Arguments ##########################
    def _check_tp_sl(self, strategy: 'Strategy'):
        buying_price = strategy.order.price
        strategy.unpnl = self.prices[strategy.symbol].ask / buying_price - 1
        # Take Profit or Stop Loss check
        if strategy.unpnl >= strategy.tp or strategy.unpnl <= -1 * strategy.sl:
            self._sell_strategy_asset(strategy)
        return

    @abstractmethod
    def _process_dicision(
        self, strategy: 'Strategy', decision: str, latest_price: float
    ):
        pass

    @abstractmethod
    def _sell_strategy_asset(self, strategy: 'Strategy'):
        pass
