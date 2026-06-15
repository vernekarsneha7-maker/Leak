"""
app.py — Water Leak Detection Backend (FIXED)
 
Key fixes from original:
  1. Thread-safe connection pool (psycopg2.pool.ThreadedConnectionPool)
     — original shared one cursor across threads → crashes/data corruption
  2. Removed broken module-level leak_type / pressure_out code outside try block
     — original would NameError immediately on startup
  3. API key read from .env via os.getenv, not hardcoded "12345"
  4. Frontend uses header "X-API-Key" (standard) not "API-Key"
  5. conn.rollback() is now inside except blocks, not dead code at module end
  6. pg_notify LISTEN runs in a dedicated thread for real-time alerts
"""
 
import os
from dotenv import load_dotenv
import json
import time
import select
import threading
 
import requests
import psycopg2
import psycopg2.pool
import psycopg2.extensions
import pandas as pd
import joblib
from flask import Flask, jsonify, request
from sqlalchemy import create_engine
from dotenv import load_dotenv
 
load_dotenv()
 
app = Flask(__name__)
 
# ─────────────────────────────────────────────
# CONFIG  (set these in your .env file)
# ─────────────────────────────────────────────
DB_HOST     = os.getenv("DB_HOST",     "localhost")
DB_NAME     = os.getenv("DB_NAME",     "water_leak_detection_db")
DB_USER     = os.getenv("DB_USER",     "postgres")
DB_PASSWORD = os.getenv("DB_PASSWORD", "testpass123")
API_KEY     = os.getenv("BACKEND_API_KEY", "change-this-secret-key")
 
DSN = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}/{DB_NAME}"
 
# Thread-safe pool: min 2, max 10 connections
pool = psycopg2.pool.ThreadedConnectionPool(
    minconn=2, maxconn=10,
    host=DB_HOST, database=DB_NAME, user=DB_USER, password=DB_PASSWORD
)
 
engine = create_engine(DSN)
 
# ─────────────────────────────────────────────
# ML MODELS
# ─────────────────────────────────────────────
leak_model = joblib.load("models/leak_model.pkl")
size_model = joblib.load("models/size_model.pkl")
SIZE_MAP   = {0: "SMALL", 1: "MEDIUM", 2: "LARGE"}
 
 
# ─────────────────────────────────────────────
# DB HELPERS
# ─────────────────────────────────────────────
def get_conn():
    return pool.getconn()
 
def release_conn(conn):
    pool.putconn(conn)
 
 
# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"message": "Water Leak Detection backend running ✅"})
 
 
@app.route("/results")
def get_results():
    # ── API Key guard ──────────────────────────
    key = request.headers.get("X-API-Key")   # standard header name
    if key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 403
 
    # ── Query ─────────────────────────────────
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
                "sensor_id":   r[0],
                "node_id":     r[1],
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
 
 
@app.route("/alerts")
def get_alerts():
    """Latest alerts fired by the PostgreSQL trigger (detect_leak)."""
    key = request.headers.get("X-API-Key")
    if key != API_KEY:
        return jsonify({"error": "Unauthorized"}), 403
 
    conn = get_conn()
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT device_id, leak_status, leak_size,
                   leak_value, latitude, longitude, created_at
            FROM   alerts
            ORDER  BY created_at DESC
            LIMIT  20
        """)
        rows = cur.fetchall()
        cols = ["device_id","leak_status","leak_size",
                "leak_value","latitude","longitude","created_at"]
        return jsonify([dict(zip(cols, r)) for r in rows])
    except Exception as exc:
        conn.rollback()
        return jsonify({"error": str(exc)}), 500
    finally:
        release_conn(conn)
 
 
# ─────────────────────────────────────────────
# DATA INGESTION  (Open-Meteo → sensor_data)
# ─────────────────────────────────────────────
METEO_URL = (
    "https://api.open-meteo.com/v1/forecast"
    "?latitude=12.97&longitude=77.59"
    "&current=pressure_msl,wind_speed_10m"
)
 
def fetch_api_data():
    """Pull one reading from Open-Meteo and return a sensor-row dict."""
    try:
        res  = requests.get(METEO_URL, timeout=5)
        cur  = res.json()["current"]
 
        pressure_in  = cur["pressure_msl"] / 100           # hPa → bar approx
        wind         = cur["wind_speed_10m"]
        pressure_out = pressure_in - (0.5 + (wind % 2))
        flow_in      = wind * 10
        flow_out     = flow_in - (5 + (wind % 5))
 
        return {
            "sensor_id":       1,
            "node_id":         1,
            "pump_status":     1,
            "pressure_in_bar": round(pressure_in,  4),
            "pressure_out_bar":round(pressure_out, 4),
            "flow_in":         round(flow_in,  4),
            "flow_out":        round(flow_out, 4),
        }
    except Exception as exc:
        print(f"[Ingest] API fetch error: {exc}")
        return None
 
 
def generate_data():
    """Background thread: fetch → INSERT into sensor_data every 5 s."""
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
                    VALUES (%s,%s,%s,%s,%s,%s,%s, FALSE)
                """, (
                    row["sensor_id"],    row["node_id"],
                    row["pump_status"],
                    row["pressure_in_bar"], row["pressure_out_bar"],
                    row["flow_in"],      row["flow_out"],
                ))
                conn.commit()
                print(f"[Ingest] ✅ p_in={row['pressure_in_bar']} "
                      f"p_out={row['pressure_out_bar']}")
            except Exception as exc:
                conn.rollback()
                print(f"[Ingest] DB error: {exc}")
            finally:
                release_conn(conn)
        time.sleep(5)
 
 
