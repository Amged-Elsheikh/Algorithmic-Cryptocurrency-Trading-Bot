from typing import *
import pandas as pd
import plotly.express as px
import dash
from dash import html, dcc, dash_table
import dash_bootstrap_components as dbc
from Moduls.data_modul import *

def contracts_layout(exchanges: Dict[str, Dict[str, Contract]]):
    
    exchanges_dropdown = dbc.Checklist(options=list(exchanges.keys()),
                                       value=list(exchanges.keys()),
                                       className='col-auto',
                                       id='exchanges_dropdown')
    exchages_dropdown = dbc.Col([html.Label('Exchanges', className='col-auto'),
                                 exchanges_dropdown], className='col-3')

    for exchange in exchanges.keys():
        contracts = {f"{exchange} {symbol}": contract 
                             for symbol, contract in exchanges[exchange].items()}
        
    contracts_dropdown = dbc.Col([dcc.Dropdown(options=list(contracts.keys()),
                                               multi=False, placeholder='Select Contract to track',
                                               id='contracts_dropdown')])
    columns = ['symbol', 'exchange', 'bidPrice', 'askPrice']
    data = pd.DataFrame(index=['id'], columns=columns)
    table = dash_table.DataTable(data=data.to_dict('records'),
                                 columns=[{"name": i, "id": i} for i in data.columns],                       
                                 fixed_rows={'headers': True}, page_size=20,
                                 style_table={'height': '300px', 'overflowY': 'auto'},
                                 id='ws_table', row_deletable=True)
    
    header = dbc.Row([exchages_dropdown, contracts_dropdown], class_name='container-fluid, mt-3')
    
    return dbc.Row(dbc.Container([header, table], class_name='container-fluid col-6'))