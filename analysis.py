"""
analysis.py
-----------
Smart data loader and chart builder that works with ANY CSV / Excel file.
Auto-detects numeric, categorical, and date columns — no hardcoding needed.
Imported by ui.py — do NOT run this file directly.
"""

import io
import base64
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ── Color palette
BLUE   = "#378ADD"
GREEN  = "#1D9E75"
CORAL  = "#D85A30"
PINK   = "#D4537E"
AMBER  = "#BA7517"
PURPLE = "#533AB7"
GRAY   = "#B4B2A9"
COLORS = [BLUE, GREEN, CORAL, PINK, AMBER, PURPLE, GRAY]

CHART_LAYOUT = dict(
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    font=dict(family="Segoe UI, sans-serif", size=12, color="#444"),
    margin=dict(l=10, r=10, t=44, b=10),
    legend=dict(orientation="h", y=-0.22, x=0),
)


# ── Number formatter
def fmt_number(v):
    """Format large numbers compactly: 1200000 → 1.2M, 34000 → 34K."""
    try:
        v = float(v)
        if abs(v) >= 1e9: return f"{v/1e9:.1f}B"
        if abs(v) >= 1e6: return f"{v/1e6:.1f}M"
        if abs(v) >= 1e3: return f"{v/1e3:.0f}K"
        return f"{v:,.2f}"
    except Exception:
        return str(v)


# ── Parse uploaded file
def parse_upload(contents, filename):
    """
    Decode a Dash Upload component base64 payload.
    Supports: .csv, .xlsx, .xls, .tsv, .txt (tab-delimited)
    Returns a cleaned DataFrame or raises ValueError with a friendly message.
    """
    content_type, content_string = contents.split(",", 1)
    decoded = base64.b64decode(content_string)
    fname   = filename.lower()

    try:
        if fname.endswith((".csv", ".txt")):
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    df = pd.read_csv(io.StringIO(decoded.decode(enc)))
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Could not decode file. Try saving it as UTF-8.")

        elif fname.endswith(".tsv"):
            for enc in ("utf-8", "latin-1", "cp1252"):
                try:
                    df = pd.read_csv(io.StringIO(decoded.decode(enc)), sep="\t")
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Could not decode TSV. Try saving it as UTF-8.")

        elif fname.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(decoded))

        else:
            raise ValueError(
                f"Unsupported format: '{filename}'. "
                "Please upload a .csv, .xlsx, .xls, .tsv, or .txt file."
            )

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Could not read '{filename}': {e}")

    if df.empty:
        raise ValueError("The uploaded file appears to be empty.")

    return clean_dataframe(df)


# ── Generic cleaner
def clean_dataframe(df):
    """
    Universal cleaning pipeline:
    - Strip whitespace from column names and string cells
    - Auto-convert currency / percentage strings to float
    - Parse obvious date columns
    - Drop fully empty rows / columns
    """
    df = df.copy()
    df.columns = df.columns.str.strip()
    df.dropna(how="all", inplace=True)
    df.dropna(axis=1, how="all", inplace=True)

    for col in df.select_dtypes("object").columns:
        df[col] = df[col].astype(str).str.strip()

        # Detect currency / numeric strings → float
        sample = df[col].dropna().head(30)
        looks_currency = (
            sample.str.match(r"^\(?[\$€£¥]?\s*-?[\d,]+(\.\d+)?\)?%?$").mean() > 0.5
        )
        if looks_currency:
            converted = (
                df[col]
                .str.replace(r"[\$€£¥,%\s]", "", regex=True)
                .str.replace(r"\((.+)\)", r"-\1", regex=True)
                .pipe(pd.to_numeric, errors="coerce")
            )
            if converted.notna().mean() > 0.5:
                df[col] = converted
                continue

        # Detect and parse date columns by name keywords
        if any(kw in col.lower() for kw in ("date","time","month","year","day","period","week")):
            try:
                parsed = pd.to_datetime(df[col], errors="coerce", infer_datetime_format=True)
                if parsed.notna().mean() > 0.5:
                    df[col] = parsed
            except Exception:
                pass

    return df


# ── Column profiler
def profile_columns(df):
    """
    Auto-detect what each column is useful for.

    Returns dict with lists:
        numeric   → good for sums / averages / KPIs
        categoric → low-cardinality strings → filters / group-by axes
        datetime  → datetime columns → time series
        text      → high-cardinality strings (IDs, free text) → skip
    """
    numeric   = []
    categoric = []
    datetime  = []
    text      = []

    for col in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            datetime.append(col)
        elif pd.api.types.is_numeric_dtype(df[col]):
            n_unique = df[col].nunique()
            # Skip pure row-ID columns (all unique, sequential integers)
            if n_unique == len(df) and df[col].min() >= 0:
                text.append(col)
            else:
                numeric.append(col)
        else:
            n_unique = df[col].nunique()
            ratio    = n_unique / max(len(df), 1)
            if n_unique <= 60 or ratio < 0.05:
                categoric.append(col)
            else:
                text.append(col)

    return {
        "numeric":   numeric,
        "categoric": categoric,
        "datetime":  datetime,
        "text":      text,
    }


#  KPI builder 
def get_kpis(df, profile):
    """
    Return list of KPI dicts [{label, value, sub}] based on detected columns.
    Always shows row count; adds up to 4 numeric column summaries.
    """
    kpis = [
        {
            "label": "Total Rows",
            "value": f"{len(df):,}",
            "sub":   f"{len(df.columns)} columns",
        }
    ]
    for col in profile["numeric"][:4]:
        total = df[col].sum()
        mean  = df[col].mean()
        kpis.append({
            "label": col,
            "value": fmt_number(total),
            "sub":   f"avg {fmt_number(mean)}",
        })
    return kpis


