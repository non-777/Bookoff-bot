from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route("/", methods=["GET"])
def health():
return "OK"

@app.route("/update_bookoff_stock", methods=["POST"])
def update_bookoff_stock():
try:
data = request.get_json(silent=True) or {}

url = data.get("url", "")
name = data.get("name", "")

return jsonify({
"ok": True,
"stock": "在庫あり（テスト）",
"url": url,
"name": name
})

except Exception as e:
return jsonify({
"ok": False,
"error": str(e)
}), 500


if __name__ == "__main__":
import os
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
