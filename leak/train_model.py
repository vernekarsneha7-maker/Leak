from sklearn.ensemble import IsolationForest
import pandas as pd
import os
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
from xgboost import XGBClassifier
import joblib


# -----------------------------
# Load Dataset
# -----------------------------
data = pd.read_excel("leakdetectiondataset.xlsx", engine="openpyxl")

# Normalize column names
data.columns = data.columns.str.strip().str.lower()

# -----------------------------
# Handle Missing Values
# -----------------------------
for col in ["pressure_in_bar", "pressure_out_bar", "flow_in", "flow_out"]:
    data[col] = data[col].fillna(data[col].median())



# -----------------------------
# Feature Engineering
# -----------------------------
data["pressure_drop"] = data["pressure_in_bar"] - data["pressure_out_bar"]
data["flow_loss"] = abs(data["flow_in"] - data["flow_out"])

# -----------------------------
# Leak Label (Balanced)
# -----------------------------

pressure_threshold = data["pressure_drop"].quantile(0.80)
flow_threshold = data["flow_loss"].quantile(0.80)

print("Pressure Threshold:", pressure_threshold)
print("Flow Threshold:", flow_threshold)

data["leak"] = (
    (data["pressure_drop"] >= pressure_threshold) |
    (data["flow_loss"] >= flow_threshold)
).astype(int)

print("Leak distribution:")
print(data["leak"].value_counts())

# -----------------------------
# Leak Size Label
# -----------------------------
def get_size(row):

    if row["leak"] == 0:
        return -1

    score = (
        row["pressure_drop"] / pressure_threshold +
        row["flow_loss"] / flow_threshold
    )

    if score > 3:
        return 2      # Large

    elif score > 2:
        return 1      # Medium

    else:
        return 0      # Small
    
data["leak_size"] = data.apply(get_size, axis=1)
print(data["leak_size"].value_counts())
    
print("\nLeak Size Distribution")


# -----------------------------
# FEATURES (FINAL FIXED SET)
# -----------------------------
features = [
    "pressure_in_bar",
    "pressure_out_bar",
    "pressure_drop",
    "flow_loss"
]
print(data["pressure_drop"].describe())
print(data["flow_loss"].describe())

# -----------------------------
# Leak Model
# -----------------------------
for col in features:
    if col not in data.columns:
        raise Exception(f"Missing column: {col}")
    
X = data[features]
y = data["leak"]

iso_model = IsolationForest(
    n_estimators=300,
    contamination=0.20,
    random_state=42
)

iso_model.fit(X)
iso_pred = iso_model.predict(X)

iso_pred = [1 if x == -1 else 0 for x in iso_pred]

print("\nIsolation Forest Detection")
print(classification_report(y, iso_pred))

print("✅ Isolation Forest saved")





X_train, X_test, y_train, y_test = train_test_split(
    X,
    y,
    test_size=0.2,
    random_state=42,
    stratify=y
)

leak_model = XGBClassifier(
    n_estimators=200,
    max_depth=5,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    eval_metric="logloss",
    random_state=42
)
leak_model.fit(X_train, y_train)

pred = leak_model.predict(X_test)
print("Leak Accuracy:", accuracy_score(y_test, pred))
print(classification_report(y_test, pred))

# -----------------------------
# Size Model (only leak rows)
# -----------------------------
size_data = data[data["leak_size"] >= 0]

if len(size_data) == 0:
    raise Exception(
        "No rows available for leak size training"
    )

print("\nSize Data Shape")
print(size_data.shape)

print("\nLeak Size Distribution")
print(size_data["leak_size"].value_counts())

X_size = size_data[features]
y_size = size_data["leak_size"]

size_model = XGBClassifier(
    objective="multi:softprob",
    num_class=3,
    eval_metric="mlogloss",
    random_state=42
)

print("\nLeak Size Distribution")
print(y_size.value_counts())

print("\nUnique Classes")
print(sorted(y_size.unique()))
size_model.fit(X_size, y_size)
print("Leak Size Distribution:")
print(y_size.value_counts())


print(data["leak_size"].value_counts(dropna=False))

print(data[[
    "pressure_drop",
    "flow_loss",
    "leak",
    "leak_size"
]].head(20))


# -----------------------------
# Save Models
# -----------------------------
os.makedirs("models", exist_ok=True)

joblib.dump(leak_model, "models/leak_model.pkl")
joblib.dump(size_model, "models/size_model.pkl")

joblib.dump(
    iso_model,
    "models/isolation_forest.pkl"
)

print("✅ Leak Model Saved")
print("✅ Size Model Saved")
print("✅ Isolation Forest Saved")
print(data.columns)
