from typing import List
from dash import Input, Output, State, callback, ctx, no_update
import dash_bootstrap_components as dbc

from strategies import TechnicalStrategies
from Moduls.data_modul import Contract

# This import is causing conflicts. App is workin, but need to be fixed
from app import clients


LOGS_COLOR_MAP = {
    'debug': 'primary',
    'info': 'secondary',
    'warning': 'warning',
    'error': 'danger',
    'critical': 'danger',
}


def get_removed_row(prev_data, data):
    for item in prev_data:
        if item not in data:
            return item


@callback(
    Output('websocket-init', 'disabled'),
    Input('websocket-init', 'n_intervals'),
    prevent_initial_call=True,
)
def start_websockets(*args):
    for client in clients.values():
        client.run()
    return True


@callback(Output('watchlist-select', 'value'),
          Input('watchlist-select', 'value'))
def subscribe_to_new_stream(value: str):
    if value:
        exchange, symbol = value.split(' ')
        clients[exchange].new_subscribe(channel='bookTicker', symbol=symbol)
    return None


@callback(
    Output('watchlist-table', 'data'),
    Input('watchlist-table', 'data_previous'),
    Input('update-interval', 'n_intervals'),
    State('watchlist-table', 'data'),
)
def update_watchlist_table(prev_data, n, data):
    if ctx.triggered_id == 'watchlist-table':
        removed_row = get_removed_row(prev_data, data)
        client = clients[removed_row['Exchange']]
        symbol = removed_row['Symbol']
        client.unsubscribe_channel(channel='bookTicker', symbol=symbol)
        # After unsubscribing, the Backend will manage to remove from the UI
    elif ctx.triggered_id == 'update-interval':
        data = [
            {
                'Symbol': price.symbol,
                'Exchange': price.exchange,
                'bidPrice': price.bid,
                'askPrice': price.ask
                }
            for client in clients.values()
            for price in client.prices.values()
            ]
    return data


@callback(
    Output('uPnl-table', 'data'),
    Input('uPnl-table', 'data_previous'),
    Input('update-interval', 'n_intervals'),
    State('uPnl-table', 'data'),
)
def update_strategy_table(prev_data, n, data):
    if ctx.triggered_id == 'uPnl-table':
        removed_row = get_removed_row(prev_data, data)
        client = clients[removed_row['Exchange']]
        symbol = removed_row['Symbol']
        strategy_id = removed_row['ID']
        strategy = client.running_startegies[f'{symbol}_{strategy_id}']
        client.unsubscribe_channel(channel='aggTrade', strategy=strategy)
        if hasattr(strategy, 'order'):
            strategy.order = client.make_order(
                contract=strategy.contract,
                side='SELL',
                order_type='MARKET',
                quantity=strategy.order.quantity,
            )
    elif ctx.triggered_id == 'update-interval':
        data = [
            {
                'ID': strategy.strategy_id,
                'Exchange': strategy.client.exchange,
                'Symbol': strategy.symbol,
                'Qty': (strategy.order.quantity
                        if strategy.had_assits else 0),
                'Entry Price': (strategy.order.price
                                if strategy.had_assits else 0),
                'Current Price': client.prices[strategy.symbol].bid,
                'uPnl': f'{strategy.unpnl*100}%',
                }
            for client in clients.values()
            for strategy in client.running_startegies.values()
            ]
    return data


@callback(
    Output('strategy-contracts-dropdown', 'value'),
    Input('add-strategy-btn', 'n_clicks'),
    State('strategy-contracts-dropdown', 'value'),
    State('entry-pct', 'value'),
    State('take-profit', 'value'),
    State('stop-loss', 'value'),
    State('interval-dropdown', 'value'),
    State('strategy-type-select', 'value'),
    State('fast-ema', 'value'),
    State('slow-ema', 'value'),
    State('fast-macd', 'value'),
    State('slow-macd', 'value'),
    State('macd-signal', 'value'),
    State('rsi-period', 'value'),
    prevent_initial_call=True,
)
def start_strategy(
    n_click,
    contract: Contract,
    buy_pct,
    tp,
    sl,
    interval,
    strategy_type,
    fast_ema,
    slow_ema,
    fast_macd,
    slow_macd,
    macd_signal,
    rsi,
):
    if strategy_type == 'Technical':
        ema = {'fast': fast_ema, 'slow': slow_ema}
        macd = {'fast': fast_macd, 'slow': slow_macd, 'signal': macd_signal}
        exchange, symbol = contract.split(' ')
        TechnicalStrategies(
            client=clients[exchange],
            symbol=symbol,
            interval=interval,
            tp=tp,
            sl=sl,
            buy_pct=buy_pct,
            ema=ema,
            macd=macd,
            rsi=rsi,
        )
    return None


@callback(
    Output('logs-list', 'children'),
    Input('update-interval', 'n_intervals'),
    State('logs-list', 'children'),
)
def update_log_list(n, logs_list: List):
    no_logs_count = 0
    for client in clients.values():
        new_logs = client.log_queue
        if len(new_logs) == 0:
            no_logs_count += 1
            continue
        while new_logs:
            log = new_logs.pop()
            logs_list.append(
                dbc.ListGroupItem(log.msg, color=LOGS_COLOR_MAP[log.level])
            )
    if no_logs_count == len(clients):
        return no_update
    return logs_list
