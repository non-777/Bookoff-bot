from flask import Flask, request, jsonify

app = Flask(__name__)

# 🔽 GAS が叩いてるエンドポイント
@app.route("/update_bookoff_stock", methods=["POST"])
def update_bookoff_stock():
data = request.get_json(force=True)

url = data.get("url", "")
name = data.get("name", "")

# いまはテスト用に固定で返す
return jsonify({
"ok": True,
"stock": "在庫あり（仮）",
"url": url,
"name": name
})


# Cloud Run 用（必須）
if __name__ == "__main__":
import os
port = int(os.environ.get("PORT", 8080))
app.run(host="0.0.0.0", port=port)