# Smart chart builder
def build_charts(df, profile):
    """
    Automatically generate the best charts for the given data profile.
    Returns list of (title_str, plotly_Figure).
    """
    charts    = []
    numeric   = profile["numeric"]
    categoric = profile["categoric"]
    datetime  = profile["datetime"]

    if not numeric:
        fig = go.Figure()
        fig.update_layout(title="No numeric columns detected in this file.", **CHART_LAYOUT)
        return [("No numeric data", fig)]

    num1 = numeric[0]
    num2 = numeric[1] if len(numeric) > 1 else None
    cat1 = categoric[0] if len(categoric) > 0 else None
    cat2 = categoric[1] if len(categoric) > 1 else None
    cat3 = categoric[2] if len(categoric) > 2 else None

    # Chart 1: Bar — primary numeric × first categorical
    if cat1:
        agg = (
            df.groupby(cat1)[num1]
              .sum().reset_index()
              .sort_values(num1, ascending=False)
              .head(15)
        )
        fig = px.bar(agg, x=cat1, y=num1,
                     title=f"Total {num1} by {cat1}",
                     color=cat1, color_discrete_sequence=COLORS)
        fig.update_layout(**CHART_LAYOUT, showlegend=False)
        fig.update_traces(marker_line_width=0)
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor="#f0f0f0")
        charts.append((f"{num1} by {cat1}", fig))

    # Chart 2: Donut (second categorical) or horizontal bar (second numeric)
    if cat2:
        agg = df.groupby(cat2)[num1].sum().reset_index()
        fig = px.pie(agg, names=cat2, values=num1,
                     title=f"{num1} share by {cat2}",
                     color_discrete_sequence=COLORS, hole=0.52)
        fig.update_layout(**CHART_LAYOUT)
        fig.update_traces(textposition="outside", textinfo="label+percent")
        charts.append((f"{num1} by {cat2}", fig))
    elif cat1 and num2:
        agg = df.groupby(cat1)[num2].sum().reset_index().sort_values(num2)
        fig = px.bar(agg, y=cat1, x=num2,
                     title=f"{num2} by {cat1}",
                     orientation="h", color=cat1,
                     color_discrete_sequence=COLORS)
        fig.update_layout(**CHART_LAYOUT, showlegend=False)
        fig.update_traces(marker_line_width=0)
        fig.update_xaxes(gridcolor="#f0f0f0")
        fig.update_yaxes(showgrid=False)
        charts.append((f"{num2} by {cat1}", fig))

    # Chart 3: Time series
    if datetime:
        dt_col = datetime[0]
        df2    = df.copy()
        df2["__period__"] = df2[dt_col].dt.to_period("M").astype(str)
        group_cols = ["__period__"] + ([cat1] if cat1 else [])
        trend = df2.groupby(group_cols)[num1].sum().reset_index()
        trend = trend.sort_values("__period__")
        trend.rename(columns={"__period__": "Period"}, inplace=True)

        if cat1:
            fig = px.line(trend, x="Period", y=num1, color=cat1,
                          title=f"{num1} over Time by {cat1}",
                          markers=True, color_discrete_sequence=COLORS)
        else:
            fig = px.line(trend, x="Period", y=num1,
                          title=f"{num1} over Time",
                          markers=True, color_discrete_sequence=[BLUE])
        fig.update_layout(**CHART_LAYOUT)
        fig.update_xaxes(showgrid=False, tickangle=-30)
        fig.update_yaxes(gridcolor="#f0f0f0")
        charts.append((f"{num1} over Time", fig))

    # Chart 4: Scatter — two numeric columns
    if num2:
        sample = df.sample(min(500, len(df)), random_state=42)
        scatter_kwargs = dict(x=num1, y=num2, opacity=0.65,
                              title=f"{num1} vs {num2}",
                              color_discrete_sequence=COLORS)
        if cat1:
            scatter_kwargs["color"] = cat1
        fig = px.scatter(sample, **scatter_kwargs)
        fig.update_layout(**CHART_LAYOUT)
        fig.update_xaxes(gridcolor="#f0f0f0")
        fig.update_yaxes(gridcolor="#f0f0f0")
        charts.append((f"{num1} vs {num2}", fig))

    # Chart 5: Histogram — distribution of primary numeric
    fig = px.histogram(df, x=num1, nbins=30,
                       title=f"Distribution of {num1}",
                       color_discrete_sequence=[BLUE])
    fig.update_layout(**CHART_LAYOUT, showlegend=False)
    fig.update_traces(marker_line_width=0)
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#f0f0f0", title="Count")
    charts.append((f"{num1} Distribution", fig))

    # Chart 6: Third categorical breakdown
    if cat3:
        agg = df.groupby(cat3)[num1].sum().reset_index().sort_values(num1)
        fig = px.bar(agg, y=cat3, x=num1,
                     title=f"{num1} by {cat3}",
                     orientation="h", color=cat3,
                     color_discrete_sequence=COLORS)
        fig.update_layout(**CHART_LAYOUT, showlegend=False)
        fig.update_traces(marker_line_width=0)
        fig.update_xaxes(gridcolor="#f0f0f0")
        fig.update_yaxes(showgrid=False)
        charts.append((f"{num1} by {cat3}", fig))

    return charts


#Filter helper 
def apply_filters(df, filter_values):
    """
    Apply dropdown filter selections to the dataframe.
    filter_values: dict of {col_name: selected_value}
    """
    d = df.copy()
    for col, val in filter_values.items():
        if val and val != "All" and col in d.columns:
            d = d[d[col].astype(str) == str(val)]
    return d