import os
import re
from datetime import datetime
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from data_collector import fetch_mrtg_data

CACHE_FILE = "mrtg_data.csv"
CHART_HEIGHT = 700  # Adjust this value to fill your screen real estate

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
    df["Max Overall Utilisation (%)"] = df[["In Max Utilisation (%)", "Out Max Utilisation (%)"]].max(axis=1)
    df["Avg Overall Utilisation (%)"] = df[["In Avg Utilisation (%)", "Out Avg Utilisation (%)"]].max(axis=1)

    # --- Sidebar Filters ---
    st.sidebar.header("Filters & Toggles")
    search_query = st.sidebar.text_input("Search Interface Name", value="")
    selected_duration = st.sidebar.selectbox("Select Graph Duration", ["day", "week", "month", "year"], index=0)

    available_types = df["Type"].unique().tolist()
    selected_types = st.sidebar.multiselect("Filter by Device Type", options=available_types, default=available_types)

    # Apply Filters
    filtered_df = df[(df["Duration"] == selected_duration) & (df["Type"].isin(selected_types))]
    if search_query:
        filtered_df = filtered_df[filtered_df["Interface"].str.contains(search_query, case=False, na=False)]

    if not filtered_df.empty:
        tabs = st.tabs([
            "💥 Burst Matrix",
            "🏋️ Gap Analysis",
            "🌪️ Tornado (In/Out)",
            "📊 Max Utilisation",
            "📈 Health Histogram",
            "🏆 Top 10 Congested",
            "🗃️ Treemap",
            "🔆 Org Sunburst",
            "🍩 Capacity Donut",
            "🕸️ Traffic Radar",
            "📝 Raw Data"
        ])

        # TAB 1: Burst Matrix (Avg vs Max)
        with tabs[0]:
            fig_burst = px.scatter(
                filtered_df, x="Avg Overall Utilisation (%)", y="Max Overall Utilisation (%)",
                color="Type", size="Port Capacity (bps)", hover_name="Interface",
                title=f"Burst Matrix: Average vs. Max Traffic ({selected_duration.upper()})",
                height=CHART_HEIGHT
            )
            max_val = max(filtered_df["Max Overall Utilisation (%)"].max(), 100)
            fig_burst.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val, line=dict(color="gray", dash="dot"))
            fig_burst.add_hline(y=80, line_dash="dash", line_color="red", annotation_text="Critical Burst Line")
            fig_burst.add_vline(x=60, line_dash="dash", line_color="orange", annotation_text="Sustained Warning")
            st.plotly_chart(fig_burst, use_container_width=True)

        # TAB 2: Dumbbell Chart (Gap Analysis)
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

        # TAB 3: Tornado Chart (In/Out Imbalance)
        with tabs[2]:
            st.subheader(f"Average Inbound vs Outbound Symmetry: Top 20 Links ({selected_duration.upper()})")

            tornado_df = filtered_df.nlargest(20, 'Avg Overall Utilisation (%)').sort_values(
                'Avg Overall Utilisation (%)', ascending=True)

            fig_tornado = go.Figure()

            fig_tornado.add_trace(go.Bar(
                y=tornado_df["Interface"], x=tornado_df["In Avg Utilisation (%)"],
                name="Inbound (%)", orientation='h', marker_color='cornflowerblue',
                text=tornado_df["In Avg Utilisation (%)"].round(1).astype(str) + "%", textposition='auto',
                hovertemplate="%{y}<br>Inbound: %{x}%<extra></extra>"
            ))

            fig_tornado.add_trace(go.Bar(
                y=tornado_df["Interface"], x=-tornado_df["Out Avg Utilisation (%)"],
                name="Outbound (%)", orientation='h', marker_color='lightcoral',
                customdata=tornado_df["Out Avg Utilisation (%)"],
                text=tornado_df["Out Avg Utilisation (%)"].round(1).astype(str) + "%", textposition='auto',
                hovertemplate="%{y}<br>Outbound: %{customdata}%<extra></extra>"
            ))

            fig_tornado.update_layout(
                barmode='relative',
                height=CHART_HEIGHT,
                xaxis=dict(
                    title="Outbound (%)  <---   Symmetry   --->  Inbound (%)",
                    tickvals=[-100, -80, -60, -40, -20, 0, 20, 40, 60, 80, 100],
                    ticktext=["100", "80", "60", "40", "20", "0", "20", "40", "60", "80", "100"],
                    showgrid=True, gridwidth=1, gridcolor='rgba(128,128,128,0.3)', dtick=10,
                    tickfont=dict(color="black")  # <--- Forces black axis numbers
                )
            )
            st.plotly_chart(fig_tornado, use_container_width=True)
        # TAB 4: Max Utilisation Bar Chart
        with tabs[3]:
            melted_df = filtered_df.melt(
                id_vars=["Interface", "Device", "Type", "Port Speed"],
                value_vars=["In Max Utilisation (%)", "Out Max Utilisation (%)"],
                var_name="Direction", value_name="Utilisation (%)"
            )
            fig_bar = px.bar(
                melted_df, x="Interface", y="Utilisation (%)", color="Direction", barmode="group",
                title=f"Max Directional Utilisation ({selected_duration.upper()})", height=CHART_HEIGHT
            )
            fig_bar.add_hline(y=60, line_dash="dash", line_color="orange")
            fig_bar.add_hline(y=80, line_dash="dash", line_color="red")
            st.plotly_chart(fig_bar, use_container_width=True)

        # TAB 5: Network Health Histogram (FIXED)
        with tabs[4]:
            fig_hist = px.histogram(
                filtered_df, x="Max Overall Utilisation (%)", nbins=20, color="Type",
                title=f"Network Capacity Spread - Histogram ({selected_duration.upper()})",
                labels={"Max Overall Utilisation (%)": "Max Utilisation Range (%)", "count": "Number of Interfaces"},
                height=CHART_HEIGHT,
                range_x=[0, max(100, filtered_df["Max Overall Utilisation (%)"].max() + 5)]
            )
            fig_hist.update_traces(xbins=dict(start=0))  # <--- Forces the bins to begin at exactly 0
            fig_hist.update_layout(bargap=0.1)
            st.plotly_chart(fig_hist, use_container_width=True)

        # TAB 6: Top 10 Congested
        with tabs[5]:
            top_10_df = filtered_df.sort_values(by="Max Overall Utilisation (%)", ascending=False).head(10).sort_values(
                by="Max Overall Utilisation (%)")
            fig_top = px.bar(
                top_10_df, x="Max Overall Utilisation (%)", y="Interface", orientation="h", color="Type",
                text="Max Overall Utilisation (%)", height=CHART_HEIGHT
            )
            fig_top.update_traces(texttemplate='%{text:.1f}%', textposition='outside')
            st.plotly_chart(fig_top, use_container_width=True)

        # TAB 7: Treemap
        with tabs[6]:
            fig_tree = px.treemap(
                filtered_df, path=["Device", "Type", "Interface"], values="Port Capacity (bps)",
                color="Max Overall Utilisation (%)", color_continuous_scale="RdYlGn_r", range_color=[0, 100],
                height=CHART_HEIGHT
            )
            fig_tree.update_traces(root_color="lightgrey")
            st.plotly_chart(fig_tree, use_container_width=True)

        # TAB 8: Organization Sunburst
        with tabs[7]:
            sun_df = filtered_df.copy()
            sun_df["Org"] = sun_df["Org"].replace(["", "Unknown"], "Uncategorized")

            # Find the Top 10 Orgs by total port capacity
            top_10_orgs = sun_df.groupby("Org")["Port Capacity (bps)"].sum().nlargest(10).index

            # Group all other orgs into "Other" to prevent the chart from becoming unreadable
            sun_df["Org"] = sun_df["Org"].apply(lambda x: x if x in top_10_orgs else "Other")

            fig_sun = px.sunburst(
                sun_df, path=["Org", "Device", "Interface"], values="Port Capacity (bps)",
                color="Avg Overall Utilisation (%)", color_continuous_scale="RdYlGn_r", range_color=[0, 100],
                title="Capacity Allocation & Average Utilisation (Top 10 Organizations)", height=CHART_HEIGHT
            )
            fig_sun.update_traces(hovertemplate="<b>%{id}</b><br>Capacity: %{value}<br>Avg Util: %{color:.2f}%")
            st.plotly_chart(fig_sun, use_container_width=True)

        # TAB 9: Port Capacity Donut
        with tabs[8]:
            fig_donut = px.pie(
                filtered_df, names="Port Speed", values="Port Capacity (bps)", hole=0.4,
                title="Total Provisioned Capacity Broken Down by Interface Speed", height=CHART_HEIGHT
            )
            fig_donut.update_traces(textinfo='percent+label', hovertemplate="Speed: %{label}<br>Total bps: %{value}")
            st.plotly_chart(fig_donut, use_container_width=True)

        # TAB 10: Device Personality Radar
        with tabs[9]:
            st.subheader(f"Traffic Fingerprint by Device Type ({selected_duration.upper()})")

            radar_df = filtered_df.groupby("Type")[
                ["In Avg Utilisation (%)", "Out Avg Utilisation (%)", "In Max Utilisation (%)",
                 "Out Max Utilisation (%)"]
            ].mean().reset_index()

            fig_radar = go.Figure()

            for i, row in radar_df.iterrows():
                fig_radar.add_trace(go.Scatterpolar(
                    r=[row["In Avg Utilisation (%)"], row["In Max Utilisation (%)"],
                       row["Out Max Utilisation (%)"], row["Out Avg Utilisation (%)"],
                       row["In Avg Utilisation (%)"]],
                    theta=['In Avg', 'In Max', 'Out Max', 'Out Avg', 'In Avg'],
                    fill='toself', name=row["Type"]
                ))

            fig_radar.update_layout(
                polar=dict(
                    radialaxis=dict(
                        visible=True,
                        range=[0, max(100, radar_df.drop("Type", axis=1).max().max() + 10)],
                        tickfont=dict(color="black")  # <--- Forces black axis numbers
                    )
                ),
                showlegend=True,
                height=CHART_HEIGHT
            )
            st.plotly_chart(fig_radar, use_container_width=True)

        # TAB 11: Raw Data Table (Now Heatmapped)
        with tabs[10]:
            st.subheader(f"Raw Data View ({selected_duration.upper()})")

            # Select the columns to display
            display_cols = [
                "Interface", "Device", "Type", "Org", "Port Speed",
                "In Avg Utilisation (%)", "In Max Utilisation (%)",
                "Out Avg Utilisation (%)", "Out Max Utilisation (%)",
                "Avg Overall Utilisation (%)", "Max Overall Utilisation (%)"
            ]

            # Apply a pandas background gradient to the numerical percentage columns
            styled_df = filtered_df[display_cols].style.background_gradient(
                cmap='RdYlGn_r',  # Red-Yellow-Green (Reversed so high = red)
                subset=[
                    "In Avg Utilisation (%)", "In Max Utilisation (%)",
                    "Out Avg Utilisation (%)", "Out Max Utilisation (%)",
                    "Avg Overall Utilisation (%)", "Max Overall Utilisation (%)"
                ],
                vmin=0, vmax=100
            ).format(precision=2)  # Lock decimals to 2 places

            st.dataframe(styled_df, use_container_width=True, height=CHART_HEIGHT)

    else:
        st.info("No active lines match your current search and filter parameters.")
