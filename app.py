from typing import *

import dash
import dash_bootstrap_components as dbc

from Moduls.data_modul import *
from Connectors.binance_connector import BinanceClient
from dashboard.dashboard_ui import *

binance_client = BinanceClient(is_spot=False, is_test=True)

clients = {'Binance': binance_client}
exchanges = {"Binance": binance_client.contracts}


external_stylesheets = [dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP, 
                        dbc.icons.FONT_AWESOME,'style.css']

app = dash.Dash(external_stylesheets=external_stylesheets)

app.layout = html.Div([nav_bar(),
                       html.Div(
                           [ 
                            upper_container(clients),
                            middel_container(),
                            bottom_container(),
                            footer()],
                           className="body-container mx-5")])

# from dashboard.dashboard_callbacks import *

if __name__ == '__main__':
    app.run(debug=True)