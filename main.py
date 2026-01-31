import os
import json
import time
import uuid
import threading
from queue import Queue, Empty
from typing import List, Dict, Any, Optional

import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify, Response

import google.auth
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ----------------------------
# 設定（ここだけあとで埋める）
# ----------------------------
# スプレッドシートID（URLの /d/ と /edit の間のやつ）
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "").strip()

# シート名（例: "シート1"）
SHEET_NAME = os.environ.get("SHEET_NAME", "シート1").strip()

# 読み取り元（BookOffの商品URL列）
URL_COL_RANGE = os.environ.get("URL_COL_RANGE", "A2:A").strip()

# 書き込み先（例: 商品名=B, 価格=C, 店舗名=D, 店舗住所=E, ネット在庫=F）
OUT_RANGE = os.environ.get("OUT_RANGE", "B2:F").strip()

# User-Agent（軽い対策。強い回避とかはせえへん）
UA = os.environ.get(
"UA",
"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
"(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
)

# どれくらいの間隔でアクセスするか（秒）
REQUEST_INTERVAL_SEC = float(os.environ.get("REQUEST_INTERVAL_SEC", "0.6"))

# タイムアウト（秒）
HTTP_TIMEOUT_SEC = float(os.environ.get("HTTP_TIMEOUT_SEC", "12"))

# ----------------------------
# Flask
# ----------------------------
app = Flask(__name__)

# 進捗管理（簡易）
JOBS: Dict[str, Dict[str, Any]] = {}
JOB_QUEUES: Dict[str, "Queue[dict]"] = {}


def sheets_client():
"""
Cloud Run の実行サービスアカウントのデフォルト認証で Sheets API を叩く。
→ サービスアカウントキー不要（ここがデカい）
"""
creds, _ = google.auth.default(
scopes=["https://www.googleapis.com/auth/spreadsheets"]
)
return build("sheets", "v4", credentials=creds, cache_discovery=False)


def read_urls(svc) -> List[str]:
"""
A列のURLを全部読む（空行は飛ばす）
"""
if not SPREADSHEET_ID:
raise ValueError("SPREADSHEET_ID が空やで。環境変数に入れてな。")

range_ = f"{SHEET_NAME}!{URL_COL_RANGE}"
resp = svc.spreadsheets().values().get(
spreadsheetId=SPREADSHEET_ID, range=range_
).execute()
rows = resp.get("values", [])
urls = []
for r in rows:
if not r:
continue
u = (r[0] or "").strip()
if u:
urls.append(u)
return urls


def parse_bookoff_page(html: str, url: str) -> Dict[str, Any]:
"""
BookOffページを “雑に” 解析（サイト構造で変わる可能性ある）
- 商品名
- 価格
- 店舗名/住所（拾えたら）
- 在庫（在庫なしっぽい文言から判断）
"""
soup = BeautifulSoup(html, "html.parser")
text = soup.get_text(" ", strip=True)

# 商品名候補
title = None
# よくある h1 から拾う
h1 = soup.find("h1")
if h1 and h1.get_text(strip=True):
title = h1.get_text(strip=True)

# 価格候補（￥/円 を探す）
price = ""
# 「円」含む要素を軽くスキャン
for cand in soup.find_all(["span", "p", "div"]):
t = cand.get_text(" ", strip=True)
if not t:
continue
if "円" in t and any(ch.isdigit() for ch in t):
# なるべく短めのを選ぶ
if len(t) <= 20:
price = t
break

# 店舗名/住所（拾えたら）
shop_name = ""
shop_addr = ""
# 「BOOKOFF」含む文言からざっくり抽出
if "BOOKOFF" in text:
# 長文の中から1行っぽいとこを拾う
parts = [p for p in text.split(" ") if "BOOKOFF" in p]
if parts:
shop_name = parts[0][:60]

# 在庫判定（超ざっくり）
# ※ここは現物見て単語を増やした方が精度上がる
out_of_stock_keywords = [
"在庫なし",
"在庫がありません",
"売り切れ",
"SOLD OUT",
"販売終了",
]
in_stock = "○"
for kw in out_of_stock_keywords:
if kw.lower() in text.lower():
in_stock = "×"
break

return {
"url": url,
"title": title or "",
"price": price,
"shop_name": shop_name,
"shop_addr": shop_addr,
"stock": in_stock,
}


def fetch_one(url: str) -> Dict[str, Any]:
headers = {"User-Agent": UA}
r = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT_SEC)
r.raise_for_status()
return parse_bookoff_page(r.text, url)


def batch_write(svc, start_row: int, values_2d: List[List[Any]]):
"""
B〜Fにまとめて書き込み
start_row はシート上の行番号（2〜）
values_2d は [[商品名, 価格, 店舗名, 店舗住所, 在庫], ...]
"""
end_row = start_row + len(values_2d) - 1
# 例: シート1!B2:F100
range_ = f"{SHEET_NAME}!B{start_row}:F{end_row}"
body = {"values": values_2d}
svc.spreadsheets().values().update(
spreadsheetId=SPREADSHEET_ID,
range=range_,
valueInputOption="USER_ENTERED",
body=body,
).execute()


