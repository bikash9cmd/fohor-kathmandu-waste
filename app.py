"""Streamlit demo of Fohor: the blockade report, where the waste comes from, and recycling access.

    streamlit run app.py

Reads the published gold tables in ./lake. If nothing is published yet, the pipeline runs once
against the public Overture Maps and HRSL buckets (anonymous S3, about a minute), like `make run`.
"""

import duckdb
import streamlit as st

import brand
from fohor import config, pipeline
from fohor.report import blockade_report
from fohor.source import S3Source
from fohor.storage import open_lake

brand.page("fohor")

TABLES = (
    "municipality_waste",
    "blockade_backlog",
    "drop_off_access",
    "facility_registry",
    "data_gaps",
    "facility_changes",
)


@st.cache_resource(show_spinner="Building the lake from Overture Maps and HRSL (about a minute, first visit only)...")
def lake():
    lk = open_lake(str(config.LAKE_ROOT))
    try:
        pipeline.load_current(lk, "municipality_waste")
    except RuntimeError:  # nothing published yet
        pipeline.run_all(
            S3Source(config.OVERTURE_BUCKET, config.OVERTURE_REGION),
            S3Source(config.HRSL_BUCKET, config.HRSL_REGION),
            lk,
            None,
        )
    return lk


@st.cache_data
def table(name: str):
    return pipeline.load_current(lake(), name)


release, waste = table("municipality_waste")
_, backlog = table("blockade_backlog")
st.caption(f"Overture Maps release {release}.")

blockade, sources, recycling, query = st.tabs(
    ["Blockade report", "Waste by local government", "Recycling drop-offs", "SQL"]
)

with blockade:
    days = st.slider("Bancharedanda landfill road blocked for (days)", 1, 30, 7)
    st.code(blockade_report(backlog, waste, days, release), language=None, wrap_lines=True)
    valley = backlog[backlog.name_en.str.startswith("Kathmandu Valley")].set_index("days_blocked")
    st.subheader("Days to clear after the road reopens")
    st.line_chart(
        valley[
            ["days_to_clear_if_surge_120pct", "days_to_clear_after_reopening", "days_to_clear_if_surge_150pct"]
        ].rename(
            columns={
                "days_to_clear_if_surge_120pct": "trucks at 120%",
                "days_to_clear_after_reopening": "trucks at 130%",
                "days_to_clear_if_surge_150pct": "trucks at 150%",
            }
        ),
        x_label="days blocked",
        y_label="days to clear",
    )

with sources:
    cols = [
        "name_en",
        "district",
        "population",
        "tonnes_per_day",
        "haul_km_mean",
        "truck_trips_per_day",
        "truck_km_per_day",
    ]
    st.bar_chart(waste.set_index("name_en")["tonnes_per_day"].sort_values(ascending=False), y_label="tonnes per day")
    st.dataframe(waste[cols].sort_values("tonnes_per_day", ascending=False), hide_index=True, width="stretch")

with recycling:
    _, access = table("drop_off_access")
    st.write("How far people live from a recycling drop-off the open map knows about.")
    st.dataframe(
        access.drop(columns=["gers_id"]).sort_values("people_beyond_2km", ascending=False),
        hide_index=True,
        width="stretch",
    )

with query:
    q = st.text_area(
        "SQL (DuckDB) over " + ", ".join(TABLES),
        "select name_en, tonnes_per_day, haul_km_mean, truck_km_per_day\n"
        "from municipality_waste\norder by tonnes_per_day desc",
        height=130,
    )
    if st.button("Run query", type="primary"):
        con = duckdb.connect()
        for t in TABLES:
            con.register(t, table(t)[1])
        try:
            st.dataframe(con.sql(q).df(), hide_index=True, width="stretch")
        except duckdb.Error as e:
            st.error(str(e))

brand.footer()
