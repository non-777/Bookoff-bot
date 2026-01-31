from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
    return "OK"

@app.route("/update_bookoff_stock", methods=["POST"])
def update_bookoff_stock():
    data = request.get_json(silent=True) or {}
    return jsonify({"status": "ok", "received": data})
