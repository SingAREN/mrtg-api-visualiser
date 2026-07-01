import os
import re
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from data_collector import fetch_mrtg_data

CACHE_FILE = "mrtg_data.csv"
CHART_HEIGHT = 800

st.set_page_config(page_title="Network Utilisation Dashboard", layout="wide")
st.title("🌐 Network Interface Utilisation Dashboard")


# --- Helper Functions ---
def speed_to_numeric(speed_str):
    if pd.isna(speed_str) or speed_str == "Unknown":
        return 1_000_000.0
    match = re.search(r"([\d.]+)\s*([a-zA-Z]+)", str(speed_str))
    if not match:
        return 1_000_000.0
    val, unit = float(match.group(1)), match.group(2).lower()
    if 'g' in unit: return val * 1_000_000_000
    if 'm' in unit: return val * 1_000_000
    if 'k' in unit: return val * 1_000
    return val


def load_cached_data():
    if os.path.exists(CACHE_FILE):
        df = pd.read_csv(CACHE_FILE)
        mtime = os.path.getmtime(CACHE_FILE)
        last_updated = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S")
        return df, last_updated
    return None, None


# --- Data Loading ---
if "df_mrtg" not in st.session_state:
    df_cache, updated_time = load_cached_data()
    if df_cache is not None and not df_cache.empty:
        st.session_state["df_mrtg"] = df_cache
        st.session_state["last_updated"] = updated_time
    else:
        with st.spinner("Fetching initial data from API..."):
            fresh_df = fetch_mrtg_data()
            if not fresh_df.empty: fresh_df.to_csv(CACHE_FILE, index=False)
            st.session_state["df_mrtg"] = fresh_df
            st.session_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

