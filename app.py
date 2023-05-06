from typing import Dict

import dash_bootstrap_components as dbc
from dash import Dash, dcc, html

from Connectors.binance_connector import BinanceClient
from Connectors.crypto_base_class import CryptoExchange
from dashboard.dashboard_ui import (bottom_container, footer, middel_container,
                                    nav_bar, technical_modal, upper_container)

clients = {'Binance': BinanceClient(is_spot=False, is_test=True)}


def main(clients: Dict[str, CryptoExchange]):
    external_stylesheets = [
        dbc.themes.BOOTSTRAP,
        dbc.icons.BOOTSTRAP,
        dbc.icons.FONT_AWESOME,
        'style.css',
    ]

    app = Dash(external_stylesheets=external_stylesheets)
    app.layout = html.Div(
        [
            nav_bar(),
            html.Div(
                [
                    upper_container(clients),
                    middel_container(),
                    bottom_container(),
                    footer(),
                    technical_modal(),
                    dcc.Interval(id='update-interval', interval=1000),
                    dcc.Interval(id='websocket-init', max_intervals=1),
                ],
                className='body-container',
            ),
        ]
    )
    return app


if __name__ == '__main__':
    app = main(clients)
    from dashboard.dashboard_callbacks import *
    app.run(debug=True, use_reloader=False)
