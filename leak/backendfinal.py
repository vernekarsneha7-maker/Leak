"""
app.py — Water Leak Detection Backend (FINAL)
 
Key fixes vs all previous versions:
  1. Sensor IDs stored/displayed as "S001"..."S005"
     Node  IDs stored/displayed as "N101"..."N105"  (never plain integers)
  2. Random SENSOR_NODE chosen each call → real variety in the DB
  3. debug=False + threaded=True → no more "development server" warning
  4. Thread-safe connection pool — each thread gets its own connection
  5. Full terminal log every cycle: sensor, node, all pressures, flows, result
  6. API key header name: "API-Key"  (matches the fixed Streamlit below)
  7. conn.rollback() inside except blocks only (was dead code at module end)
  8. leak_type chosen per-call inside the try block (was NameError before)
"""
 
import os
import time
import threading
import random
 
import requests
import psycopg2
import psycopg2.pool
import pandas as pd
import joblib
from flask import Flask, jsonify, request
from sqlalchemy import create_engine
 
# ─────────────────────────────────────────────
# CONFIG
# ─────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",         "localhost")
DB_NAME     = os.getenv("DB_NAME",         "water_leak_detection_db")
DB_USER     = os.getenv("DB_USER",         "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD",     "testpass123")
API_KEY     = os.getenv("BACKEND_API_KEY", "12345")
 
DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
 
# ─────────────────────────────────────────────
# SENSOR NETWORK
# (sensor_num, node_num, latitude, longitude)
# Always formatted: sensor → "S001", node → "N101"
# ─────────────────────────────────────────────
SENSOR_NODES = [
    (1, 101, 12.9716, 77.5946),
    (2, 102, 12.9800, 77.6000),
    (3, 103, 12.9650, 77.5800),
    (4, 104, 12.9900, 77.6100),
    (5, 105, 12.9550, 77.5700),
]
 
def fmt_sensor(n: int) -> str:
    return f"S{n:03d}"      # 1   → "S001"
 
def fmt_node(n: int) -> str:
    return f"N{n:03d}"      # 101 → "N101"
 
# ─────────────────────────────────────────────
# ML MODELS
# ─────────────────────────────────────────────
leak_model = joblib.load("models/leak_model.pkl")
size_model = joblib.load("models/size_model.pkl")
iso_model = joblib.load("models/isolation_forest.pkl")
SIZE_MAP   = {0: "SMALL", 1: "MEDIUM", 2: "LARGE"}

print("Loading models...")

leak_model = joblib.load("models/leak_model.pkl")
size_model = joblib.load("models/size_model.pkl")
iso_model = joblib.load("models/isolation_forest.pkl")

print("✅ Leak Model Loaded")
print("✅ Size Model Loaded")
print("✅ Isolation Forest Loaded")
 
# ─────────────────────────────────────────────
# THREAD-SAFE CONNECTION POOL
# Each thread calls get_conn() → does work → release_conn()
# Nothing shared across threads — eliminates crashes / bad-state errors
# ─────────────────────────────────────────────
pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2, maxconn=10,
    host=DB_HOST, database=DB_NAME,
    user=DB_USER, password=DB_PASSWORD,
)
 
def get_conn():
    return pool.getconn()
 
def release_conn(c):
    pool.putconn(c)
 
# ─────────────────────────────────────────────
# FLASK APP
# ─────────────────────────────────────────────
app = Flask(__name__)
 
 
@app.route("/")
def home():
    return jsonify({"message": "Water Leak Detection backend running ✅"})
 
 
