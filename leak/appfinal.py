import streamlit as st
import requests
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from io import BytesIO
import base64
 
# ─────────────────────────────────────────────
# FIX: send the API key header so the backend
# doesn't reject the request with 403
# ─────────────────────────────────────────────
def fetch_results():
    try:
        response = requests.get(
            "http://127.0.0.1:5000/results",
            headers={"API-Key": "12345"},   # ← was missing before → caused 403
            timeout=5,
        )
 
        print("STATUS:", response.status_code)
        print("DATA:", response.text[:200])   # show first 200 chars only
 
        if response.status_code == 403:
            st.error("❌ API key rejected — make sure the backend is running")
            return pd.DataFrame()
 
        if response.status_code != 200:
            st.error(f"❌ Backend error {response.status_code}")
            return pd.DataFrame()
 
        return pd.DataFrame(response.json())
 
    except requests.exceptions.ConnectionError:
        st.warning("⚠️ Cannot reach backend. Start the backend first:\n\n"
                   "`python app.py`\n\nthen refresh this page.")
        return pd.DataFrame()
 
    except Exception as e:
        st.error(f"API Error: {e}")
        return pd.DataFrame()
 
 
 
# -----------------------------
# CONFIG
# -----------------------------
st.set_page_config(page_title="Leak Detection", layout="wide")
 
 
 
size_map = {0: "SMALL", 1: "MEDIUM", 2: "LARGE"}
 
 
 
# -----------------------------
# UI
# -----------------------------
st.title("💧 Smart Pipeline Leak Detection System")
st.info("📂 Default dataset loaded")
 
# -----------------------------
# DATA LOAD (SAFE)
# -----------------------------
def load_data():
    uploaded_file = st.file_uploader("Upload CSV (optional)", type=["csv"])
 
    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file)
            except:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding="latin1")
 
            st.success("✅ Uploaded dataset loaded")
            return df
 
        except Exception as e:
            st.error(f"❌ Upload failed: {e}")
 
    return pd.read_csv("leakdetectiontestdataset.csv")
 
data = load_data()
 
# -----------------------------
# LIVE MODE
# -----------------------------
db_mode = st.toggle("🟢 Live DB Monitoring")
 
 
 
 
# -----------------------------
# CLEAN DATA
# -----------------------------
required_cols = ["pressure_in_bar", "pressure_out_bar", "flow_in", "flow_out", "pump_status"]
 
 
if all(col in data.columns for col in required_cols):
    for col in ["pressure_in_bar", "pressure_out_bar", "flow_in", "flow_out"]:
        data[col] = data[col].fillna(data[col].median())
else:
    st.error("❌ Missing required columns in dataset")
    st.stop()
 
 
# -----------------------------
# RUN BUTTON
# -----------------------------
run = st.button("▶ Start Detection")
 
# -----------------------------
# MAIN EXECUTION
# -----------------------------
def display_results(df):
 
    if df.empty:
        st.success("✅ No Leak Detected")
        return
 
    df = df.copy()
 
    if "leak_status" not in df.columns:
        df["leak_status"] = "Leak Detected"
        df["leak_size"] = "MEDIUM"
 
    # SPLIT
    leak_df = df[df["leak_status"] == "Leak Detected"]
    pump_off_df = df[df["leak_status"].str.contains("Pump OFF", na=False)]
 
    # SUMMARY
    st.subheader("🚨 Leak Summary")
 
    counts = leak_df["leak_size"].value_counts()
 
    col1, col2, col3 = st.columns(3)
    col1.metric("SMALL", counts.get("SMALL", 0))
    col2.metric("MEDIUM", counts.get("MEDIUM", 0))
    col3.metric("LARGE", counts.get("LARGE", 0))
 
    # ALERT
    if not leak_df.empty:
        top = leak_df.iloc[0]
        st.warning(f"🚨 {top['leak_size']} leak detected at Sensor {top['sensor_id']}")
 
    # COLOR TABLE
    if not leak_df.empty:
 
        def highlight_row(row):
            if row["leak_size"] == "LARGE":
                return ["background-color:#ffcccc"] * len(row)
            elif row["leak_size"] == "MEDIUM":
                return ["background-color:#ffe0b3"] * len(row)
            else:
                return ["background-color:#fff9cc"] * len(row)
 
        styled_df = leak_df.style.apply(highlight_row, axis=1)
 
        st.subheader("📊 Leak Detected Data")
        st.dataframe(styled_df, use_container_width=True)
 
        # DOWNLOAD
        csv = leak_df.to_csv(index=False).encode("utf-8")
        st.download_button("📥 Download CSV", csv, "leak_report.csv")
 
        output = BytesIO()
        with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
            leak_df.to_excel(writer, index=False)
 
        st.download_button("📊 Download Excel", output.getvalue(), "leak_report.xlsx")
 
    # PUMP OFF
    if not pump_off_df.empty:
        st.subheader("🔌 Pump OFF Cases")
 
        for _, row in pump_off_df.iterrows():
            st.info(f"Sensor: {row['sensor_id']} | Node: {row['node_id']}")
 
 
 
# -----------------------------
# EXECUTION FLOW
# -----------------------------
if run and not db_mode:
    display_results(data)
 
if db_mode:
    st_autorefresh(interval=5000, key="live_refresh")
 
    data_live = fetch_results()
 
    if data_live.empty:
        st.warning("⚠ No live results yet...")
    else:
        display_results(data_live)