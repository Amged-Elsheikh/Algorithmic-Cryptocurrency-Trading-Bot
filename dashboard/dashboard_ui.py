from typing import *
from functools import partial

import dash_bootstrap_components as dbc
import pandas as pd
import dash
from dash import dash_table, dcc, html, Input, Output, State

if TYPE_CHECKING:
    from Connectors.binance_connector import BinanceClient
from Moduls.data_modul import *
from strategies import intervals_to_sec
from datetime import datetime

# Helpful Functions
def get_contracts(clients: Dict[str, 'BinanceClient']) -> Dict[str, Contract]:
    contracts = dict()
    for exchange, client in clients.items():
        contracts.update(
            {f"{exchange} {symbol}": contract 
             for symbol, contract in client.contracts.items()}
        )
    return contracts


def nav_bar():
    nav_bar = dbc.Navbar(dbc.Container([
        html.A('AMGED', className='navbar-brand'), 
        dbc.NavbarToggler(id="navbar-toggler", n_clicks=0),
        dbc.Collapse(),
        ], fluid=True))
    return nav_bar
    

def upper_container(clients: Dict[str, 'BinanceClient']):
    contracts = get_contracts(clients)
    watchlist_contracts = html.Div([
        html.Div(html.Label('Contract'), className="col-auto"),
        html.Div(dcc.Dropdown(options=list(contracts.keys()),
                              value=None, 
                              id="watchlist-select"),
                 className="col")],
                                   className="row my-3")
    
    watchlist_contracts = html.Div(watchlist_contracts, 
                                   className="col-5 container-fluid")
    
    strategy_component = html.Div(strategy_selector(contracts),
                                  className="col-7 container-fluid text-center", 
                                  id="right-window-upper")
    
    container = html.Div([watchlist_contracts, strategy_component],
                          className="row pt-3 container-fluid up-container")
    return container


def strategy_selector(contracts):
    contracts_dropmenu = html.Div(
        [html.Span("Contract"),
         dbc.Select(options=list(contracts.keys()),
                    value=None, id="strategy-contracts",
                    class_name="small-font")],
        className="col-3 strategy-component ms-4")
    
    entry_pct = html.Div(
        [html.Span("Entry pct"),
         dbc.Input(type='number', id="entry-pct", 
                   class_name="form-control small-font")],
        className="col-1 strategy-component"
    )
    
    tp_entry = html.Div(
        [html.Span("TP"),
         dbc.Input(type='number', id="take-profit", 
                   class_name="form-control small-font")],
        className="col-1 strategy-component"
    )
    
    tp_entry = html.Div(
        [html.Span("TP"),
         dbc.Input(type='number', id="take-profit", 
                   class_name="form-control small-font")],
        className="col-1 strategy-component"
    )
    
    sl_entry = html.Div(
        [html.Span("SL"),
         dbc.Input(type='number', id="stop-loss", 
                   class_name="form-control small-font")],
        className="col-1 strategy-component"
    )
    
    strategy = html.Div(
        [html.Span("Strategy"),
         dbc.Select(options=['Technical'],
                    value='Technical', id="strategy-select",
                    class_name="from-select small-font")],
        className="col-2 strategy-component"
    )
    
    buttons = dbc.ButtonGroup(
        [
            dbc.Button("Extra Param", id="extra-param-btn", n_clicks=0,
                       outline=True, color="secondary", className="me-1"),
            dbc.Button(html.I(className="bi bi-bag-plus-fill"),
                       outline=True, color="secondary", className="me-1",
                       id="strategy-add", n_clicks=0)
        ], class_name="btn-group btn-group-sm col-3 strategy-component"
    )
    
    strategy_component = dbc.Form([contracts_dropmenu, entry_pct, tp_entry,
                                   sl_entry, strategy, buttons],
                                   class_name="row new-strategy"),
    return strategy_component
    

