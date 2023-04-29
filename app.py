import dash
import dash_bootstrap_components as dbc

from Connectors.binance_connector import BinanceClient
from dashboard.dashboard_ui import *


clients = {'Binance': BinanceClient(is_spot=False, is_test=True)}


def main(clients):
    external_stylesheets = [dbc.themes.BOOTSTRAP, dbc.icons.BOOTSTRAP, 
                            dbc.icons.FONT_AWESOME,'style.css']

    app = dash.Dash(external_stylesheets=external_stylesheets)
    app.layout = html.Div([nav_bar(),
                        html.Div(
                            [ 
                                upper_container(clients),
                                middel_container(),
                                bottom_container(),
                                footer(),
                                technical_modal(),
                                dash.dcc.Interval(id='update-interval', interval=1000),
                                dash.dcc.Interval(id='websocket-init', max_intervals=1)
                                ],
                            className="body-container")])
    return app


if __name__ == '__main__':
    app = main(clients)
    from dashboard.dashboard_callbacks import *
    app.run(debug=True, use_reloader=False)