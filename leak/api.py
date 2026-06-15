from flask import Flask, request, jsonify
from model_pipeline import predict_leak

app = Flask(__name__)

@app.route("/predict", methods=["POST"])
def predict():

    data = request.get_json()

    if not data:
        return jsonify({"error": "No input"}), 400

    result = predict_leak(data)

    return jsonify(result)

if __name__ == "__main__":
    app.run(debug=True)