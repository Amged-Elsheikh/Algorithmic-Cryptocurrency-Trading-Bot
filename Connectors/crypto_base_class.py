import logging
import time
from abc import ABC, abstractmethod, abstractproperty
from collections import deque, namedtuple
from threading import Thread
from typing import TYPE_CHECKING, Dict, List, Literal, Union

import websocket
from requests.models import Response

from Moduls.data_modul import Balance, CandleStick, Contract, Order, Price

if TYPE_CHECKING:
    from strategies import Strategy


class CryptoExchange(ABC):
    def __init__(self):
        self.logger: logging.Logger  # Logger is defined in the inherted class
        self.log_map = {
            "debug": self.logger.debug,
            "info": self.logger.info,
            "warning": self.logger.warning,
            "error": self.logger.error,
        }
        self._queue_tuple = namedtuple("Logs", "msg, level")
        self.log_queue = deque()
        # Websocket connection
        self._ws_connect = False
        self.id = 1
        self.prices: Dict[str, Price]
        self.balance: Dict[str, Balance]
        self.bookTicker_subscribtion_list: Dict[Contract, int] = dict()
        """
        running_startegies key: 'symbol_id'.\n
        value: strategy object, to be used later in the UI
        """
        self.running_startegies: Dict[str, Strategy] = dict()
        """
        A single contract can have multiple running strategies.
        key: symbol_id\n,
        value: strategy object, to be used later in the UI
        """
        self.strategy_counter: Dict[str, Dict[str, int]] = dict()
        """
        when a new strategyy added, the counter will increase, and when
        strategy is executed/canceled, counter will go down. Once counter
        reach Zero, unsubscribe the aggTrade channel. The first key is the
        symbol, and the item is another dictionary. For the 2nd dict,
        the keys are the counter 'count' and the 'id' for the web socket
        """

    @abstractproperty
    def exchange(self) -> str:
        pass

    def run(self):
        self._ws_connect = True
        t = Thread(target=self._start_ws)
        t.start()

    @abstractmethod
    def _execute_request(
        self, endpoint: str, params: Dict, http_method: str
    ) -> Response:
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
    def _get_contracts(self) -> Dict[str, Contract]:
        pass

    @abstractmethod
    def get_candlestick(self, contract: Contract, interval: str) -> List[CandleStick]:
        pass

    @abstractmethod
    def get_price(self, contract: Contract) -> Price:
        pass

    @abstractmethod
    def make_order(self, contract: Contract, **kwargs) -> Order:
        pass

    @abstractmethod
    def order_status(self, order: Order) -> Order:
        pass

    @abstractmethod
    def delete_order(self, order: Order) -> Order:
        pass

    @abstractmethod
    def getBalance(self):
        pass

    def _start_ws(self):
        self._ws = websocket.WebSocketApp(
            url=self._ws_url,
            on_open=self._on_open,
            on_close=self._on_close,
            on_error=self._on_error,
            on_message=self._on_message,
        )
        self._is_closed = False
        # Reopen the websocket connection if it terminated
        while not self._is_closed:
            try:
                if self._ws_connect:
                    # Reconnect unless the interface is closed by the user
                    self._ws.run_forever()
                else:
                    break
            except Exception as e:
                # Update the log about this error
                self.add_log(
                    msg=f"{self.exchange} error in run_forever() method: {e}",
                    level="warning",
                )
            # Add sleeping interval
            time.sleep(3)

    def _on_open(self, ws: websocket.WebSocketApp):
        self.add_log(msg="Websocket connected", level="info")

    def _on_error(self, ws: websocket.WebSocketApp, error):
        self.add_log(msg=f"Error: {error}", level="error")

    def _on_close(self, ws: websocket.WebSocketApp):
        self._ws_connect = False
        self.add_log(msg="Websocket disconnect", level="info")
        self._is_closed = True
        return

    @abstractmethod
    def _on_message(self, ws: websocket.WebSocketApp, msg):
        pass

    def add_log(self, msg: str, level: str):
        self.log_map[level.lower()](msg)
        msg = f"{self.exchange} Connector: {msg}"
        self.log_queue.append(self._queue_tuple(msg, level))

    # ########################### Websocket Arguments ########################
    @abstractmethod
    def new_subscribe(
        self, channel: Literal["tickers", "candles"], symbol: str, interval: str
    ):
        pass

    @abstractmethod
    def unsubscribe_channel(
        self,
        channel: Literal["tickers", "candles"],
        *,
        symbol: Union[str, None] = None,
        strategy: Union["Strategy", None] = None,
    ):
        pass

    # ########################### Strategy Arguments ##########################
    def _check_tp_sl(self, strategy: "Strategy"):
        buying_price = strategy.order.price
        strategy.unpnl = self.prices[strategy.symbol].ask / buying_price - 1
        # Take Profit or Stop Loss check
        if strategy.unpnl >= strategy.tp or strategy.unpnl <= -1 * strategy.sl:
            self._sell_with_strategy(strategy)
        return

    @abstractmethod
    def _process_dicision(self, strategy: "Strategy", decision: str):
        pass

    @abstractmethod
    def _sell_with_strategy(self, strategy: "Strategy"):
        pass

    @abstractmethod
    def _buy_with_strategy(self, strategy: "Strategy"):
        pass
