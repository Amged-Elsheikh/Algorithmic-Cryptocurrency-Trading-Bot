from typing import *

import dash_bootstrap_components as dbc
import pandas as pd
from dash import dash_table, dcc

if TYPE_CHECKING:
    from Connectors.binance_connectore import BinanceClient
from Moduls.data_modul import *
from strategies import intervals_to_sec


def get_contracts(clients: Dict[str, 'BinanceClient']) -> Dict[str, Contract]:
    for client in clients:
        contracts = {f"{client}: {symbol}": contract
                     for symbol, contract in clients[client].contracts.items()}
    return contracts


def contracts_layout(clients: Dict[str, 'BinanceClient']):
    contracts = get_contracts(clients)
    
    contracts_dropdown = dbc.Col([
        dcc.Dropdown(options=list(contracts.keys()),
                     multi=False,
                     placeholder="Select Contract to track",
                     id="contracts_dropdown")])

    columns = ["symbol", "exchange", "bidPrice", "askPrice"]
    data = pd.DataFrame(index=["id"], columns=columns)
    
    table = dash_table.DataTable(data=data.to_dict("records"),
                                 columns=[{"name": i, "id": i} for i in data.columns],
                                 style_table={"height": "300px", "overflowY": "auto"},
                                 fixed_rows={"headers": True}, page_size=20,
                                 id="ws_table", row_deletable=True)

    header = dbc.Container(contracts_dropdown, class_name="container-fluid, mt-3 mb-3")
    return dbc.Row(dbc.Container([header, table], class_name="col-6"))


def percentage_container(labels: Set[str], max_=None):
    containers = [[dbc.Label(f'{label} %'), 
                  dbc.Input(value=10, type='number',
                            min=1, max=max_, step=1,
                            id=label.replace(' ', '_').lower())]
                 for label in labels]
    
    
    pct_container = dbc.Col(dbc.Row([dbc.Col(container, width=12//len(containers)) 
                                     for container in containers]),
                            width=len(containers))
    return pct_container


def technical_container(name: str, types: List):
    indicator_labels = [dbc.Col(f"{label[0].capitalize()}") for label in types]
    indicator_inputs = [dbc.Col(dbc.Input(type='number', id=f'{label[0]}_{name.lower()}', 
                                          value=label[1], min=1)) 
                        for label in types]
    
    indicator_container = dbc.Col([dbc.Label(f'{name}'),
                                   dbc.Row(indicator_labels),
                                   dbc.Row(indicator_inputs)],
                                  width = len(types),
                                  class_name='border border-secondary m-3')
    return indicator_container


def strategy_layout(clients: Dict[str, 'BinanceClient']):
    contracts = get_contracts(clients)
    contracts_dropdown = dbc.Col([dbc.Label('Trading Pair'),
                                  dcc.Dropdown(options=list(contracts.keys()),
                                               value='Binance: BTCUSDT',
                                               multi=False, placeholder="contracts",
                                               id="strategy_contracts_dropdown")],
                                 class_name='align-items-center', width=2)
    
    entry_box = dbc.Row([contracts_dropdown, 
                        percentage_container({'TP', 'SL'}), 
                        percentage_container({'Buy'})],
                       className='align-items-center text-center')
    
    technical_box = dbc.Row([technical_container('EMA', [['fast', 7], ['slow', 25]]),
                             technical_container('MACD', [['fast', 12], ['slow', 26], ['signal', 9]])],
                            className='align-items-center text-center')
    
    button = dbc.Button('Run Strategy', id='run_strategy', class_name='btn btn-primary')
    
    intervals_container = dcc.Dropdown(options=list(intervals_to_sec.keys()),
                                       multi=False, value='30m',
                                       placeholder="Select trading interval",
                                       id="interval_dropdown")
    
    return dbc.Container([entry_box, technical_box, intervals_container, button])