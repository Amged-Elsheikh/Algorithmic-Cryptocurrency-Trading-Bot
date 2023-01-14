from typing import *

import dash
import dash_bootstrap_components as dbc
import plotly.express as px
from dash import dcc, html

from Connectors.binance_connectore import BinanceClient
from dashboard.dashboard_ui import *
from Moduls.data_modul import *

# if TYPE_CHECKING:
from dashboard.dashboard_callbacks import *


binance_client = BinanceClient()
candles = binance_client.get_candlestick(binance_client.contracts['BTCUSDT'], '4h')

print('hi')
# exchanges = {"Binance":binance_client.contracts}

# app = dash.Dash(external_stylesheets=[dbc.themes.BOOTSTRAP])

# app.layout = html.Div([contracts_layout(exchanges), 
#                       dcc.Interval(id='watchlist_interval', interval=1000)])

# if __name__ == '__main__':
#     app.run(debug=True)