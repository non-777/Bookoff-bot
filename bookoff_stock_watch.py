import re
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

# 使い方:
# python3 bookoff_stock_watch.py "https://shopping.bookoff.co.jp/used/0000992402"
#
# Enter = 更新（在庫を取り直す）
# q + Enter = 終了

def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()

def extract_stores(page):
    # 1) まず「在庫」っぽいボタンを探してクリック
    # 画面右の「在庫なし」表示の近く/「入荷の…」など色々あるので、候補を広めに取る
    candidates = [
        "text=在庫",
        "text=店舗",
        "text=入荷",
        "text=入荷のお知らせ",
        "text=在庫を確認",
        "text=在庫あり",
    ]

    clicked = False
    last_err = None

    for c in candidates:
        try:
            loc = page.locator(c).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                clicked = True
                break
        except Exception as e:
            last_err = e

    if not clicked:
        # 「在庫」文字がボタンじゃなくて別要素の場合もあるから、リンク/ボタンを総当たりで探す
        try:
            btn = page.locator("button:has-text('在庫'), a:has-text('在庫'), button:has-text('入荷'), a:has-text('入荷')").first
            if btn.count() > 0 and btn.is_visible():
                btn.click()
                clicked = True
        except Exception as e:
            last_err = e

    if not clicked:
        raise RuntimeError(f"在庫ボタンが見つからんかった…（候補クリック失敗）: {last_err}")

    # 2) モーダルが出るまで待つ
    # あなたの画像やと、モーダル内に「商品が入荷した店舗」って文字が出る
    try:
        page.wait_for_selector("text=商品が入荷した店舗", timeout=8000)
    except PWTimeoutError:
        # モーダル文言が違う可能性もあるので、もう一段ゆるく待つ
        page.wait_for_selector("[class*='modal']", timeout=8000)

   # 3) 店舗名っぽい要素を拾う
   # まずモーダル内のテキストをざっくり取り、店名候補を抽出
   modal = page.locator("[class*='modal']").first
   text = normalize_space(modal.inner_text())

   # よくある店名表記: "BOOKOFF ○○店"
   stores = []
   for m in re.finditer(r"(BOOKOFF\s*[^\n]+?店)", text):
       stores.append(normalize_space(m.group(1)))

   # 重複削除
   uniq = []
   seen = set()
   for s in stores:
       if s not in seen:
           uniq.append(s)
           seen.add(s)

    return uniq, text

def main():
    if len(sys.argv) < 2:
        print('使い方: python3 bookoff_stock_watch.py "商品URL"')
        sys.exit(1)

    url = sys.argv[1]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False) # 画面出した方が安定しやすい
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(800) # ちょい待つ

        print("\nEnterで更新 / qで終了\n")

        while True:
            cmd = input("更新する？(Enter/q) > ").strip().lower()
            if cmd == "q":
                break

            # ページをリロードしてから在庫を取り直す（あなたの“更新ボタン”）
            page.reload(wait_until="domcontentloaded")
            page.wait_for_timeout(800)

            try:
                stores, modal_text = extract_stores(page)
                print("\n--- 結果 ---")
                if stores:
                    for i, s in enumerate(stores, 1):
                        print(f"{i}. {s}")
                else:
                     print("店名の抽出に失敗したか、在庫が0かも。モーダル文章だけ下に出すで。")
                     print(modal_text[:800] + ("..." if len(modal_text) > 800 else ""))
                print("------------\n")
            except Exception as e:
                print(f"\nエラー: {e}\n")

        browser.close()

if __name__ == "__main__":
    main()
