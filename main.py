import os
import time
import requests
import pandas as pd
import yfinance as yf
import json
from datetime import datetime
from dotenv import load_dotenv
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

LOG_PATH = Path("data/logs.json")
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID")

# ── IDX top liquid emitens ─────────────────────────────────────────────────────
IDX_TICKERS = [
    "BBCA", "BBRI", "BMRI", "BBNI", "BRIS",
    "TLKM", "ASII", "UNVR", "ICBP", "INDF",
    "GOTO", "BYAN", "ADRO", "PTBA", "ITMG",
    "ANTM", "TINS", "INCO", "MDKA", "HRUM",
    "CPIN", "JPFA", "MAIN", "TBIG", "TOWR",
    "EXCL", "ISAT", "SMGR", "INTP",
    "KLBF", "SIDO", "MIKA", "HEAL", "SILO",
    "PWON", "BSDE", "CTRA", "LPKR", "SMRA",
    "AKRA", "ESSA", "PGAS", "MEDC", "ELSA",
    "MTEL", "FILM", "ACES", "MAPI", "LPPF",
    "HMSP", "GGRM", "WIIM", "AMRT", "MIDI",
]

YFINANCE_SUFFIX = ".JK"
MAX_WORKERS     = 10   # concurrent yfinance threads
MAX_RETRIES     = 2

# ── Sector mapping for Big Player analysis ─────────────────────────────────────
SECTOR_MAP = {
    "BBCA": "Banking",  "BBRI": "Banking",  "BMRI": "Banking",
    "BBNI": "Banking",  "BRIS": "Banking",
    "TLKM": "Telco",    "EXCL": "Telco",    "ISAT": "Telco",    "MTEL": "Telco",
    "UNVR": "Consumer", "ICBP": "Consumer", "INDF": "Consumer",
    "GOTO": "Tech",
    "BYAN": "Coal",     "ADRO": "Coal",     "PTBA": "Coal",
    "ITMG": "Coal",     "HRUM": "Coal",
    "ANTM": "Mining",   "TINS": "Mining",   "INCO": "Mining",   "MDKA": "Mining",
    "ASII": "Industrial",
    "CPIN": "Agri",     "JPFA": "Agri",     "MAIN": "Agri",
    "TBIG": "Tower",    "TOWR": "Tower",
    "SMGR": "Cement",   "INTP": "Cement",
    "KLBF": "Health",   "SIDO": "Health",   "MIKA": "Health",
    "HEAL": "Health",   "SILO": "Health",
    "PWON": "Property", "BSDE": "Property", "CTRA": "Property",
    "LPKR": "Property", "SMRA": "Property",
    "AKRA": "Energy",   "ESSA": "Energy",   "PGAS": "Energy",
    "MEDC": "Energy",   "ELSA": "Energy",
    "ACES": "Retail",   "MAPI": "Retail",   "LPPF": "Retail",
    "AMRT": "Retail",   "MIDI": "Retail",
    "HMSP": "Tobacco",  "GGRM": "Tobacco",  "WIIM": "Tobacco",
    "FILM": "Media",
}


def get_ticker_data(ticker: str, retries: int = MAX_RETRIES) -> Optional[dict]:
    """Fetch OHLCV + derived metrics for a single ticker via yfinance, with retries."""
    for attempt in range(1, retries + 2):
        try:
            tk   = yf.Ticker(ticker + YFINANCE_SUFFIX)
            hist = tk.history(period="20d")
            if hist.empty or len(hist) < 6:
                return None

            today      = hist.iloc[-1]
            prev       = hist.iloc[-2]
            close      = today["Close"]
            prev_close = prev["Close"]

            avg_vol_10  = hist["Volume"].iloc[-11:-1].mean()
            vol_ratio   = today["Volume"] / avg_vol_10 if avg_vol_10 > 0 else 0
            pct_change  = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
            tx_value_bn = (today["Volume"] * close) / 1_000_000_000  # billion IDR

            return {
                "ticker":      ticker,
                "close":       close,
                "pct_change":  pct_change,
                "volume":      today["Volume"],
                "avg_vol_10d": avg_vol_10,
                "vol_ratio":   vol_ratio,
                "tx_value_bn": tx_value_bn,
            }
        except Exception as e:
            if attempt <= retries:
                time.sleep(1)
            else:
                print(f"[WARN] {ticker} failed after {retries + 1} attempts: {e}")
                return None