def middel_container():
    custom_table = partial(dash_table.DataTable,
                           fixed_rows={"headers": True},
                           page_size=100, cell_selectable=True,
                           style_table={'height': '20rem', 'overflowY': 'auto'},
                           style_cell={'textAlign': 'center'},
                           style_header={'fontWeight': 'bold', 'backgroundColor': 'white',},
                           style_as_list_view=True)
    
    # left table
    columns = ["symbol", "exchange", "bidPrice", "askPrice"]
    data = pd.DataFrame(index=["id"], columns=columns)
    
    watchlist_table = custom_table(data=data.to_dict("records"),
                                   columns=[{"name": i, "id": i} 
                                            for i in data.columns])
    
    columns = ['Exchange', "Symbol", "Qty", "Entry Price", "Current Price", "uPnl", " ", "  "]
    data = pd.DataFrame(index=["id"], columns=columns)
    
    strategy_table = custom_table(data=data.to_dict("records"),
                                  columns=[{"name": i, "id": i}  for i in data.columns],
                                  id="uPnL-table")
    
    mid_container = html.Div([
        html.Div(watchlist_table, className='col-5'),
        html.Div(strategy_table, className='col-7')],
                             className="row pt-3 container-fluid mid-container")
    return mid_container
    
    
def bottom_container():
    logs_list = html.Div(html.Ol(children=[],
                                 id='logs-list',
                                 className="list-group"),
                         className="logs-list")
    
    left = html.Div([html.H3("Logs"), logs_list],
                    className="col-5 logs-container text-justify")
    
    container = html.Div([left], 
                         className="row pt-3 container-fluid h-100", 
                         id="bottom-container")
    return container


def footer():
    facebook = html.A(html.I(className="fab fa-facebook-f"),
                      className="btn text-white btn-floating m-1 facebook")
    
    twitter = html.A(html.I(className="fab fa-twitter"),
                     className="btn text-white btn-floating m-1 twitter")
    
    google = html.A(html.I(className="fab fa-google"),
                    className="btn text-white btn-floating m-1 google")
    
    instagram = html.A(html.I(className="fab fa-instagram"),
                       className="btn text-white btn-floating m-1 instagram")
    
    linkedin = html.A(html.I(className="fab fa-linkedin-in"),
                      className="btn text-white btn-floating m-1 linkedin")
    
    github = html.A(html.I(className="fab fa-github"),
                    className="btn text-white btn-floating m-1 github")
    
    container = html.Div([
        html.Span(f"© Copyright {datetime.now().year} Amged. Created using Plotly Dash",
                  className="text-dark"),
        html.Section([facebook, twitter, google, instagram, linkedin, github],
                     className="container p-1 pb-0")])
    
    container = html.Footer(container,
                            className="bg-light text-center pb-3 fixed-bottom")
    return container


def technical_modal():
    def technicl_modal_component(title: str, indicators: List[str]):
        int_input = partial(dbc.Input, type="number", value=1, 
                            step=1, min=1)
        
        indicator_entry = []
        for indicator in indicators:
            text = dbc.InputGroupText(indicator)
            input_ = int_input(value=1, 
                            id=indicator.replace(" ","-").lower())
            indicator_entry.append(dbc.InputGroup([text, input_],
                                                  className="mb-3"))
        indicator_component = html.Div([html.H2(title), *indicator_entry])
        return indicator_component
    
    ema_component = technicl_modal_component(
        'EMA', ['fast EMA', 'slow EMA']
        )
    macd_component = technicl_modal_component(
        "MACD", ["fast MACD", "slow MACD", "MACD signal"]
        )
    rsi_component = technicl_modal_component(
        "RSI", ["RSI period",]
    )
    
    modal = dbc.Modal([
        dbc.ModalHeader(dbc.ModalTitle("Technical Strategy Parameters")),
        dbc.ModalBody([ema_component, macd_component, rsi_component]),
        dbc.ModalFooter(dbc.Button("Close", id="technical-modal-close",
                                   className="ms-auto", n_clicks=0))],
                      id="technical-modal",
                      is_open=False)
    return modal


@dash.callback(Output(component_id="technical-modal", component_property="is_open"),
          Input(component_id="technical-modal-close", component_property="n_clicks"),
          Input(component_id="extra-param-btn", component_property="n_clicks"),
          State(component_id="strategy-select", component_property="value"),
          State(component_id="technical-modal", component_property="is_open"))
def open_modal(close_btn, open_btn, strategy: str, modal_state: bool):
    if open_btn==0:
        return False
    elif modal_state:
        return False
    elif strategy == "Technical":
        return True