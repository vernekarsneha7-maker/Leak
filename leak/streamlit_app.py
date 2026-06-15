import streamlit as st
import requests
from streamlit_autorefresh import st_autorefresh
import pandas as pd
from io import BytesIO

# -----------------------------
# CONFIG
# -----------------------------
BACKEND_URL = "http://127.0.0.1:5000"
API_KEY     = "12345"          # ← must match backend.py API_KEY

# -----------------------------
# PAGE SETUP
# -----------------------------
st.set_page_config(page_title="💧 Leak Detection", layout="wide")
st.title("💧 Smart Pipeline Leak Detection System")

# -----------------------------
# HELPERS
# -----------------------------

def fetch_results() -> pd.DataFrame:
    """
    BUG FIXED: the API-Key header was never sent before.
    Now it is passed with every request.
    """
    try:
        response = requests.get(
            f"{BACKEND_URL}/results",
            headers={"API-Key": API_KEY},
            timeout=5,
        )
        if response.status_code == 403:
            st.error("🔑 API key rejected – check that API_KEY matches backend.py")
            return pd.DataFrame()
        if response.status_code != 200:
            st.error(f"Backend error {response.status_code}: {response.text}")
            return pd.DataFrame()

        return pd.DataFrame(response.json())

    except requests.exceptions.ConnectionError:
        st.error("❌ Cannot reach backend – is backend.py running on port 5000?")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"API Error: {e}")
        return pd.DataFrame()


def load_csv_data() -> pd.DataFrame:
    uploaded_file = st.file_uploader("Upload CSV (optional)", type=["csv"])
    if uploaded_file is not None:
        try:
            uploaded_file.seek(0)
            try:
                df = pd.read_csv(uploaded_file)
            except Exception:
                uploaded_file.seek(0)
                df = pd.read_csv(uploaded_file, encoding="latin1")
            st.success("✅ Uploaded dataset loaded")
            return df
        except Exception as e:
            st.error(f"❌ Upload failed: {e}")

    try:
        return pd.read_csv("leakdetectiontestdataset.csv")
    except FileNotFoundError:
        st.info("📂 No default CSV found – using Live DB mode.")
        return pd.DataFrame()


def clean_data(df: pd.DataFrame):
    required_cols = [
        "pressure_in_bar", "pressure_out_bar",
        "flow_in", "flow_out", "pump_status",
    ]
    if not all(c in df.columns for c in required_cols):
        st.error(f"❌ Missing required columns. Need: {required_cols}")
        return None
    for col in ["pressure_in_bar", "pressure_out_bar", "flow_in", "flow_out"]:
        df[col] = df[col].fillna(df[col].median())
    return df


def display_results(df: pd.DataFrame):
    if df.empty:
        st.success("✅ No data to display yet.")
        return

    df = df.copy()

    if "leak_status" not in df.columns:
        df["leak_status"] = "Leak Detected"
        df["leak_size"]   = "MEDIUM"

    leak_df     = df[df["leak_status"] == "Leak Detected"].copy()
    normal_df   = df[df["leak_status"] == "Normal"].copy()
    pump_off_df = df[df["leak_status"].str.contains("Pump OFF", na=False)].copy()

    # KPI row
    st.subheader("🚨 Leak Summary")
    counts = leak_df["leak_size"].value_counts() if not leak_df.empty else pd.Series(dtype=int)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("🔴 LARGE",  counts.get("LARGE",  0))
    c2.metric("🟠 MEDIUM", counts.get("MEDIUM", 0))
    c3.metric("🟡 SMALL",  counts.get("SMALL",  0))
    c4.metric("✅ Normal", len(normal_df))

    # Live alert banner
    if not leak_df.empty:
        top = leak_df.iloc[0]
        st.warning(
            f"🚨 **{top['leak_size']}** leak detected | "
            f"Sensor {top['sensor_id']} | Node {top['node_id']} | "
            f"{top.get('timestamp', '')}"
        )

    # Leak table
    if not leak_df.empty:
        def highlight_row(row):
            if row.get("leak_size") == "LARGE":
                return ["background-color:#ffcccc"] * len(row)
            elif row.get("leak_size") == "MEDIUM":
                return ["background-color:#ffe0b3"] * len(row)
            return ["background-color:#fff9cc"] * len(row)

        styled = leak_df.style.apply(highlight_row, axis=1)
        st.subheader("📊 Leak Detected Rows")
        st.dataframe(styled, use_container_width=True)

        col_a, col_b = st.columns(2)
        with col_a:
            csv = leak_df.to_csv(index=False).encode("utf-8")
            st.download_button("📥 Download CSV", csv, "leak_report.csv", "text/csv")
        with col_b:
            buf = BytesIO()
            with pd.ExcelWriter(buf, engine="xlsxwriter") as writer:
                leak_df.to_excel(writer, index=False)
            st.download_button(
                "📊 Download Excel", buf.getvalue(),
                "leak_report.xlsx",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

    # All rows expander
    with st.expander("🔍 All recent rows (last 50)"):
        st.dataframe(df, use_container_width=True)

    # Pump-off notices
    if not pump_off_df.empty:
        st.subheader("🔌 Pump OFF Cases")
        for _, row in pump_off_df.iterrows():
            st.info(
                f"Sensor: {row.get('sensor_id', '?')} | "
                f"Node: {row.get('node_id', '?')} | "
                f"{row.get('timestamp', '')}"
            )


# -----------------------------
# SIDEBAR
# -----------------------------
st.sidebar.header("⚙️ Settings")
db_mode = st.sidebar.toggle("🟢 Live DB Monitoring", value=False)

if db_mode:
    st.sidebar.success("Live mode ON – refreshing every 5 s")
else:
    st.sidebar.info("Offline mode – upload or use default CSV")

# -----------------------------
# MAIN FLOW
# -----------------------------
if db_mode:
    st_autorefresh(interval=5_000, key="live_refresh")
    st.info("📡 Fetching live results from backend…")
    live_df = fetch_results()

    if live_df.empty:
        st.warning("⚠️ No live results yet – backend may still be processing rows.")
    else:
        display_results(live_df)

else:
    data = load_csv_data()
    if data is not None and not data.empty:
        data = clean_data(data)
        if data is not None:
            run = st.button("▶ Start Detection")
            if run:
                display_results(data)