col1, col2 = st.columns([1, 4])
with col1:
    if st.button("🔄 Refresh Data From API"):
        with st.spinner("Fetching fresh data from API..."):
            fresh_df = fetch_mrtg_data()
            fresh_df.to_csv(CACHE_FILE, index=False)
            st.session_state["df_mrtg"] = fresh_df
            st.session_state["last_updated"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            st.rerun()
with col2:
    st.caption(f"**Last Updated:** {st.session_state.get('last_updated', 'Unknown')} (Loaded from cache)")

df = st.session_state["df_mrtg"]

if df.empty:
    st.warning("No data available. Verify connection to the API.")
else:
    # --- Data Pre-Processing ---
    df["Port Capacity (bps)"] = df["Port Speed"].apply(speed_to_numeric)

    # NEW: Create a clean Gbps column for human-readable tooltips
    df["Port Capacity (Gbps)"] = df["Port Capacity (bps)"] / 1_000_000_000

    df["Max Overall Utilisation (%)"] = df[["In Max Utilisation (%)", "Out Max Utilisation (%)"]].max(axis=1)
    df["Avg Overall Utilisation (%)"] = df[["In Avg Utilisation (%)", "Out Avg Utilisation (%)"]].max(axis=1)

    # --- Sidebar Filters ---
    st.sidebar.header("Filters & Toggles")

    # Toggle: Metric Selection
    metric_toggle = st.sidebar.radio(
        "Select Utilisation Metric",
        options=["Max", "Average"],
        index=0,
        help="Switches the primary metric used for standard charts. Burst and Gap charts naturally display both."
    )

    search_query = st.sidebar.text_input("Search Interface Name", value="")
    selected_duration = st.sidebar.selectbox("Select Graph Duration", ["day", "week", "month", "year"], index=0)

    # Multi-select: Device Type
    available_types = df["Type"].unique().tolist()
    selected_types = st.sidebar.multiselect("Filter by Device Type", options=available_types, default=available_types)

    # Multi-select: Device Filter
    available_devices = df["Device"].unique().tolist()
    selected_devices = st.sidebar.multiselect("Filter by Device", options=available_devices, default=available_devices)

    # Map the selected metric to dynamic dataframe columns
    if metric_toggle == "Max":
        col_overall = "Max Overall Utilisation (%)"
        col_in = "In Max Utilisation (%)"
        col_out = "Out Max Utilisation (%)"
    else:
        col_overall = "Avg Overall Utilisation (%)"
        col_in = "In Avg Utilisation (%)"
        col_out = "Out Avg Utilisation (%)"

    # Apply Filters
    filtered_df = df[
        (df["Duration"] == selected_duration) &
        (df["Type"].isin(selected_types)) &
        (df["Device"].isin(selected_devices))
        ]

    if search_query:
        filtered_df = filtered_df[filtered_df["Interface"].str.contains(search_query, case=False, na=False)]

    if not filtered_df.empty:
        tabs = st.tabs([
            "💥 Burst Matrix",
            "🏋️ Gap Analysis",
            "🌪️ Tornado (In/Out)",
            "📊 Directional Bar",
            "📈 Health Histogram",
            "🏆 Top 10 Congested",
            "🗃️ Treemap",
            "🔆 Device Sunburst",
            "🍩 Capacity Donut",
            "📝 Raw Data"
        ])

        # TAB 1: Burst Matrix
        with tabs[0]:
            fig_burst = px.scatter(
                filtered_df, x="Avg Overall Utilisation (%)", y="Max Overall Utilisation (%)",
                color="Type", size="Port Capacity (Gbps)", hover_name="Interface",
                title=f"Burst Matrix: Average vs. Max Traffic ({selected_duration.upper()})",
                height=CHART_HEIGHT,
                size_max=50  # <--- Scales up the absolute maximum size for your 400G links
            )

            # <--- Forces the smallest orbs (e.g., 1G) to never shrink below 6 pixels
            fig_burst.update_traces(marker=dict(sizemin=6))

            max_val = max(filtered_df["Max Overall Utilisation (%)"].max(), 100)
            fig_burst.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val, line=dict(color="gray", dash="dot"))
            fig_burst.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="Critical Burst Line")
            fig_burst.add_vline(x=60, line_dash="dash", line_color="orange", annotation_text="Sustained Warning")
            st.plotly_chart(fig_burst, use_container_width=True)

        # TAB 2: Dumbbell Chart
        with tabs[1]:
            st.subheader(f"Traffic Variance: Top 20 Links by Max ({selected_duration.upper()})")
            dumbbell_df = filtered_df.nlargest(20, 'Max Overall Utilisation (%)').sort_values(
                'Max Overall Utilisation (%)', ascending=True)

            fig_db = go.Figure()
            for i, row in dumbbell_df.iterrows():
                fig_db.add_trace(go.Scatter(
                    x=[row["Avg Overall Utilisation (%)"], row["Max Overall Utilisation (%)"]],
                    y=[row["Interface"], row["Interface"]], mode="lines", line=dict(color="gray", width=2),
                    showlegend=False, hoverinfo="skip"
                ))
            fig_db.add_trace(go.Scatter(
                x=dumbbell_df["Avg Overall Utilisation (%)"], y=dumbbell_df["Interface"], mode="markers",
                name="Average %", marker=dict(color="blue", size=10),
                text=dumbbell_df["Type"], hovertemplate="Avg: %{x}%<br>Type: %{text}"
            ))
            fig_db.add_trace(go.Scatter(
                x=dumbbell_df["Max Overall Utilisation (%)"], y=dumbbell_df["Interface"], mode="markers", name="Max %",
                marker=dict(color="red", size=10),
                text=dumbbell_df["Port Speed"], hovertemplate="Max: %{x}%<br>Speed: %{text}"
            ))
            fig_db.update_layout(xaxis_title="Utilisation (%)", yaxis_title="",
                                 xaxis_range=[0, max(100, dumbbell_df["Max Overall Utilisation (%)"].max() + 5)],
                                 height=CHART_HEIGHT)
            st.plotly_chart(fig_db, use_container_width=True)

        # TAB 3: Tornado Chart
        with tabs[2]:
            st.subheader(f"Inbound vs Outbound Symmetry - {metric_toggle} ({selected_duration.upper()})")
            tornado_df = filtered_df.nlargest(20, col_overall).sort_values(col_overall, ascending=True)

            fig_tornado = go.Figure()

            fig_tornado.add_trace(go.Bar(
                y=tornado_df["Interface"], x=tornado_df[col_in],
                name="Inbound (%)", orientation='h', marker_color='cornflowerblue',
                text=tornado_df[col_in].round(1).astype(str) + "%", textposition='auto',
                hovertemplate="%{y}<br>Inbound: %{x}%<extra></extra>"
            ))

            fig_tornado.add_trace(go.Bar(
                y=tornado_df["Interface"], x=-tornado_df[col_out],
                name="Outbound (%)", orientation='h', marker_color='lightcoral',
                customdata=tornado_df[col_out],
                text=tornado_df[col_out].round(1).astype(str) + "%", textposition='auto',
                hovertemplate="%{y}<br>Outbound: %{customdata}%<extra></extra>"
            ))

            fig_tornado.update_layout(
                barmode='relative', height=CHART_HEIGHT,
                xaxis=dict(
                    title="Outbound (%)  <---   Symmetry   --->  Inbound (%)",
                    tickvals=[-100, -80, -60, -40, -20, 0, 20, 40, 60, 80, 100],
                    ticktext=["100", "80", "60", "40", "20", "0", "20", "40", "60", "80", "100"],
                    showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.3)', dtick=10,
                    tickfont=dict(color="lightgray")
                )
            )
            st.plotly_chart(fig_tornado, use_container_width=True)

        # TAB 4: Directional Utilisation Bar Chart
        with tabs[3]:
            melted_df = filtered_df.melt(
                id_vars=["Interface", "Device", "Type", "Port Speed"], value_vars=[col_in, col_out],
                var_name="Direction", value_name="Utilisation (%)"
            )
            melted_df["Direction"] = melted_df["Direction"].str.replace(f" {metric_toggle} Utilisation (%)", "",
                                                                        regex=False)

            fig_bar = px.bar(
                melted_df, x="Interface", y="Utilisation (%)", color="Direction", barmode="group",
                title=f"Directional Utilisation - {metric_toggle} ({selected_duration.upper()})", height=CHART_HEIGHT
            )
            fig_bar.add_hline(y=60, line_dash="dash", line_color="orange")
            fig_bar.add_hline(y=80, line_dash="dash", line_color="red")
            st.plotly_chart(fig_bar, use_container_width=True)

        # TAB 5: Network Health Histogram
        with tabs[4]:
            fig_hist = px.histogram(
                filtered_df, x=col_overall, nbins=20, color="Type",
                title=f"Network Capacity Spread - {metric_toggle} ({selected_duration.upper()})",
                labels={col_overall: f"{metric_toggle} Utilisation Range (%)", "count": "Number of Interfaces"},
                height=CHART_HEIGHT, range_x=[0, max(100, filtered_df[col_overall].max() + 5)]
            )
            fig_hist.update_traces(xbins=dict(start=0))
            fig_hist.update_layout(bargap=0.1)
            st.plotly_chart(fig_hist, use_container_width=True)

        # TAB 6: Top 10 Congested
        with tabs[5]:
            top_10_df = filtered_df.sort_values(by=col_overall, ascending=False).head(10).sort_values(by=col_overall)
            fig_top = px.bar(
                top_10_df, x=col_overall, y="Interface", orientation="h", color="Type", text=col_overall,
                height=CHART_HEIGHT,
                title=f"Top 10 Congested Links by {metric_toggle} Utilisation ({selected_duration.upper()})"
            )
            fig_top.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            st.plotly_chart(fig_top, use_container_width=True)

        # TAB 7: Treemap (Updated to Gbps)
        with tabs[6]:
            fig_tree = px.treemap(
                filtered_df, path=["Device", "Type", "Interface"], values="Port Capacity (Gbps)",
                color=col_overall, color_continuous_scale="RdYlGn_r", range_color=[0, 100], height=CHART_HEIGHT,
                title=f"Hierarchical Capacity vs {metric_toggle} Saturation ({selected_duration.upper()})"
            )
            # Use formatting to lock to 2 decimal places for Gbps
            fig_tree.update_traces(root_color="lightgrey",
                                   hovertemplate="<b>%{id}</b><br>Capacity: %{value:,.2f} Gbps<br>Util: %{color:.2f}%")
            st.plotly_chart(fig_tree, use_container_width=True)

        # TAB 8: Device Sunburst (Updated to Gbps)
        with tabs[7]:
            sun_df = filtered_df.copy()
            top_10_devices = sun_df.groupby("Device")["Port Capacity (Gbps)"].sum().nlargest(10).index
            sun_df["Device"] = sun_df["Device"].apply(lambda x: x if x in top_10_devices else "Other")

            fig_sun = px.sunburst(
                sun_df, path=["Device", "Interface"], values="Port Capacity (Gbps)",
                color=col_overall, color_continuous_scale="RdYlGn_r", range_color=[0, 100],
                title=f"Capacity Allocation & {metric_toggle} Utilisation (Top 10 Devices)", height=CHART_HEIGHT
            )
            # Changed the hover template to add Gbps text
            fig_sun.update_traces(hovertemplate="<b>%{id}</b><br>Capacity: %{value:,.2f} Gbps<br>Util: %{color:.2f}%")
            st.plotly_chart(fig_sun, use_container_width=True)

        # TAB 9: Port Capacity Donut (Updated to Gbps)
        with tabs[8]:
            st.subheader(f"Total Provisioned Capacity - Single Device View ({selected_duration.upper()})")

            donut_devices = sorted(filtered_df["Device"].unique().tolist())

            if donut_devices:
                selected_donut_device = st.selectbox(
                    "Select a device to view its isolated capacity (prevents cross-link double counting):",
                    options=donut_devices
                )

                donut_df = filtered_df[filtered_df["Device"] == selected_donut_device].copy()

                fig_donut = px.pie(
                    donut_df, names="Port Speed", values="Port Capacity (Gbps)", hole=0.4,
                    title=f"Capacity Broken Down by Interface Speed for {selected_donut_device}", height=CHART_HEIGHT
                )
                # Changed the hover template to add Gbps text
                fig_donut.update_traces(textinfo='percent+label',
                                        hovertemplate="Speed: %{label}<br>Total Capacity: %{value:,.2f} Gbps")
                st.plotly_chart(fig_donut, use_container_width=True)
            else:
                st.info("No devices available to display based on your current sidebar filters.")

        # TAB 10: Raw Data Table
        with tabs[9]:
            st.subheader(f"Raw Data View ({selected_duration.upper()})")
            display_cols = [
                "Interface", "Device", "Type", "Org", "Port Speed",
                "In Avg Utilisation (%)", "In Max Utilisation (%)",
                "Out Avg Utilisation (%)", "Out Max Utilisation (%)",
                "Avg Overall Utilisation (%)", "Max Overall Utilisation (%)"
            ]
            styled_df = filtered_df[display_cols].style.background_gradient(
                cmap='RdYlGn_r',
                subset=[
                    "In Avg Utilisation (%)", "In Max Utilisation (%)",
                    "Out Avg Utilisation (%)", "Out Max Utilisation (%)",
                    "Avg Overall Utilisation (%)", "Max Overall Utilisation (%)"
                ], vmin=0, vmax=100
            ).format(precision=2)

            st.dataframe(styled_df, use_container_width=True, height=CHART_HEIGHT)