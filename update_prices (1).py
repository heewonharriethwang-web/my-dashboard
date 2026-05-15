"""
희원 자산 대시보드 — 시세 자동 업데이트 스크립트
GitHub Actions에서 실행되어 index.html 내 자산 가격을 최신 시세로 갱신합니다.

업데이트 대상:
  - 삼성전자 (005930.KS)  → id:9
  - SK하이닉스 (000660.KS) → id:10
  - 삼성SDI (006400.KS)   → id:11
  - VOO                    → id:8  (USD→KRW 환율 변환)
  - BTC                    → id:7  (KRW 직접 조회)
"""

import re
import json
import urllib.request
import urllib.error
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
HTML_FILE = "index.html"

# ─── API 호출 헬퍼 ──────────────────────────────────────

def fetch_json(url, timeout=15):
    """URL에서 JSON을 가져온다. 실패 시 None 반환."""
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        print(f"  ⚠ fetch 실패: {url}\n    {e}")
        return None


# ─── 주식 시세 (다중 소스) ──────────────────────────────

def get_stock_price_yfinance(symbol):
    """yfinance 라이브러리로 시세 조회 (가장 안정적)."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        info = ticker.fast_info
        price = getattr(info, "last_price", None) or getattr(info, "previous_close", None)
        if price and price > 0:
            return {"price": price, "source": "yfinance"}
    except Exception as e:
        print(f"  ⚠ yfinance 실패 ({symbol}): {e}")
    return None


def get_stock_price_yahoo_api(symbol):
    """Yahoo Finance REST API로 시세 조회."""
    for host in ["query1", "query2"]:
        url = f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}?range=1d&interval=1d"
        data = fetch_json(url)
        if data:
            meta = data.get("chart", {}).get("result", [{}])[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price and price > 0:
                return {"price": price, "source": "yahoo-api"}
    return None


def get_stock_price(symbol, name=""):
    """여러 소스를 순서대로 시도."""
    for getter in [get_stock_price_yfinance, get_stock_price_yahoo_api]:
        result = getter(symbol)
        if result:
            print(f"  ✅ {name or symbol}: {result['price']:,.2f} (via {result['source']})")
            return result["price"]
    return None


# ─── 환율 ──────────────────────────────────────────────

def get_usdkrw():
    """USD/KRW 환율 조회 (다중 소스)."""
    # 1) yfinance
    result = get_stock_price_yfinance("USDKRW=X")
    if result:
        return result["price"]
    # 2) Yahoo API
    result = get_stock_price_yahoo_api("USDKRW=X")
    if result:
        return result["price"]
    # 3) exchangerate API (무료)
    data = fetch_json("https://open.er-api.com/v6/latest/USD")
    if data and data.get("rates", {}).get("KRW"):
        return data["rates"]["KRW"]
    # 폴백
    print("  ⚠ 환율 조회 전부 실패, 1380 사용")
    return 1380


# ─── BTC ───────────────────────────────────────────────

def get_btc_krw():
    """BTC/KRW 가격 조회 (다중 소스)."""
    # 1) CoinGecko
    data = fetch_json("https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=krw&include_24hr_change=true")
    if data and "bitcoin" in data:
        price = data["bitcoin"]["krw"]
        print(f"  ✅ BTC: ₩{price:,.0f} (via coingecko)")
        return price
    # 2) Binance BTCUSDT × 환율
    binance = fetch_json("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT")
    if binance:
        usd_price = float(binance["lastPrice"])
        rate = get_usdkrw()
        price = round(usd_price * rate)
        print(f"  ✅ BTC: ₩{price:,.0f} (via binance)")
        return price
    # 3) CryptoCompare
    data = fetch_json("https://min-api.cryptocompare.com/data/price?fsym=BTC&tsyms=KRW")
    if data and "KRW" in data:
        price = round(data["KRW"])
        print(f"  ✅ BTC: ₩{price:,.0f} (via cryptocompare)")
        return price
    return None


# ─── HTML 업데이트 ──────────────────────────────────────

def update_asset_price(html, asset_id, new_price):
    """assets 배열에서 특정 id의 price 값을 업데이트한다."""
    pattern = rf"(\{{id:{asset_id},.*?price:)\d+(\}})"
    new_html, count = re.subn(pattern, rf"\g<1>{new_price}\2", html)
    if count > 0:
        print(f"  📝 id:{asset_id} → price:{new_price:,}")
    else:
        print(f"  ❌ id:{asset_id} 패턴을 찾지 못함")
    return new_html


def update_data_updated(html):
    """DATA_UPDATED 날짜를 현재로 업데이트."""
    today = datetime.now(KST)
    date_str = f"{today.year}년 {today.month}월 {today.day}일"
    return re.sub(r"const DATA_UPDATED = '[^']*'", f"const DATA_UPDATED = '{date_str}'", html)


# ─── 메인 ──────────────────────────────────────────────

def main():
    now = datetime.now(KST)
    print(f"🕐 시세 업데이트 시작: {now.strftime('%Y-%m-%d %H:%M KST')}")
    print("=" * 50)

    with open(HTML_FILE, "r", encoding="utf-8") as f:
        html = f.read()

    updated, failed = [], []

    # 1) 환율
    print("\n💱 환율 조회...")
    usdkrw = get_usdkrw()
    print(f"  USD/KRW: {usdkrw:,.2f}")

    # 2) 국내주식
    kr_stocks = [
        {"symbol": "005930.KS", "name": "삼성전자", "id": 9},
        {"symbol": "000660.KS", "name": "SK하이닉스", "id": 10},
        {"symbol": "006400.KS", "name": "삼성SDI", "id": 11},
    ]
    for stock in kr_stocks:
        print(f"\n📈 {stock['name']} ({stock['symbol']}) 조회...")
        price = get_stock_price(stock["symbol"], stock["name"])
        if price:
            html = update_asset_price(html, stock["id"], round(price))
            updated.append(stock["name"])
        else:
            print(f"  ❌ {stock['name']} 전체 조회 실패")
            failed.append(stock["name"])

    # 3) VOO
    print("\n🌐 VOO 조회...")
    voo_price = get_stock_price("VOO", "VOO")
    if voo_price:
        voo_krw = round(voo_price * usdkrw)
        print(f"  VOO KRW: ${voo_price:,.2f} × {usdkrw:,.0f} = ₩{voo_krw:,}")
        html = update_asset_price(html, 8, voo_krw)
        updated.append("VOO")
    else:
        print("  ❌ VOO 전체 조회 실패")
        failed.append("VOO")

    # 4) BTC
    print("\n₿ BTC 조회...")
    btc_price = get_btc_krw()
    if btc_price:
        html = update_asset_price(html, 7, round(btc_price))
        updated.append("BTC")
    else:
        print("  ❌ BTC 전체 조회 실패")
        failed.append("BTC")

    # 5) 날짜 갱신
    if updated:
        html = update_data_updated(html)

    with open(HTML_FILE, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"\n{'='*50}")
    if updated:
        print(f"✅ 성공: {', '.join(updated)}")
    if failed:
        print(f"❌ 실패: {', '.join(failed)}")
    print(f"📄 {HTML_FILE} 저장 완료")


if __name__ == "__main__":
    main()
