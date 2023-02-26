from typing import *

import dash
import dash_bootstrap_components as dbc

from Moduls.data_modul import *
from Connectors.binance_connector import BinanceClient

binance_client = BinanceClient(is_spot=False, is_test=True)

clients = {'Binance': binance_client}
exchanges = {"Binance": binance_client.contracts}

from dashboard.dashboard_ui import *
from dashboard.dashboard_callbacks import *

app = dash.Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])

app.layout = dbc.Container([contracts_layout(exchanges),
                            strategy_layout(exchanges),
                            dcc.Interval(id='watchlist_interval', interval=1000)])

if __name__ == '__main__':
    app.run(debug=True)