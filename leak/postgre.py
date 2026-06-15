import psycopg2

conn = psycopg2.connect(
    host="localhost",
    database="water_leak_detection_db",
    user="postgres",
    password="testpass123"
)

cursor = conn.cursor()

# -----------------------------
# SENSOR DATA TABLE
# -----------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS sensor_data (
    id SERIAL PRIMARY KEY,
    sensor_id STRING,
    node_id STRING,
    pump_status INT,
    pressure_in_bar FLOAT,
    pressure_out_bar FLOAT,
    flow_in FLOAT,
    flow_out FLOAT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed BOOLEAN DEFAULT FALSE
);
""")

# -----------------------------
# RESULTS TABLE
# -----------------------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS results (
    id SERIAL PRIMARY KEY,
    sensor_id STRING,
    node_id STRING,
    pump_status INT,
    leak_status TEXT,
    leak_size TEXT,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

conn.commit()
cursor.close()
conn.close()

print("✅ Tables created successfully")