# ─────────────────────────────────────────────
# ML MONITORING  (sensor_data → results)
# ─────────────────────────────────────────────
def run_live_monitoring():
    """Background thread: run ML on unprocessed rows every 5 s."""
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
                        flow_loss     = abs(row["flow_in"] - row["flow_out"])
 
                        X = pd.DataFrame([{
                            "pressure_in_bar":  row["pressure_in_bar"],
                            "pressure_out_bar": row["pressure_out_bar"],
                            "pressure_drop":    pressure_drop,
                            "flow_loss":        flow_loss,
                        }])
 
                        if row["pump_status"] == 0:
                            leak_status = (f"Pump OFF at Sensor {row['sensor_id']} "
                                          f"Node {row['node_id']}")
                            leak_size = None
                        else:
                            if leak_model.predict(X)[0] == 1:
                                leak_status = "Leak Detected"
                                leak_size   = SIZE_MAP.get(size_model.predict(X)[0])
                            else:
                                leak_status = "Normal"
                                leak_size   = None
 
                        cur.execute("""
                            INSERT INTO results
                                (sensor_id, node_id, pump_status,
                                 leak_status, leak_size)
                            VALUES (%s,%s,%s,%s,%s)
                        """, (row["sensor_id"], row["node_id"],
                              row["pump_status"], leak_status, leak_size))
 
                        cur.execute(
                            "UPDATE sensor_data SET processed=TRUE WHERE id=%s",
                            (row["id"],)
                        )
 
                    conn.commit()
                    print(f"[Monitor] ✅ Processed {len(df)} row(s)")
                except Exception as exc:
                    conn.rollback()
                    print(f"[Monitor] DB error: {exc}")
                finally:
                    release_conn(conn)
        except Exception as exc:
            print(f"[Monitor] Error: {exc}")
 
        time.sleep(5)
 
 
# ─────────────────────────────────────────────
# pg_notify LISTENER  (real-time alerts)
# ─────────────────────────────────────────────
def listen_for_leaks():
    """
    Dedicated connection that LISTENs on 'leak_channel'.
    The PostgreSQL trigger (detect_leak) fires pg_notify there.
    This thread logs every notification; extend to push via WebSocket etc.
    """
    conn = psycopg2.connect(
        host=DB_HOST, database=DB_NAME,
        user=DB_USER, password=DB_PASSWORD
    )
    conn.set_isolation_level(psycopg2.extensions.ISOLATION_LEVEL_AUTOCOMMIT)
    cur = conn.cursor()
    cur.execute("LISTEN leak_channel;")
    print("[pg_notify] Listening on leak_channel …")
 
    while True:
        # Block up to 5 s waiting for a notification
        if select.select([conn], [], [], 5) == ([], [], []):
            continue                          # timeout, try again
        conn.poll()
        while conn.notifies:
            note = conn.notifies.pop(0)
            print(f"[pg_notify] 🚨 ALERT: {note.payload}")
            # TODO: push to a WebSocket / SSE endpoint for frontend
 
 
# ─────────────────────────────────────────────
# START THREADS
# ─────────────────────────────────────────────
threading.Thread(target=generate_data,       daemon=True).start()
threading.Thread(target=run_live_monitoring, daemon=True).start()
threading.Thread(target=listen_for_leaks,    daemon=True).start()
 
 
# ─────────────────────────────────────────────
# RUN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)