def fetch_all_tickers() -> list[dict]:
    """Fetch all IDX tickers concurrently using a thread pool."""
    results = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(get_ticker_data, t): t for t in IDX_TICKERS}
        for future in as_completed(futures):
            data = future.result()
            if data:
                results.append(data)
    return results


# IDX endpoints to try in order
_IDX_ENDPOINTS = [
    "https://www.idx.co.id/umbraco/Surface/StockData/GetStockSummary",
    "https://www.idx.co.id/primary/TradingSummary/GetStockSummary",
]

_IDX_HEADERS = {
    "User-Agent":      (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9,id;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer":         "https://www.idx.co.id/id/data-pasar/data-saham/ringkasan-perdagangan-saham/",
    "Origin":          "https://www.idx.co.id",
    "Connection":      "keep-alive",
    "DNT":             "1",
}


def _make_idx_session() -> requests.Session:
    """Create a session with IDX cookies by visiting the homepage first."""
    session = requests.Session()
    session.headers.update(_IDX_HEADERS)
    try:
        session.get("https://www.idx.co.id/", timeout=10)
    except Exception:
        pass  # best-effort warm-up
    return session


def fetch_idx_foreign_flow() -> pd.DataFrame:
    """
    Fetch net foreign buy/sell from IDX public API.
    Uses a session + homepage warm-up to bypass 403 bot protection.
    Tries multiple endpoints. Returns an empty DataFrame on failure.
    """
    session = _make_idx_session()
    params  = {"start": 0, "length": 9999, "draw": 1}

    rows = []
    for url in _IDX_ENDPOINTS:
        try:
            resp = session.get(url, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("data", [])
            if rows:
                print(f"[INFO] IDX foreign flow fetched from: {url}")
                break
        except Exception as e:
            print(f"[WARN] IDX endpoint {url} failed: {e}")
            continue

    if not rows:
        print("[WARN] All IDX endpoints failed — foreign flow unavailable.")
        return pd.DataFrame()

    df = pd.DataFrame(rows)
    col_map = {
        "StockCode":   "ticker",
        "ForeignBuy":  "foreign_buy",
        "ForeignSell": "foreign_sell",
        "Close":       "close_idx",
        "Volume":      "volume_idx",
        "Value":       "value_idx",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})

    for col in ["foreign_buy", "foreign_sell", "value_idx"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "foreign_buy" in df.columns and "foreign_sell" in df.columns:
        df["net_foreign"]    = df["foreign_buy"] - df["foreign_sell"]
        df["net_foreign_bn"] = df["net_foreign"] / 1_000_000_000

    if "value_idx" in df.columns:
        df["tx_value_bn"] = df["value_idx"] / 1_000_000_000

    return df


def generate_big_player_insight(all_data: list[dict], unusual: list[dict]) -> str:
    """Generate Big Player analysis appended below the raw screener data."""
    if not all_data:
        return ""

    top_val = sorted(all_data, key=lambda x: x["tx_value_bn"], reverse=True)[:10]

    # ── STEP 1: Big Player Detection ──────────────────────────────────────────
    akumulasi: list[dict] = []
    markup:    list[dict] = []
    distribusi: list[dict] = []
    for d in top_val:
        pct = d["pct_change"]
        if pct > 5.0:
            markup.append(d)
        elif pct < -2.0:
            distribusi.append(d)
        else:
            akumulasi.append(d)

    # ── STEP 2: Sector value aggregation ──────────────────────────────────────
    sector_value: dict[str, float] = {}
    for d in all_data:
        sector = SECTOR_MAP.get(d["ticker"], "Other")
        sector_value[sector] = sector_value.get(sector, 0) + d["tx_value_bn"]
    top_sectors = sorted(sector_value.items(), key=lambda x: x[1], reverse=True)

    # Dominant sectors among top-10-value stocks (preserve insertion order)
    bp_sectors: list[str] = []
    for d in top_val[:5]:
        s = SECTOR_MAP.get(d["ticker"], "Other")
        if s not in bp_sectors:
            bp_sectors.append(s)
    bp_sectors = bp_sectors[:2]

    # ── STEP 3: Volume validation ──────────────────────────────────────────────
    vol_confirmed = len(unusual) >= 3

    # ── STEP 4 & 5: Momentum + Market condition ───────────────────────────────
    avg_pct   = sum(d["pct_change"] for d in all_data) / len(all_data)
    gainers   = [d for d in all_data if d["pct_change"] > 0]
    high_risk = [d for d in all_data if d["pct_change"] > 10]
    broad_positive = len(gainers) > len(all_data) * 0.6

    if avg_pct > 1.5:
        market_label = "Bullish"
    elif avg_pct > 0.3:
        market_label = "Bullish ringan"
    elif avg_pct > -0.5:
        market_label = "Sideways"
    else:
        market_label = "Weak"

    # ── Risk classification ────────────────────────────────────────────────────
    if high_risk and not vol_confirmed:
        risk_level  = "Tinggi"
        risk_reason = "Ada saham +10% tanpa dukungan unusual volume → pergerakan belum terkonfirmasi"
    elif markup and vol_confirmed:
        risk_level  = "Sedang"
        risk_reason = "Markup terkonfirmasi volume, tapi momentum sudah berjalan — jangan late entry"
    elif not vol_confirmed:
        risk_level  = "Sedang"
        risk_reason = "Tidak ada unusual volume yang cukup → pergerakan belum fully confirmed"
    else:
        risk_level  = "Rendah"
        risk_reason = "Volume mendukung, pola akumulasi terkonfirmasi"

    # ── Build lines ────────────────────────────────────────────────────────────
    L = ["", "---", ""]

    L.append("🧠 *Big Player Insight*")
    sectors_str = " & ".join(bp_sectors) if bp_sectors else "belum jelas"
    L.append(f"- Big player terlihat masuk di: *{sectors_str}*")

    if akumulasi:
        L.append("- Kandidat akumulasi:")
        for d in akumulasi[:3]:
            L.append(
                f"  - `{d['ticker']}` → value {d['tx_value_bn']:.1f}B, "
                f"naik tipis {d['pct_change']:+.1f}% _(indikasi serap supply)_"
            )

    if markup:
        L.append("- Kandidat markup:")
        for d in markup[:3]:
            L.append(
                f"  - `{d['ticker']}` → naik {d['pct_change']:+.1f}% "
                f"dengan value {d['tx_value_bn']:.1f}B _(big move confirmed)_"
            )

    if distribusi:
        L.append("- Kandidat distribusi:")
        for d in distribusi[:3]:
            L.append(
                f"  - `{d['ticker']}` → turun {d['pct_change']:+.1f}% "
                f"dengan value {d['tx_value_bn']:.1f}B _(waspadai tekanan jual)_"
            )

    # Extra pattern intelligence
    if len(akumulasi) >= 3:
        L.append("- ⚠️ _Banyak saham value besar tapi naik kecil → kemungkinan akumulasi luas_")
    if broad_positive and avg_pct > 0:
        L.append("- 📈 _Mayoritas saham hijau → indikasi risk-on market_")
    if high_risk:
        tickers_str = ", ".join(f"`{d['ticker']}`" for d in high_risk[:3])
        L.append(f"- 🚨 _Top gainers terlalu tinggi ({tickers_str}) → potensi trap, jangan kejar_")

    L += ["", "---", ""]
    L.append("🔄 *Market Behavior*")
    risk_on_tag = "  _(risk-on)_" if broad_positive and avg_pct > 0 else ""
    L.append(f"- Kondisi: *{market_label}*{risk_on_tag}")
    if len(top_sectors) >= 2:
        rotation = f"{top_sectors[0][0]} → {top_sectors[1][0]}"
    else:
        rotation = "belum terlihat jelas"
    L.append(f"- Rotasi sektor: {rotation}")

    L += ["", "---", ""]
    L.append("⚠️ *Risk Level*")
    L.append(f"- *{risk_level}*")
    L.append(f"- {risk_reason}")

    L += ["", "---", ""]
    L.append("🎯 *Action Plan*")
    focus = [d["ticker"] for d in akumulasi[:2]] + [
        d["ticker"] for d in markup if d["pct_change"] < 8
    ][:1]
    L.append("- Fokus: " + (", ".join(f"`{t}`" for t in focus[:4]) if focus else "-"))

    strategy = "Buy on pullback, jangan kejar harga hijau"
    if not vol_confirmed:
        strategy += " — tunggu konfirmasi volume dulu"
    L.append(f"- Strategi: {strategy}")

    avoid = [d["ticker"] for d in high_risk[:3]] + [d["ticker"] for d in distribusi[:2]]
    L.append("- Hindari: " + (", ".join(f"`{t}`" for t in avoid[:5]) if avoid else "Belum ada yang perlu dihindari"))

    return "\n".join(L)

def load_logs() -> dict:
    if LOG_PATH.exists():
        try:
            with open(LOG_PATH, "r") as f:
                return json.load(f)
        except:
            return {}
    return {}


def save_today_log(all_data: list[dict]):
    logs = load_logs()
    today = datetime.now().strftime("%Y-%m-%d")

    # simpan hanya field penting
    logs[today] = [
        {
            "ticker": d["ticker"],
            "tx_value_bn": d["tx_value_bn"],
            "pct_change": d["pct_change"],
            "vol_ratio": d["vol_ratio"],
        }
        for d in all_data
    ]

    with open(LOG_PATH, "w") as f:
        json.dump(logs, f, indent=2)


def get_prev_day_data() -> Optional[list[dict]]:
    logs = load_logs()
    dates = sorted(logs.keys())
    if len(dates) < 2:
        return None
    return logs[dates[-2]]

def generate_day_comparison(all_data: list[dict]) -> str:
    prev_data = get_prev_day_data()
    if not prev_data:
        return ""

    prev_map = {d["ticker"]: d for d in prev_data}

    lines = ["", "---", "", "📊 *DAY-TO-DAY COMPARISON*"]

    insights = []

    for d in all_data:
        ticker = d["ticker"]
        prev = prev_map.get(ticker)

        if not prev:
            continue

        # Value naik signifikan
        if d["tx_value_bn"] > prev["tx_value_bn"] * 1.2:
            insights.append(
                f"🔼 `{ticker}` → Value naik signifikan "
                f"({prev['tx_value_bn']:.0f}B → {d['tx_value_bn']:.0f}B)"
            )

        # Flat → naik (markup start)
        if abs(prev["pct_change"]) < 1 and d["pct_change"] > 3:
            insights.append(
                f"🚀 `{ticker}` → Mulai markup ({prev['pct_change']:+.1f}% → {d['pct_change']:+.1f}%)"
            )

        # Naik → turun (distribusi)
        if prev["pct_change"] > 3 and d["pct_change"] < 0:
            insights.append(
                f"⚠️ `{ticker}` → Potensi distribusi ({prev['pct_change']:+.1f}% → {d['pct_change']:+.1f}%)"
            )

        # Volume meningkat
        if d["vol_ratio"] > prev["vol_ratio"] * 1.5:
            insights.append(
                f"📈 `{ticker}` → Aktivitas volume meningkat "
                f"(Vol×{prev['vol_ratio']:.1f} → Vol×{d['vol_ratio']:.1f})"
            )

    if not insights:
        lines.append("_Tidak ada perubahan signifikan dibanding hari sebelumnya._")
    else:
        for i in insights[:10]:
            lines.append(f"  {i}")

    return "\n".join(lines)


def build_report() -> str:
    """Assemble the full screening report."""
    today_str = datetime.now().strftime("%d %b %Y %H:%M WIB")
    lines = [f"📊 *IDX Daily Screener — {today_str}*\n"]

    # ── 1. FETCH ALL TICKERS CONCURRENTLY (yfinance — always reliable) ────────
    print(f"[INFO] Fetching {len(IDX_TICKERS)} tickers concurrently...")
    all_data = fetch_all_tickers()
    all_data_sorted_val = sorted(all_data, key=lambda x: x["tx_value_bn"], reverse=True)

    # ── 2. TOP TRANSACTION VALUE (from yfinance) ──────────────────────────────
    lines.append("💰 *TOP 10 NILAI TRANSAKSI (IDR Miliar)*")
    for d in all_data_sorted_val[:10]:
        arrow = "🔺" if d["pct_change"] >= 0 else "🔻"
        lines.append(
            f"  {arrow} `{d['ticker']:<6}` {d['tx_value_bn']:.1f}B"
            f"  |  {d['pct_change']:+.1f}%"
        )
    lines.append("")

    # ── 3. FOREIGN FLOW from IDX (best-effort) ───────────────────────────────
    df_idx = fetch_idx_foreign_flow()

    if not df_idx.empty and "net_foreign_bn" in df_idx.columns:
        top_foreign = (
            df_idx[["ticker", "net_foreign_bn", "tx_value_bn"]]
            .sort_values("net_foreign_bn", ascending=False)
            .head(10)
        )
        bot_foreign = (
            df_idx[["ticker", "net_foreign_bn", "tx_value_bn"]]
            .sort_values("net_foreign_bn", ascending=True)
            .head(5)
        )

        lines.append("🟢 *TOP 10 NET FOREIGN BUY (IDR Miliar)*")
        for _, r in top_foreign.iterrows():
            sign = "+" if r["net_foreign_bn"] >= 0 else ""
            lines.append(
                f"  `{r['ticker']:<6}` Net {sign}{r['net_foreign_bn']:.1f}B"
                f"  |  Val {r.get('tx_value_bn', 0):.1f}B"
            )

        lines.append("\n🔴 *TOP 5 NET FOREIGN SELL*")
        for _, r in bot_foreign.iterrows():
            lines.append(
                f"  `{r['ticker']:<6}` Net {r['net_foreign_bn']:.1f}B"
                f"  |  Val {r.get('tx_value_bn', 0):.1f}B"
            )
        lines.append("")


    lines.append("⚡ *UNUSUAL VOLUME (Vol > 3× rata-rata 10 hari)*")
    unusual = [d for d in all_data if d["vol_ratio"] >= 3.0]

    if unusual:
        unusual.sort(key=lambda x: x["vol_ratio"], reverse=True)
        for d in unusual[:15]:
            arrow = "🔺" if d["pct_change"] >= 0 else "🔻"
            lines.append(
                f"  {arrow} `{d['ticker']:<6}` "
                f"{d['pct_change']:+.1f}%  "
                f"Vol×{d['vol_ratio']:.1f}  "
                f"Val {d['tx_value_bn']:.1f}B"
            )
    else:
        lines.append("  _Tidak ada unusual volume hari ini._")
    lines.append("")

    # ── 5. TOP GAINERS & LOSERS ───────────────────────────────────────────────
    if all_data:
        sorted_by_pct = sorted(all_data, key=lambda x: x["pct_change"], reverse=True)

        lines.append("🔺 *TOP 5 GAINERS*")
        for d in sorted_by_pct[:5]:
            lines.append(
                f"  `{d['ticker']:<6}` {d['pct_change']:+.2f}%"
                f"  |  Close {d['close']:,.0f}"
                f"  |  Val {d['tx_value_bn']:.1f}B"
            )
        lines.append("")

        lines.append("🔻 *TOP 5 LOSERS*")
        for d in sorted_by_pct[-5:][::-1]:
            lines.append(
                f"  `{d['ticker']:<6}` {d['pct_change']:+.2f}%"
                f"  |  Close {d['close']:,.0f}"
                f"  |  Val {d['tx_value_bn']:.1f}B"
            )
        lines.append("")

    lines.append(
        "📌 _Data: Yahoo Finance (+ IDX jika tersedia). "
        "Bukan rekomendasi beli/jual. DYOR._"
    )

    # ── Big Player Insight analysis (appended below raw data) ─────────────────
    lines.append(generate_big_player_insight(all_data, unusual))
    lines.append(generate_day_comparison(all_data))

    return "\n".join(lines)


def send_telegram(message: str):
    """Send message to Telegram. Splits if over 4096 chars."""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    # Telegram message limit is 4096 chars
    chunks = [message[i:i+4096] for i in range(0, len(message), 4096)]
    for chunk in chunks:
        payload = {
            "chat_id":                  TELEGRAM_CHAT_ID,
            "text":                     chunk,
            "parse_mode":               "Markdown",
            "disable_web_page_preview": True,
        }
        resp = requests.post(url, json=payload, timeout=15)
        resp.raise_for_status()
    print(f"[OK] Telegram sent — {len(chunks)} message(s)")


def run():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Building report...")
    report = build_report()
    print(report)

    print("\n[INFO] Saving daily log...")
    all_data = fetch_all_tickers()
    save_today_log(all_data)

    print("\n[INFO] Sending to Telegram...")
    send_telegram(report)


if __name__ == "__main__":
    run()