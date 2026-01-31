import os
import time
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, jsonify

import google.auth
from googleapiclient.discovery import build

app = Flask(__name__)

# ====== 環境変数（Cloud Runで設定するやつ）======
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID", "").strip() # /d/ここ/ の部分
SHEET_NAME = os.environ.get("SHEET_NAME", "シート1").strip() # タブ名
MIN_DELAY_MS = int(os.environ.get("MIN_DELAY_MS", "900")) # アクセス間隔(ミリ秒)

def sheets_client():
# ★鍵ファイル不要：Cloud Runのサービスアカウントで認証する
creds, _ = google.auth.default(scopes=[
"https://www.googleapis.com/auth/spreadsheets"
])
return build("sheets", "v4", credentials=creds, cache_discovery=False)

def read_urls(svc):
# A2:A に BookOff 商品URLが入ってる想定
rng = f"{SHEET_NAME}!A2:A"
res = svc.spreadsheets().values().get(
spreadsheetId=SPREADSHEET_ID,
range=rng
).execute()
rows = res.get("values", [])
return [r[0].strip() for r in rows if r and r[0].strip()]

def batch_write(svc, start_row, values_2d):
# B〜F：商品名/価格/店舗名/住所/在庫
end_row = start_row + len(values_2d) - 1
rng = f"{SHEET_NAME}!B{start_row}:F{end_row}"
svc.spreadsheets().values().update(
spreadsheetId=SPREADSHEET_ID,
range=rng,
valueInputOption="USER_ENTERED",
body={"values": values_2d}
).execute()

def parse_bookoff(html: str):
soup = BeautifulSoup(html, "html.parser")
text = soup.get_text(" ", strip=True)

# タイトル
title = ""
h1 = soup.find("h1")
if h1:
title = h1.get_text(" ", strip=True)

# 価格（ざっくり「円」から拾う）
price = ""
# 文字列から最初の「◯◯◯円」を探す（雑だけどまず動かす）
import re
m = re.search(r"([0-9]{2,7})\s*円", text.replace(",", ""))
if m:
price = m.group(1)

# 店舗名/住所（取れたら）
shop = ""
addr = ""
if "BOOKOFF" in text:
# 雰囲気で拾うだけ（必要なら後で精度上げる）
m2 = re.search(r"(BOOKOFF[^ ]{0,40})", text)
if m2:
shop = m2.group(1)

# 住所っぽい（都道府県で始まるもの）
m3 = re.search(r"(北海道|東京都|大阪府|京都府|神奈川県|愛知県|福岡県|兵庫県|埼玉県|千葉県|広島県|静岡県|宮城県|茨城県|栃木県|群馬県|新潟県|長野県|岐阜県|三重県|滋賀県|奈良県|和歌山県|岡山県|山口県|熊本県|鹿児島県|沖縄県)[^ ]{6,60}", text)
if m3:
addr = m3.group(0)

# 在庫：売り切れっぽい文言があれば×
soldout = any(k.lower() in text.lower() for k in ["在庫なし", "品切れ", "sold out", "売り切れ", "販売終了"])
stock = "×" if soldout else "○"

return title, price, shop, addr, stock

def fetch_one(url: str):
r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
r.raise_for_status()
return parse_bookoff(r.text)

@app.get("/")
def root():
# 恐竜ページを消して「動いてる」確認用
return "ok", 200

@app.post("/update_bookoff_stock")
def update_bookoff_stock():
# 仕様互換：email受け取るけど使わん（将来通知したいなら使える）
_email = (request.json or {}).get("email", "")

if not SPREADSHEET_ID:
return jsonify({"error": "SPREADSHEET_ID is empty (Cloud Runの環境変数に入れてな)"}), 500

svc = sheets_client()
urls = read_urls(svc)

total = len(urls)
if total == 0:
return jsonify({"message": "no urls in column A"}), 200

# 50件ずつまとめて書く（Sheets API節約）
buf = []
buf_start_row = 2

done = 0
for i, url in enumerate(urls, start=1):
try:
title, price, shop, addr, stock = fetch_one(url)
buf.append([title, price, shop, addr, stock])
except Exception:
buf.append(["", "", "", "", "×"])

done = i

if len(buf) >= 50:
batch_write(svc, buf_start_row, buf)
buf_start_row += len(buf)
buf = []

time.sleep(MIN_DELAY_MS / 1000.0)

if buf:
batch_write(svc, buf_start_row, buf)

return jsonify({"message": "Stock updated successfully", "updated": done, "total": total}), 200
