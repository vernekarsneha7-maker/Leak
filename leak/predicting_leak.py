import pandas as pd
import joblib

# -----------------------------
# Load Models
# -----------------------------
leak_model = joblib.load("models/leak_model.pkl")
size_model = joblib.load("models/size_model.pkl")

# -----------------------------
# Load Data
# -----------------------------
data = pd.read_csv("leakdetectiontestdataset.csv")

# -----------------------------
# Handle Missing Values
# -----------------------------
data["pressure_in_bar"] = data["pressure_in_bar"].fillna(data["pressure_in_bar"].median())
data["pressure_out_bar"] = data["pressure_out_bar"].fillna(data["pressure_out_bar"].median())
data["flow_in"] = data["flow_in"].fillna(data["flow_in"].median())
data["flow_out"] = data["flow_out"].fillna(data["flow_out"].median())

# -----------------------------
# Feature Engineering (MUST MATCH TRAINING)
# -----------------------------
data["pressure_drop"] = data["pressure_in_bar"] - data["pressure_out_bar"]
data["flow_loss"] = abs(data["flow_in"] - data["flow_out"])

features = ["pressure_in_bar", "pressure_out_bar", "pressure_drop", "flow_loss"]

# -----------------------------
# Prediction Loop (ROW BY ROW)
# -----------------------------
for index, row in data.iterrows():

    X_input = pd.DataFrame([row[features].values], columns=features)

    leak_pred = leak_model.predict(X_input)[0]

    # -----------------------------
    # NO LEAK
    # -----------------------------
    if leak_pred == 0:
        print(f"Sensor {row['sensor_id']} → No Leak Detected")
        print("-" * 40)
        continue

    # -----------------------------
    # LEAK DETECTED
    # -----------------------------
    size_pred = size_model.predict(X_input)[0]

    size_map = {0: "SMALL", 1: "MEDIUM", 2: "LARGE"}
    leak_size_category = size_map[size_pred]

    # Optional: numeric estimation (if needed for realism)
    leak_size_value = (row["flow_loss"] * 10) + (row["pressure_drop"] * 5)

    # Location handling
    latitude = row.get("latitude", row.get("Latitude", "N/A"))
    longitude = row.get("longitude", row.get("Longitude", "N/A"))

    print("🚨 LEAK DETECTED!")
    print(f"Row: {index}")
    print(f"Sensor ID: {row['sensor_id']}")
    print(f"Node ID: {row['node_id']}")
    print(f"Location: ({latitude}, {longitude})")
    print(f"Leak Size Category: {leak_size_category}")
    print(f"Estimated Leak Size: {round(leak_size_value, 2)} mm")
    print("-" * 40)