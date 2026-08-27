"""
Streamlit UI for the barcode enrichment pipeline.

Run with:  streamlit run streamlit_app.py
"""

import asyncio
from pathlib import Path

import pandas as pd
import streamlit as st
import yaml

from src.runner import run_pipeline

st.set_page_config(page_title="Barcode Product Enrichment", layout="wide")
st.title("Barcode Product Enrichment")
st.caption(
    "Upload the CSV of barcodes Open Food Facts couldn't resolve. "
    "This runs the free lookup pipeline (structured APIs → region search → "
    "verified scraping) and splits results into found / not-found / invalid."
)

with open("config.yaml", "r", encoding="utf-8") as f:
    default_config = yaml.safe_load(f)

if "summary" not in st.session_state:
    st.session_state.summary = None
    st.session_state.result_paths = None

with st.sidebar:
    st.header("Single barcode lookup")
    st.caption("Test one barcode instantly — doesn't touch batch progress.")

    single_barcode = st.text_input("Barcode", placeholder="e.g. 8997021871295")
    lookup_clicked = st.button("Look up", disabled=not single_barcode)

    if lookup_clicked and single_barcode:
        from src.runner import lookup_single_barcode
        with st.spinner("Looking up..."):
            outcome = asyncio.run(lookup_single_barcode(single_barcode.strip(), default_config))
        st.session_state.single_lookup_result = outcome

    if st.session_state.get("single_lookup_result"):
        outcome = st.session_state.single_lookup_result
        status = outcome["status"]
        if status == "found":
            st.success("Found")
        elif status == "not_found":
            st.warning("Not found")
        else:
            st.error("Invalid barcode")
        st.json(outcome["result"])

    st.divider()
    st.header("Re-check an existing result")
    st.caption("Re-run a barcode already in found_products.csv against a fresh search.")

    found_path = Path(default_config["paths"]["found_csv"])
    if found_path.exists():
        try:
            existing_df = pd.read_csv(found_path)
            existing_barcodes = existing_df["barcode"].astype(str).tolist()
        except Exception:
            existing_barcodes = []
    else:
        existing_barcodes = []

    recheck_barcode = st.selectbox(
        "Barcode to re-check", options=[""] + existing_barcodes,
        format_func=lambda b: "Select..." if b == "" else b,
    )
    recheck_clicked = st.button("Re-check", disabled=not recheck_barcode)

    if recheck_clicked and recheck_barcode:
        from src.runner import lookup_single_barcode
        old_row = existing_df[existing_df["barcode"].astype(str) == recheck_barcode].iloc[0].to_dict()
        with st.spinner("Re-checking..."):
            outcome = asyncio.run(lookup_single_barcode(recheck_barcode.strip(), default_config))
        st.subheader("Previous result")
        st.json(old_row)
        st.subheader("Fresh result")
        st.json(outcome["result"])

st.divider()

uploaded_file = st.file_uploader("Upload CSV", type=["csv"])

col1, col2 = st.columns(2)
with col1:
    sample_mode = st.checkbox("Test on a sample first (recommended before a full run)", value=True)
    sample_size = st.number_input(
        "Sample size", min_value=10, max_value=15000, value=50, step=10, disabled=not sample_mode
    )
    st.caption(
        "This only limits the SAMPLE test above. Unchecking it processes your "
        "entire uploaded CSV regardless of size (tested comfortably up to "
        "10,000+ rows via the CLI; very large runs in Streamlit itself can "
        "disconnect if left open for hours — see README for CLI usage on big files)."
    )
with col2:
    concurrency = st.slider(
        "Concurrency (browser pages at once)",
        min_value=1, max_value=20, value=default_config.get("concurrency", 6),
    )
    fresh_start = st.checkbox("Ignore previous progress and start fresh", value=False)

start_clicked = st.button("Start processing", type="primary", disabled=uploaded_file is None)

if start_clicked and uploaded_file is not None:
    Path("data").mkdir(exist_ok=True)
    input_path = Path("data") / uploaded_file.name
    with open(input_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    config = dict(default_config)
    config["concurrency"] = concurrency

    progress_placeholder = st.empty()
    progress_bar = progress_placeholder.progress(0, text="Starting...")

    def on_progress(done: int, total: int):
        pct = int(done / total * 100) if total else 100
        progress_bar.progress(pct, text=f"{done}/{total} barcodes processed")

    with st.spinner("Running — this can take a while on a full file. Safe to leave this tab open."):
        summary = asyncio.run(run_pipeline(
            str(input_path),
            config,
            sample=sample_size if sample_mode else None,
            fresh=fresh_start,
            progress_callback=on_progress,
        ))

    st.session_state.summary = summary
    st.session_state.result_paths = config["paths"]

if st.session_state.summary:
    summary = st.session_state.summary
    paths = st.session_state.result_paths

    st.success(
        f"Done in {summary['runtime_seconds']}s — "
        f"**found:** {summary['found']}  ·  "
        f"**not found:** {summary['not_found']}  ·  "
        f"**invalid:** {summary['invalid']}  ·  "
        f"(of {summary['total_rows']} total rows)"
    )

    st.subheader("Download results")
    dl1, dl2, dl3 = st.columns(3)
    with dl1:
        if Path(paths["found_csv"]).exists():
            with open(paths["found_csv"], "rb") as f:
                st.download_button("⬇ found_products.csv", f, file_name="found_products.csv")
    with dl2:
        if Path(paths["not_found_csv"]).exists():
            with open(paths["not_found_csv"], "rb") as f:
                st.download_button("⬇ not_found_products.csv", f, file_name="not_found_products.csv")
    with dl3:
        if Path(paths["invalid_csv"]).exists():
            with open(paths["invalid_csv"], "rb") as f:
                st.download_button("⬇ invalid_barcodes.csv", f, file_name="invalid_barcodes.csv")

    tab1, tab2, tab3 = st.tabs(["Found products", "Not found (manual queue)", "Invalid barcodes"])
    with tab1:
        if Path(paths["found_csv"]).exists():
            df = pd.read_csv(paths["found_csv"])
            st.dataframe(df, use_container_width=True)
    with tab2:
        if Path(paths["not_found_csv"]).exists():
            df = pd.read_csv(paths["not_found_csv"])
            st.dataframe(df, use_container_width=True)
    with tab3:
        if Path(paths["invalid_csv"]).exists():
            df = pd.read_csv(paths["invalid_csv"])
            st.dataframe(df, use_container_width=True)
else:
    st.info("Upload a CSV and click **Start processing** to begin.")