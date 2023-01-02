from typing import *
import pandas as pd
import dash
from dash import Input, Output, State
import dash_bootstrap_components as dbc

@dash.callback(Output(component_id='contracts_dropdown', component_property='value'),
               Input(component_id='contracts_dropdown', component_property='value'))
def subscribe_to_new_stream(value: str):
    if value:
        exchange, symbol = value.split(" ")
        if exchange == 'Binance':
            from app import binance_client
            binance_client.new_subscribe(symbol)
    return None

@dash.callback(Output(component_id='ws_table', component_property='data'),
               Input(component_id='watchlist_interval', component_property='n_intervals'))
def ws_data_update(*args):
    # df = pd.DataFrame(data)
    from app import binance_client
    data = [{'symbol': price.symbol, 'exchange': price.exchange,
             'bidPrice': price.bid, 'askPrice': price.ask} 
            for price in binance_client.prices.values()]
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
                
        from app import binance_client
        binance_client.unsubscribe_channel(item['symbol'])
    return 20
