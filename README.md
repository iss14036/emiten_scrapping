# 📊 emiten-scrapper

Daily IDX stock screener that sends a formatted report to **Telegram**, covering:
- 🟢 Top 10 Net Foreign Buy
- 🔴 Top 5 Net Foreign Sell
- 💰 Top 10 Nilai Transaksi
- ⚡ Unusual Volume (>3× 10-day average)
- 🔺🔻 Top Gainers & Losers

---

## Requirements

- Python 3.9+
- A [Telegram Bot](https://core.telegram.org/bots#creating-a-new-bot) token and chat ID

---

## Setup

```bash
# 1. Clone & enter the project
git clone <your-repo-url>
cd emiten-scrapper

# 2. Create virtualenv
python3 -m venv venv
source venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
cp .env.example .env
# Edit .env with your TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
```

---

## Usage

### Run Once
```bash
python main.py
```
### Run on Schedule (GitHub Actions)
The project includes a `.github/workflows/screener.yml` that runs automatically **every weekday at 16:30 WIB**.

To enable this:
1. Go to your GitHub repository **Settings → Secrets and variables → Actions**
2. Add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` as repository secrets.

---

## Project Structure

```
emiten-scrapper/
├── .github/
│   └── workflows/
│       └── screener.yml # GitHub Actions daily runner
├── main.py          # Core screener logic
├── requirements.txt # Python dependencies
├── .env.example     # Environment variable template
├── .env             # Your secrets (git-ignored)
└── .gitignore
```

---

## Disclaimer
Data sourced from IDX and Yahoo Finance. **Not financial advice. DYOR.**
