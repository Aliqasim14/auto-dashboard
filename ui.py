import io
import json
import dash
from dash import dcc, html, Input, Output, State, ctx, ALL
from analysis import parse_upload, profile_columns, get_kpis, build_charts, apply_filters

app = dash.Dash(__name__, title="Auto Dashboard", suppress_callback_exceptions=True)
server = app.server

BG    = "#f5f7fb"
WHITE = "#ffffff"

def card(extra=None):
    base = {"background": WHITE, "border": "1px solid #eee", "borderRadius": "12px",
            "padding": "16px", "boxShadow": "0 2px 8px rgba(0,0,0,.05)"}
    if extra:
        base.update(extra)
    return base

def kpi_card_el(label, value, sub):
    return html.Div([
        html.P(label, style={"margin": 0, "fontSize": "11px", "color": "#888",
                              "fontWeight": "600", "textTransform": "uppercase"}),
        html.H3(value, style={"margin": "4px 0 2px", "fontSize": "21px",
                               "fontWeight": "700", "color": "#1a1a2e"}),
        html.P(sub, style={"margin": 0, "fontSize": "11px", "color": "#aaa"}),
    ], style={**card(), "flex": "1", "minWidth": "140px", "padding": "14px 18px"})

upload_zone = html.Div([
    dcc.Upload(
        id="upload",
        children=html.Div([
            html.Div("📂", style={"fontSize": "48px", "marginBottom": "12px"}),
            html.B("Drag & drop your file here"),
            html.Br(),
            html.Span("or click to browse", style={"color": "#888", "fontSize": "13px"}),
            html.Br(), html.Br(),
            html.Span("Supported: .csv  .xlsx  .xls  .tsv  .txt",
                      style={"fontSize": "12px", "color": "#aaa", "background": "#f0f0f0",
                             "padding": "4px 10px", "borderRadius": "20px"}),
        ]),
        style={"width": "100%", "minHeight": "220px", "border": "2px dashed #c0cfe8",
               "borderRadius": "16px", "display": "flex", "alignItems": "center",
               "justifyContent": "center", "textAlign": "center", "cursor": "pointer",
               "background": "#f8faff"},
        multiple=False,
    ),
    html.Div(id="upload-status", style={"marginTop": "12px", "textAlign": "center", "fontSize": "13px"}),
], style={"maxWidth": "560px", "margin": "60px auto 0"})

app.layout = html.Div(
    style={"fontFamily": "Segoe UI, sans-serif", "background": BG,
           "minHeight": "100vh", "padding": "28px 32px"},
    children=[
        dcc.Store(id="store-data"),
        dcc.Store(id="store-profile"),
        html.Div([
            html.H1("Auto Dashboard", style={"margin": 0, "fontSize": "26px",
                                              "fontWeight": "700", "color": "#1a1a2e"}),
            html.P("Upload any CSV or Excel file — charts build automatically.",
                   style={"margin": "4px 0 0", "color": "#888", "fontSize": "13px"}),
        ], style={"marginBottom": "28px"}),
        html.Div(id="upload-area", children=upload_zone),
        html.Div(id="dashboard", style={"display": "none"}, children=[
            html.Div([
                html.Div(id="file-info", style={"fontSize": "13px", "color": "#555"}),
                html.Button("↩ Upload new file", id="btn-reset",
                            style={"marginLeft": "auto", "padding": "6px 16px",
                                   "fontSize": "12px", "border": "1px solid #c0cfe8",
                                   "borderRadius": "8px", "background": WHITE,
                                   "cursor": "pointer", "color": "#378ADD"}),
            ], style={"display": "flex", "alignItems": "center", "marginBottom": "20px"}),
            html.Div(id="filters-row", style={"display": "flex", "gap": "14px",
                                               "flexWrap": "wrap", "marginBottom": "22px",
                                               "alignItems": "flex-end"}),
            html.Div(id="kpi-row", style={"display": "flex", "gap": "14px",
                                           "flexWrap": "wrap", "marginBottom": "22px"}),
            html.Div(id="charts-grid"),
        ]),
    ],
)


@app.callback(
    Output("store-data",    "data"),
    Output("store-profile", "data"),
    Output("upload-status", "children"),
    Input("upload", "contents"),
    State("upload", "filename"),
    prevent_initial_call=True,
)
def store_upload(contents, filename):
    if not contents:
        return dash.no_update, dash.no_update, ""
    try:
        import pandas as pd
        df      = parse_upload(contents, filename)
        profile = profile_columns(df)
        df_json = df.copy()
        for col in profile["datetime"]:
            df_json[col] = df_json[col].astype(str)
        return (
            df_json.to_json(date_format="iso", orient="split"),
            json.dumps(profile),
            html.Span(f"✅ '{filename}' loaded — {len(df):,} rows × {len(df.columns)} columns",
                      style={"color": "#1D9E75", "fontWeight": "600"}),
        )
    except Exception as e:
        return None, None, html.Span(f"❌ {e}", style={"color": "#D85A30"})


