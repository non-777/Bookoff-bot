from flask import Flask, request, jsonify
import os

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
return "OK"

@app.route("/update_bookoff_stock", methods=["POST"])
def update_bookoff_stock():
data = request.json
return jsonify({"status": "ok", "received": data})

# ↓ これはローカル用だけ残す
if __name__ == "__main__":
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
