from typing import *
import pandas as pd
import dash
from dash import Input, Output, State
import dash_bootstrap_components as dbc

from strategies import Strategy
from Moduls.data_modul import Contract 
from app import clients

@dash.callback(Output(component_id='contracts_dropdown', component_property='value'),
               Input(component_id='contracts_dropdown', component_property='value'))
def subscribe_to_new_stream(value: str):
    if value:
        exchange, symbol = value.split(" ")
        clients[exchange].new_subscribe(symbol)
        
    return None

@dash.callback(Output(component_id='ws_table', component_property='data'),
               Input(component_id='watchlist_interval', component_property='n_intervals'))
def ws_data_update(*args):
    data = [{'symbol': price.symbol, 'exchange': price.exchange,
             'bidPrice': price.bid, 'askPrice': price.ask}
            
            for price in clients['Binance'].prices.values()]
    return data

@dash.callback(Output(component_id='ws_table', component_property='page_size'),
               Input(component_id='ws_table', component_property='data_previous'),
               State(component_id='ws_table', component_property='data'))

def unsubscribe_channel(prev_data, data):
    if prev_data:
        if len(prev_data)==1:
            item = prev_data[0]
        else:
            for item in prev_data:
                if item not in data:
                    break
        clients['Binance'].unsubscribe_channel(item['symbol'])
    return 20


@dash.callback(Output(component_id='strategy_contracts_dropdown', component_property='value'),
               Input(component_id='run_strategy', component_property='n_clicks'),
               State(component_id='strategy_contracts_dropdown', component_property='value'), 
               State(component_id='tp', component_property='value'),
               State(component_id='sl', component_property='value'),
               State(component_id='buy', component_property='value'),
               State(component_id='fast_ema', component_property='value'),
               State(component_id='slow_ema', component_property='value'),
               State(component_id='fast_macd', component_property='value'),
               State(component_id='slow_macd', component_property='value'),
               State(component_id='signal_macd', component_property='value'),
               State(component_id='interval_dropdown', component_property='value'),
               prevent_initial_call=True)
def start_strategy(n_click, contract: Contract, tp, sl, 
                   buy_pct, fast_ema, slow_ema, fast_macd, 
                   slow_macd, macd_signal, interval):
    
    if fast_ema > slow_ema:
        raise 'Fast EMA should be less than slow EMA' 
    ema = {'slow': slow_ema, 'fast': fast_ema}
    
    if fast_macd > slow_macd:
        raise 'Fast MACD should be less than slow MACD'
    
    macd = {'slow': slow_macd, 'fast': fast_macd, 
            'signal': macd_signal}
    exchange, symbol = contract.split(' ')
    
    Strategy(clients[exchange], symbol, interval, 
             ema, macd, tp, sl, buy_pct)
    return None