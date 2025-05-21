import re
import os
import pandas as pd
import plotly.express as px
from dash import Dash, dcc, html, Input, Output, State
import dash_bootstrap_components as dbc
from datetime import datetime
import subprocess

app = Dash(__name__, external_stylesheets=[dbc.themes.BOOTSTRAP])

def generate_default_coord_variables(custom_variable: str):
    base_pairs = {
        'OrigTgX': 'OrigTgY',
        'FusionX': 'FusionY',
        'KalmanTgX': 'KalmanTgY',
        'WX': 'WY',
        'LXW': 'LYW',
        'RWX': 'RWY',
        'current_coord.x': 'current_coord.y'
    }

    if custom_variable:
        custom_variable = custom_variable.strip()
        if custom_variable not in base_pairs:
            if custom_variable.endswith('X'):
                base_pairs[custom_variable] = custom_variable[:-1] + 'Y'
            else:
                base_pairs[custom_variable] = custom_variable + 'Y'

        if len(custom_variable) == 1 and custom_variable.isalpha():
            base_pairs['R' + custom_variable] = 'R' + custom_variable + 'Y'

    return base_pairs

def run_grep_on_file(file_path):
    git_bash_path = r"C:\Program Files\Git\bin\bash.exe"
    escaped_path = file_path.replace('\\', '/')
    pattern = r"'RX [0-9]+ RY [0-9]+ TX [0-9]+ TY [0-9]+'"
    command = [
        git_bash_path,
        "-c",
        f"grep -n -E {pattern} {escaped_path}"
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        matched_lines = []
        for line in result.stdout.strip().split('\n'):
            if not line:
                continue
            line_num_str, line_text = line.split(':', 1)
            matched_lines.append((int(line_num_str), line_text.strip()))
        return matched_lines, None
    except subprocess.CalledProcessError as e:
        if e.returncode == 1:
            return [], None
        return [], f"Error running grep: {e}"
    except Exception as e:
        return [], f"Unexpected error: {e}"

def parse_log_file_from_path(file_path):
    matched_lines, err = run_grep_on_file(file_path)
    if err:
        return {}, [], err
    try:
        with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.readlines()
    except Exception as e:
        return {}, [], f"Error reading file: {str(e)}"

    sector_data = {}
    labels = []
    if not matched_lines:
        return {}, [], "No sectors found matching pattern."

    for idx, (start_line_num, matched_line) in enumerate(matched_lines):
        sector_name = f"Sector {idx+1}"
        start_idx = start_line_num - 1
        end_idx = matched_lines[idx + 1][0] - 1 if idx + 1 < len(matched_lines) else len(lines)
        sector_lines = [line.strip() for line in lines[start_idx:end_idx]]
        sector_data[sector_name] = sector_lines
        labels.append({
            'label': f"{sector_name} - Line {start_line_num}: {matched_line[:60]}",
            'value': sector_name
        })

    return sector_data, labels, f"✅ Loaded {len(sector_data)} sector(s)."

def process_sector(lines, custom_var=None, coord_variables=None):
    data, coord_data = [], []
    variables, coord_names = set(), set()
    custom_variable = custom_var.strip() if custom_var else None
    coord_vars = coord_variables if coord_variables else {}

    for line_num, line in enumerate(lines, start=1):
        match = re.match(r'(\d{2}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(.*)', line)
        if not match:
            continue
        timestamp, content = match.groups()
        try:
            dt = datetime.strptime(timestamp, '%d/%m/%y %H:%M:%S.%f')
        except ValueError:
            continue

        pairs = re.findall(r'([\w.]+)\s*[:=]\s*([-\d.]+)', content)
        parsed_values = {}

        for var, val in pairs:
            try:
                val = float(val)
                parsed_values[var] = val
                data.append({'timestamp': timestamp, 'datetime': dt, 'line_number': line_num, 'variable': var, 'value': val})
                variables.add(var)
            except ValueError:
                continue

        if custom_variable:
            pattern = rf'{re.escape(custom_variable)}\s+([-\d.]+)'
            match_custom = re.search(pattern, content)
            if match_custom:
                try:
                    val = float(match_custom.group(1))
                    data.append({'timestamp': timestamp, 'datetime': dt, 'line_number': line_num, 'variable': custom_variable, 'value': val})
                    variables.add(custom_variable)
                except ValueError:
                    pass

        for x_var, y_var in coord_vars.items():
            if x_var in parsed_values and y_var in parsed_values:
                try:
                    x_val = parsed_values[x_var]
                    y_val = parsed_values[y_var]
                    coord_name = f"{x_var[:-1]}_Coords" if x_var.endswith('X') else f"{x_var}_Coords"
                    coord_data.append({'timestamp': timestamp, 'datetime': dt, 'line_number': line_num, 'coord_name': coord_name, 'x': x_val, 'y': y_val})
                    coord_names.add(coord_name)
                except ValueError:
                    continue

    return pd.DataFrame(data), pd.DataFrame(coord_data), sorted(variables), sorted(coord_names)

# UI Layout
app.layout = dbc.Container([
    dbc.Row(dbc.Col(html.H2("Log File Visualizer with Dynamic Coordinate Variables"), className="my-3")),
    dbc.Row([
        dbc.Col(dbc.Input(id='file-path', placeholder="Enter full log file path here", type='text'), width=7),
        dbc.Col(dbc.Input(id='custom-var', placeholder="Custom variable (e.g., RX)", type='text'), width=3),
        dbc.Col([
            dbc.Button("Process", id='process-btn', color="primary"),
            html.Div(id="file-info", className="mt-2")
        ], width=2)
    ], className="mb-4"),

    dbc.Row([
        dbc.Col([
            html.Label("Select Sector:"),
            dcc.Dropdown(id='sector-dropdown', style={'marginBottom': '15px'})
        ])
    ]),

    dcc.Tabs([
        dcc.Tab(label='Time Series Plot', children=[
            html.Div([
                html.Label("Select Variables:"),
                dcc.Dropdown(id='variable-selector', multi=True),
                dbc.Checklist(
                    options=[{"label": "Swap X and Y axis", "value": "swap"}],
                    value=[],
                    id="ts-swap-toggle",
                    inline=True,
                    switch=True,
                    style={'marginTop': '10px'}
                ),
            ], style={'margin': '10px'}),
            dcc.Graph(id='time-series-plot')
        ]),
        dcc.Tab(label='Coordinate Plot', children=[
            html.Div([
                html.Label("Select Coordinate Set:"),
                dcc.Dropdown(id='coord-selector', multi=True),
                dbc.Checklist(
                    options=[{"label": "Swap X and Y axis", "value": "swap"}],
                    value=[],
                    id="coord-swap-toggle",
                    inline=True,
                    switch=True,
                    style={'marginTop': '10px'}
                ),
            ], style={'margin': '10px'}),
            dcc.Graph(id='coord-plot')
        ])
    ]),

    dcc.Store(id='sector-data'),
    dcc.Store(id='sector-coord-data'),
    dcc.Store(id='all-sectors'),
    dcc.Store(id='custom-var-store'),
    dcc.Store(id='coord-vars-store')
], fluid=True)

@app.callback(
    Output('all-sectors', 'data'),
    Output('sector-dropdown', 'options'),
    Output('file-info', 'children'),
    Output('custom-var-store', 'data'),
    Output('coord-vars-store', 'data'),
    Input('process-btn', 'n_clicks'),
    State('file-path', 'value'),
    State('custom-var', 'value')
)
def process_file(n, file_path, custom_var):
    if not file_path:
        return {}, [], " No file path provided.", custom_var, {}
    cleaned_path = file_path.strip().strip('"')
    if not os.path.exists(cleaned_path):
        return {}, [], f" File not found: {cleaned_path}", custom_var, {}
    sectors, labels, info = parse_log_file_from_path(cleaned_path)
    coord_vars = generate_default_coord_variables(custom_var)
    return sectors, labels, info, custom_var, coord_vars

@app.callback(
    Output('sector-data', 'data'),
    Output('sector-coord-data', 'data'),
    Output('variable-selector', 'options'),
    Output('coord-selector', 'options'),
    Input('sector-dropdown', 'value'),
    State('all-sectors', 'data'),
    State('custom-var-store', 'data'),
    State('coord-vars-store', 'data')
)
def update_sector_data(selected_sector, all_sectors, custom_var, coord_vars):
    if not selected_sector or selected_sector not in all_sectors:
        return None, None, [], []
    lines = all_sectors[selected_sector]
    df_data, df_coords, vars_list, coord_list = process_sector(lines, custom_var, coord_vars)
    var_options = [{"label": v, "value": v} for v in vars_list]
    coord_options = [{"label": c, "value": c} for c in coord_list]
    return df_data.to_dict('records'), df_coords.to_dict('records'), var_options, coord_options

@app.callback(
    Output('time-series-plot', 'figure'),
    Input('sector-data', 'data'),
    Input('variable-selector', 'value'),
    Input('ts-swap-toggle', 'value')
)
def update_time_series_plot(data, selected_vars, swap_toggle):
    if not data or not selected_vars:
        return {}
    df = pd.DataFrame(data)
    df = df[df['variable'].isin(selected_vars)]

    # Sort data by datetime to ensure correct line connections
    df = df.sort_values('datetime')

    if 'swap' not in swap_toggle:
        # Normal: time on x, value on y
        fig = px.line(df, x='datetime', y='value', color='variable', markers=True)
    else:
        # Swap axes: value on x, time on y
        fig = px.line(df, x='value', y='datetime', color='variable', markers=True)
        fig.update_layout(yaxis_title='Time')

    fig.update_layout(legend_title_text='Variables', margin=dict(l=40, r=20, t=30, b=40))
    return fig

@app.callback(
    Output('coord-plot', 'figure'),
    Input('sector-coord-data', 'data'),
    Input('coord-selector', 'value'),
    Input('coord-swap-toggle', 'value')
)
def update_coord_plot(coord_data, selected_coords, swap_toggle):
    if not coord_data or not selected_coords:
        return {}
    df = pd.DataFrame(coord_data)
    df = df[df['coord_name'].isin(selected_coords)]

    fig = px.scatter(df, x='x', y='y', color='coord_name')

    if 'swap' in swap_toggle:
        fig = px.scatter(df, x='y', y='x', color='coord_name')
        fig.update_layout(xaxis_title='Y', yaxis_title='X')
    else:
        fig.update_layout(xaxis_title='X', yaxis_title='Y')

    fig.update_layout(legend_title_text='Coordinate Sets', margin=dict(l=40, r=20, t=30, b=40), height=600)
    return fig

if __name__ == '__main__':
    app.run(debug=True)
