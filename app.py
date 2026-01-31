from flask import Flask, request, jsonify, render_template_string
from playwright.sync_api import sync_playwright

app = Flask(__name__)

HTML = """
<!doctype html>
<html>
<head>
  <meta charset="utf-8"/>
  <title>BookOff 在庫チェッカー</title>
  <style>
    body { font-family: -apple-system, system-ui; padding: 18px; }
    input { width: 520px; max-width: 90vw; padding: 8px; }
    button { padding: 8px 12px; margin-left: 6px; }
    pre { background:#f6f6f6; padding:12px; border-radius:8px; overflow:auto; }
  </style>
</head>
<body>
  <h2>BookOff 在庫チェッカー（手動更新）</h2>
  <p>商品URL入れて「更新」押したら、在庫店舗のリンクを抜く。</p>
  <input id="url" value="https://shopping.bookoff.co.jp/used/0000992402"/>
  <button onclick="go()">更新</button>
  <p id="status"></p>
  <pre id="out"></pre>

<script>
async function go(){
 const url = document.getElementById("url").value.trim();
 document.getElementById("status").textContent = "取得中…";
 document.getElementById("out").textContent = "";
 const r = await fetch("/fetch", {
   method:"POST",
   headers:{"Content-Type":"application/json"},
   body: JSON.stringify({url})
});
const j = await r.json();
document.getElementById("status").textContent = j.ok ? ("取得OK: " + j.count + "件") : ("失敗: " + j.error);
if(j.ok){
  document.getElementById("out").textContent = j.items.map(x => `${x.name}\n${x.href}`).join("\\n\\n");
 }
}
</script>
</body>
</html>
"""

@app.get("/")
def index():
    return render_template_string(HTML)

@app.post("/fetch")
def fetch():
    data = request.get_json(force=True)
    url = data.get("url", "")
    if not url.startswith("http"):
        return jsonify(ok=False, error="URLが変やで"), 400

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=60000)

            # 「在庫」ボタンをクリック（サイト側で文言が違う場合があるから候補を広めに）
            # ここは必要なら後で調整するポイント
            candidates = [
                "text=在庫",
                "text=在庫のある店舗",
                "text=在庫を確認",
                "text=店舗在庫",
            ]
            clicked = False
            for sel in candidates:
                try:
                    page.locator(sel).first.click(timeout=2000)
                    clicked = True
                    break
                except:
                    pass

            if not clicked:
                browser.close()
                return jsonify(ok=False, error="在庫ボタン見つからんかった（文言違うかも）")

            # モーダルの店舗リストを待つ
            page.wait_for_selector("ul.modalStoreInformation_store a", timeout=15000)
            links = page.locator("ul.modalStoreInformation_store a").all()

            items = []
            for a in links:
                name = (a.inner_text() or "").strip()
                href = (a.get_attribute("href") or "").strip()
                if href and href.startswith("/"):
                    href = "https://www.bookoff.co.jp" + href
                if href:
                    items.append({"name": name, "href": href})

            browser.close()
            return jsonify(ok=True, count=len(items), items=items)

    except Exception as e:
        return jsonify(ok=False, error=str(e))

if __name__ == "__main__":
    app.run(port=5050, debug=True)