@app.route("/results")
def get_results():
    # API Key guard — Streamlit must send header "API-Key: 12345"
    if request.headers.get("API-Key") != API_KEY:
        return jsonify({"error": "Unauthorized – invalid or missing API key"}), 403
 
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT sensor_id, node_id, pump_status,
                   leak_status, leak_size, timestamp
            FROM   results
            ORDER  BY timestamp DESC
            LIMIT  50
        """)
        rows = cur.fetchall()
        data = [
            {
                "sensor_id":   r[0],   # stored as "S001" etc.
                "node_id":     r[1],   # stored as "N101" etc.
                "pump_status": r[2],
                "leak_status": r[3],
                "leak_size":   r[4],
                "timestamp":   str(r[5]),
            }
            for r in rows
        ]
        return jsonify(data)
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        release_conn(conn)
 
 
# ─────────────────────────────────────────────
# DATA INGESTION  — Open-Meteo → sensor_data
# ─────────────────────────────────────────────
METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=12.97&longitude=77.59"
    "&current=pressure_msl,wind_speed_10m"
)
 
 
def fetch_api_data():
    """Fetch real weather proxy from Open-Meteo, simulate a leak, return row."""
    try:
        res  = requests.get(METEO_URL, timeout=5)
        cur  = res.json()["current"]
 
        pressure_in = cur["pressure_msl"] / 100    # hPa → bar
        flow_in     = cur["wind_speed_10m"] * 10   # proxy m³/h
 
        # Different sensor/node every call
        s_num, n_num, lat, lon = random.choice(SENSOR_NODES)
 
        # Weighted leak scenario  (50% normal, 20% small, 20% medium, 10% large)
        leak_type = random.choices(
            ["none", "small", "medium", "large"],
            weights=[50, 20, 20, 10],
        )[0]
 
        if leak_type == "none":
            pressure_out = pressure_in - random.uniform(0.0, 0.1)
            flow_out     = flow_in     - random.uniform(0.0, 0.5)
        elif leak_type == "small":
            pressure_out = pressure_in - random.uniform(0.2, 0.8)
            flow_out     = flow_in     - random.uniform(1,   5)
        elif leak_type == "medium":
            pressure_out = pressure_in - random.uniform(1,   2)
            flow_out     = flow_in     - random.uniform(5,  15)
        else:  # large
            pressure_out = pressure_in - random.uniform(2,   4)
            flow_out     = flow_in     - random.uniform(15, 30)
 
        pump_status = 0 if random.random() < 0.05 else 1   # 5% pump-off
 
        # ── Full terminal log for every ingested reading ─────────
        print(
            f"\n[Ingest] ────────────────────────────────────────────\n"
            f"  Sensor   : {fmt_sensor(s_num)}          Node : {fmt_node(n_num)}\n"
            f"  Location : lat={lat}     lon={lon}\n"
            f"  Scenario : {leak_type.upper():<6}        Pump : {'ON' if pump_status else 'OFF'}\n"
            f"  Pressure : in={pressure_in:.4f} bar   out={pressure_out:.4f} bar"
            f"   Δ={pressure_in - pressure_out:.4f}\n"
            f"  Flow     : in={flow_in:.2f}           out={flow_out:.2f}"
            f"            loss={abs(flow_in - flow_out):.2f}\n"
            f"─────────────────────────────────────────────────────"
        )
 
        return {
            "sensor_id":        fmt_sensor(s_num),
            "node_id":          fmt_node(n_num),
            "pump_status":      pump_status,
            "pressure_in_bar":  round(pressure_in,  4),
            "pressure_out_bar": round(pressure_out, 4),
            "flow_in":          round(flow_in,  4),
            "flow_out":         round(flow_out, 4),
        }
 
    except Exception as exc:
        print(f"[Ingest] ❌ API error: {exc}")
        return None
 
 
# ─────────────────────────────────────────────
# BACKGROUND THREAD 1 — ingest (every 5 s)
# ─────────────────────────────────────────────
def generate_data():
    print("[Ingest] ✅ Thread started — inserting sensor data every 5 s")
    while True:
        row = fetch_api_data()
        if row:
            conn = get_conn()
            try:
                cur = conn.cursor()
                cur.execute("""
                    INSERT INTO sensor_data
                        (sensor_id, node_id, pump_status,
                         pressure_in_bar, pressure_out_bar,
                         flow_in, flow_out, processed)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
                """, (
                    row["sensor_id"],
                    row["node_id"],
                    row["pump_status"],
                    row["pressure_in_bar"],
                    row["pressure_out_bar"],
                    row["flow_in"],
                    row["flow_out"],
                ))
                conn.commit()
                print(f"[Ingest] ✅ Saved  sensor={row['sensor_id']}  node={row['node_id']}")
            except Exception as exc:
                conn.rollback()
                print(f"[Ingest] ❌ DB insert error: {exc}")
            finally:
                release_conn(conn)
        time.sleep(5)
 
 
# ─────────────────────────────────────────────
# BACKGROUND THREAD 2 — ML monitor (every 5 s)
# ─────────────────────────────────────────────
def run_live_monitoring():
    engine = create_engine(DSN)
    print("[Monitor] ✅ Thread started — running ML on unprocessed rows every 5 s")
 
    while True:
        try:
            df = pd.read_sql("""
                SELECT * FROM sensor_data
                WHERE  processed = FALSE
                ORDER  BY timestamp ASC
                LIMIT  5
            """, engine)
 
            if not df.empty:
                conn = get_conn()
                try:
                    cur = conn.cursor()
 
                    for _, row in df.iterrows():
                        pressure_drop = row["pressure_in_bar"] - row["pressure_out_bar"]
                        flow_loss = abs(row["flow_in"] - row["flow_out"])
                        X = pd.DataFrame([{
                              "pressure_in_bar": row["pressure_in_bar"],
                              "pressure_out_bar": row["pressure_out_bar"],
                              "pressure_drop": pressure_drop,
                              "flow_loss": flow_loss,
                              }])
                        iso_result = iso_model.predict(X)[0]
                        # Decision logic
                        if row["pump_status"] == 0:
                             leak_status = (
                                  f"Pump OFF at Sensor {row['sensor_id']} "
                                  f"Node {row['node_id']}"
 )
                             leak_size = None
                        elif iso_result == -1:
                             leak_pred = leak_model.predict(X)[0]
                        if leak_pred == 1:
                             size_pred = size_model.predict(X)[0]
                             leak_status = "Leak Detected"
                             leak_size = SIZE_MAP.get(int(size_pred), "UNKNOWN")
                        else:
                             leak_status = "Anomaly Detected"
                             leak_size = None
                    else:
                        leak_status = "Normal"
                        leak_size = None
 
                        # ── Full terminal log for every processed row ────
                        size_tag = f"[{leak_size}]" if leak_size else ""
                        print(
                            f"\n[Monitor] ══════════════════════════════════════════\n"
                            f"  Sensor   : {row['sensor_id']}        Node : {row['node_id']}\n"
                            f"  Pressure : in={row['pressure_in_bar']:.4f}  "
                            f"out={row['pressure_out_bar']:.4f}  drop={pressure_drop:.4f}\n"
                            f"  Flow     : in={row['flow_in']:.2f}  "
                            f"out={row['flow_out']:.2f}  loss={flow_loss:.2f}\n"
                            f"  Pump     : {'ON' if row['pump_status'] else 'OFF'}\n"
                            f"  Decision : {leak_status} {size_tag}\n"
                            f"══════════════════════════════════════════════════"
                        )
 
                        cur.execute("""
                            INSERT INTO results
                                (sensor_id, node_id, pump_status,
                                 leak_status, leak_size)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            row["sensor_id"],
                            row["node_id"],
                            row["pump_status"],
                            leak_status,
                            leak_size,
                        ))
 
                        cur.execute(
                            "UPDATE sensor_data SET processed = TRUE WHERE id = %s",
                            (row["id"],)
                        )
 
                    conn.commit()
                    print(f"[Monitor] ✅ Committed {len(df)} row(s)\n")
 
                except Exception as exc:
                    conn.rollback()
                    print(f"[Monitor] ❌ DB error: {exc}")
                finally:
                    release_conn(conn)
 
        except Exception as exc:
            print(f"[Monitor] ❌ Outer error: {exc}")
 
        time.sleep(5)
 
 
# ─────────────────────────────────────────────
# START BACKGROUND THREADS
# ─────────────────────────────────────────────
threading.Thread(target=generate_data,       daemon=True, name="ingest").start()
threading.Thread(target=run_live_monitoring, daemon=True, name="monitor").start()
 
# ─────────────────────────────────────────────
# RUN SERVER
#   debug=False      → removes the "development server" warning entirely
#   threaded=True    → Flask handles concurrent requests without blocking
#   use_reloader=False → prevents threads from being launched twice
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("\n" + "=" * 58)
    print("  💧 Water Leak Detection Backend")
    print("  Listening on: http://127.0.0.1:5000")
    print("  Background threads: [ingest] + [monitor]  ← always on")
    print("=" * 58 + "\n")
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False,
        threaded=True,
        use_reloader=False,
    )
    