def run_job(job_id: str):
q = JOB_QUEUES[job_id]
JOBS[job_id]["status"] = "running"

try:
svc = sheets_client()
urls = read_urls(svc)
total = len(urls)
JOBS[job_id]["total"] = total

q.put({"type": "meta", "total": total})

# まとめて更新（50件ずつ）
buf = []
buf_start_row = 2 # A2開始なのでB2開始
done = 0

for idx, u in enumerate(urls, start=1):
try:
data = fetch_one(u)
rowvals = [
data["title"],
data["price"],
data["shop_name"],
data["shop_addr"],
data["stock"],
]
except Exception as ex:
# 失敗しても止めずに×扱いで残す
rowvals = ["", "", "", "", "×"]

buf.append(rowvals)

# 進捗をイベントで流す
done = idx
q.put({"type": "progress", "done": done, "total": total})

# 一定数たまったら書き込み
if len(buf) >= 50:
batch_write(svc, buf_start_row, buf)
buf_start_row += len(buf)
buf = []

time.sleep(REQUEST_INTERVAL_SEC)

# 残り書き込み
if buf:
batch_write(svc, buf_start_row, buf)

JOBS[job_id]["status"] = "done"
q.put({"type": "done", "message": "Stock updated successfully!"})

except Exception as e:
JOBS[job_id]["status"] = "error"
q.put({"type": "error", "message": str(e)})


@app.get("/")
def index():
# 簡易UI（スクショの雰囲気に寄せる）
html = f"""
<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<title>GB更新</title>
<style>
body{{font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans JP", sans-serif; background:#f3f5f8;}}
.wrap{{max-width:720px;margin:60px auto;padding:24px;}}
.card{{background:#fff;border-radius:14px;padding:24px;box-shadow:0 8px 30px rgba(0,0,0,.08);}}
input{{width:100%;padding:14px 16px;font-size:16px;border:1px solid #d6dbe3;border-radius:10px;}}
button{{margin-top:12px;width:100%;padding:14px 16px;font-size:16px;border:0;border-radius:10px;background:#3b6ea8;color:#fff;cursor:pointer;}}
#msg{{margin-top:16px;color:#333;}}
#warn{{margin-top:6px;color:#c0392b;}}
</style>
</head>
<body>
<div class="wrap">
<div class="card">
<input id="email" placeholder="メールアドレス（任意）" />
<button id="btn">更新</button>
<div id="msg"></div>
<div id="warn"></div>
</div>
</div>
<script>
const btn = document.getElementById('btn');
const msg = document.getElementById('msg');
const warn = document.getElementById('warn');

btn.onclick = async () => {{
msg.textContent = "開始中...";
warn.textContent = "";

const email = document.getElementById('email').value || "";

const res = await fetch('/start', {{
method:'POST',
headers:{{'Content-Type':'application/json'}},
body: JSON.stringify({{email}})
}});
const data = await res.json();
if (!data.job_id) {{
warn.textContent = data.error || "開始失敗";
return;
}}

const es = new EventSource('/events/' + data.job_id);
es.onmessage = (ev) => {{
const d = JSON.parse(ev.data);
if (d.type === 'progress') {{
msg.textContent = `${{d.done}}/${{d.total}} 取得完了。`;
warn.textContent = "現在更新中のため、全て完了してから再度お試しください。";
}}
if (d.type === 'done') {{
msg.textContent = "更新完了。";
warn.textContent = "";
es.close();
}}
if (d.type === 'error') {{
warn.textContent = "エラー: " + d.message;
es.close();
}}
}};
}};
</script>
</body>
</html>
"""
return Response(html, mimetype="text/html")


@app.post("/start")
def start():
# 連打対策（同時に走らせたくないならここで弾く）
job_id = str(uuid.uuid4())
JOBS[job_id] = {"status": "queued", "total": 0}
JOB_QUEUES[job_id] = Queue()

t = threading.Thread(target=run_job, args=(job_id,), daemon=True)
t.start()

return jsonify({"job_id": job_id})


@app.get("/events/<job_id>")
def events(job_id: str):
if job_id not in JOB_QUEUES:
return Response("not found", status=404)

q = JOB_QUEUES[job_id]

def stream():
# SSE
while True:
try:
item = q.get(timeout=30)
yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
if item.get("type") in ("done", "error"):
break
except Empty:
# keep-alive
yield "data: {}\n\n"

return Response(stream(), mimetype="text/event-stream")


@app.post("/update_bookoff_stock")
def update_bookoff_stock():
"""
APIで叩きたい時用（スクショで見えてた /update_bookoff_stock 想定）
"""
job_id = str(uuid.uuid4())
JOBS[job_id] = {"status": "queued", "total": 0}
JOB_QUEUES[job_id] = Queue()

t = threading.Thread(target=run_job, args=(job_id,), daemon=True)
t.start()

return jsonify({"message": "started", "job_id": job_id})


# Cloud Run 用
if __name__ == "__main__":
port = int(os.environ.get("PORT", "8080"))
app.run(host="0.0.0.0", port=port)
