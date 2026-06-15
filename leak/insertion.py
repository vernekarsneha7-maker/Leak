import pandas as pd
import numpy as np
import psycopg2
from psycopg2.extras import execute_values

# -----------------------------
# LOAD
# -----------------------------
df = pd.read_csv("leakdetectiondataset.csv")
print("Columns:", df.columns)

# -----------------------------
# CLEAN
# -----------------------------



# Timestamp
df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
df["timestamp"] = df["timestamp"].fillna(pd.Timestamp.now())

# IDs cleanup
df["sensor_id"] = df["sensor_id"].astype(str).str.replace("S", "", regex=False)
df["node_id"]   = df["node_id"].astype(str).str.replace("N", "", regex=False)

df["sensor_id"] = pd.to_numeric(df["sensor_id"], errors="coerce").fillna(0).astype(int)
df["node_id"]   = pd.to_numeric(df["node_id"], errors="coerce").fillna(0).astype(int)

# Numeric columns
numeric_cols = [
    "pressure_in_bar","pressure_out_bar","flow_in","flow_out",
    "pressure_drop","flow_loss","pressure_change_rate_bar_per_min",
    "flow_rate","flow_velocity","leak_volume_estimation",
    "pipe_diameter_mm","standard_deviation",
    "discharge_coefficient","gravity","water_density","leak_volume"
]

for col in numeric_cols:
    df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

# Latitude & Longitude
df["latitude"]  = pd.to_numeric(df["latitude"], errors="coerce").fillna(0)
df["longitude"] = pd.to_numeric(df["longitude"], errors="coerce").fillna(0)

# Sampling rate
df["sampling_rate_min"] = pd.to_numeric(df["sampling_rate_min"], errors="coerce").fillna(1)

# Pump status
df["pump_status"] = df["pump_status"].fillna("OFF")

# Boolean + string
df["leak"] = df["leak"].map({True: True, False: False}).fillna(False).astype(bool)
df["leak_size"] = df["leak_size"].fillna("UNKNOWN").astype(str)

# -----------------------------
# FINAL CHECK (NO DROPPING ROWS)
# -----------------------------
print("Null values after cleaning:\n", df.isnull().sum())
print("Total rows going to insert:", len(df))

# -----------------------------
# CONNECT
# -----------------------------
conn = psycopg2.connect(
    host="localhost",
    database="water_leak_detection_db",
    user="postgres",
    password="testpass123"
)
cursor = conn.cursor()

# -----------------------------
# INSERT QUERY
# -----------------------------
query = """
INSERT INTO sensor_data (
    timestamp, sensor_id, node_id, latitude, longitude,
    pump_status, pressure_in_bar, pressure_out_bar,
    flow_in, flow_out, pressure_drop, flow_loss,
    pressure_change_rate_bar_per_min, sampling_rate_min,
    flow_rate, flow_velocity, leak_volume_estimation,
    pipe_diameter_mm, standard_deviation,
    discharge_coefficient, gravity, water_density,
    leak_volume, leak, leak_size
) VALUES %s
"""

# -----------------------------
# PREPARE VALUES
# -----------------------------
values = [
    (
        row.timestamp, row.sensor_id, row.node_id,
        row.latitude, row.longitude, row.pump_status,
        row.pressure_in_bar, row.pressure_out_bar,
        row.flow_in, row.flow_out,
        row.pressure_drop, row.flow_loss,
        row.pressure_change_rate_bar_per_min, row.sampling_rate_min,
        row.flow_rate, row.flow_velocity,
        row.leak_volume_estimation,
        row.pipe_diameter_mm, row.standard_deviation,
        row.discharge_coefficient, row.gravity,
        row.water_density, row.leak_volume,
        row.leak, row.leak_size
    )
    for row in df.itertuples(index=False)
]

# -----------------------------
# EXECUTE INSERT
# -----------------------------
execute_values(cursor, query, values)

conn.commit()
cursor.close()
conn.close()

print("✅ Successfully inserted rows:", len(values))