@app.callback(
    Output("upload-area", "style"),
    Output("dashboard",   "style"),
    Input("store-data",   "data"),
    Input("btn-reset",    "n_clicks"),
)
def toggle_panels(data, _reset):
    if ctx.triggered_id == "btn-reset" or not data:
        return {"display": "block"}, {"display": "none"}
    return {"display": "none"}, {"display": "block"}


@app.callback(
    Output("file-info",   "children"),
    Output("filters-row", "children"),
    Output("kpi-row",     "children"),
    Output("charts-grid", "children"),
    Input("store-data",    "data"),
    Input("store-profile", "data"),
    prevent_initial_call=True,
)
def build_dashboard(data_json, profile_json):
    if not data_json or not profile_json:
        return "", [], [], []

    import pandas as pd
    df      = pd.read_json(io.StringIO(data_json), orient="split")
    profile = json.loads(profile_json)

    for col in profile["datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    info = html.Span([
        html.B(f"{len(df):,} rows"),
        f" · {len(df.columns)} columns · "
        f"{len(profile['numeric'])} numeric · "
        f"{len(profile['categoric'])} categorical · "
        f"{len(profile['datetime'])} date",
    ])

    filters = []
    for col in profile["categoric"][:4]:
        unique_vals = sorted(df[col].dropna().astype(str).unique())
        opts = [{"label": "All", "value": "All"}] + \
               [{"label": v, "value": v} for v in unique_vals]
        filters.append(html.Div([
            html.Label(col, style={"fontSize": "11px", "color": "#888", "display": "block",
                                   "marginBottom": "4px", "fontWeight": "600",
                                   "textTransform": "uppercase"}),
            dcc.Dropdown(id={"type": "filter-dd", "col": col}, options=opts,
                         value="All", clearable=False, style={"width": "180px", "fontSize": "13px"}),
        ]))

    kpis    = get_kpis(df, profile)
    kpi_els = [kpi_card_el(k["label"], k["value"], k["sub"]) for k in kpis]

    charts    = build_charts(df, profile)
    n         = len(charts)
    chart_els = []
    i = 0
    while i < n:
        if (n - i) == 1:
            chart_els.append(html.Div(
                html.Div(dcc.Graph(figure=charts[i][1], config={"displayModeBar": False},
                                   style={"height": "340px"}),
                         style=card({"marginBottom": "16px"}))
            ))
            i += 1
        else:
            chart_els.append(html.Div([
                html.Div(dcc.Graph(figure=charts[i][1], config={"displayModeBar": False},
                                   style={"height": "320px"}), style=card()),
                html.Div(dcc.Graph(figure=charts[i+1][1], config={"displayModeBar": False},
                                   style={"height": "320px"}), style=card()),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                      "gap": "16px", "marginBottom": "16px"}))
            i += 2

    return info, filters, kpi_els, chart_els


@app.callback(
    Output("kpi-row",     "children", allow_duplicate=True),
    Output("charts-grid", "children", allow_duplicate=True),
    Input({"type": "filter-dd", "col": ALL}, "value"),
    State({"type": "filter-dd", "col": ALL}, "id"),
    State("store-data",    "data"),
    State("store-profile", "data"),
    prevent_initial_call=True,
)
def apply_filter_changes(filter_values, filter_ids, data_json, profile_json):
    if not data_json or not profile_json or not filter_ids:
        return dash.no_update, dash.no_update

    import pandas as pd
    df      = pd.read_json(io.StringIO(data_json), orient="split")
    profile = json.loads(profile_json)

    for col in profile["datetime"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")

    fv = {fid["col"]: val for fid, val in zip(filter_ids, filter_values)}
    df = apply_filters(df, fv)

    kpis    = get_kpis(df, profile)
    kpi_els = [kpi_card_el(k["label"], k["value"], k["sub"]) for k in kpis]

    charts    = build_charts(df, profile)
    n         = len(charts)
    chart_els = []
    i = 0
    while i < n:
        if (n - i) == 1:
            chart_els.append(html.Div(
                html.Div(dcc.Graph(figure=charts[i][1], config={"displayModeBar": False},
                                   style={"height": "340px"}),
                         style=card({"marginBottom": "16px"}))
            ))
            i += 1
        else:
            chart_els.append(html.Div([
                html.Div(dcc.Graph(figure=charts[i][1], config={"displayModeBar": False},
                                   style={"height": "320px"}), style=card()),
                html.Div(dcc.Graph(figure=charts[i+1][1], config={"displayModeBar": False},
                                   style={"height": "320px"}), style=card()),
            ], style={"display": "grid", "gridTemplateColumns": "1fr 1fr",
                      "gap": "16px", "marginBottom": "16px"}))
            i += 2

    return kpi_els, chart_els


if __name__ == "__main__":
    app.run(debug=False)
