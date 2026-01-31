from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
return "OK-20260201-AAAA"

@app.route("/update_bookoff_stock", methods=["POST"])
def update_bookoff_stock():
data = request.json
return jsonify({"status": "ok", "received": data})
