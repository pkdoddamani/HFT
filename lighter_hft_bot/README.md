# Lighter.xyz Institutional High-Frequency Trading (HFT) & Market Making Bot

A production-ready, asynchronous Python framework for High-Frequency Trading (HFT) and Avellaneda-Stoikov Market Making on [Lighter.xyz](https://lighter.xyz/). Equipped with an **Institutional Alpha Engine**, **Multi-Level Quoting Ladder**, **Toxic Flow Guard**, **Live PowerShell Terminal Dashboard**, **Dry Run Diagnostics**, and a **High-Frequency Backtester**. Controlled via a convenient **`.env`** file!

---

## Executive Summary: HFT Feasibility on Lighter.xyz

**Can we build an accurate HFT bot on Lighter.xyz?**
**Yes!** Lighter is uniquely designed to support high-frequency and automated quantitative trading because of two massive structural advantages:
1. **Zero Fees on Standard Accounts**: Lighter charges **0% maker and 0% taker fees** by default. This eliminates the #1 friction point for HFT strategies (such as order book scalping and market making), where traditional exchanges consume edge through basis point trading fees.
2. **Zero Engine Latency for Premium Makers**: While Standard accounts trade for free, Lighter applies an artificial matching engine throttle (`300ms` taker latency, `200ms` maker/cancel latency). However, by opting into a **Premium Account** and staking LIT tokens, **Post-Only maker order placements and cancellations have 0ms added latency**.

---

## 🏆 Institutional HFT Upgrades (Deep Research Features)

To ensure this bot operates at institutional grade, we researched and engineered three advanced quantitative modules into the framework:

### 1. Multi-Level Post-Only Quoting Ladder (`NUM_QUOTE_LEVELS=3`)
Instead of placing just one limit order at the touch, the strategy manages a **3-level order book ladder** (`Level 1` at optimal half-spread $\delta$, `Level 2` at $\delta + 3.5$ bps, `Level 3` at $\delta + 7.0$ bps). Each level maintains exact `$100 notional` sizing (`$20 margin x 5x leverage`). This captures tight scalping flow at the touch while harvesting wider spreads during sudden volatility spikes.

### 2. Toxic Flow Guard & Adverse Selection Shield (`toxic_flow_guard.py`)
In HFT, adverse selection (getting filled by informed whale order flow right before a directional breakout) destroys maker edge. The **Toxic Flow Guard** monitors real-time taker volume velocity to compute **Order Flow Imbalance (OFI)**. When toxicity exceeds threshold (`OFI > 0.65`), the bot immediately widens spreads by $2.5\times+$ or pulls quotes on the toxic side.

### 3. External Leading Indicator Alpha Feed (`external_feed.py`)
Decentralized exchanges often lag global price discovery on centralized giants like Binance Futures (`ethusdt`) by tens of milliseconds. Our bot maintains a concurrent WebSocket stream to Binance Futures (`wss://fstream.binance.com/ws/ethusdt@bookTicker`) to calculate the real-time **Lead-Lag Price Delta**. If Binance jumps by $>2.5$ bps before Lighter reflects the move, the bot cancels stale local quotes *before* latency arbitrageurs can hit them!

---

## ⚙️ Configured Capital, Sizing & Leverage Rules (`.env`)

All parameters are controlled directly from **`lighter_hft_bot/.env`** (or root `.env`):
* **Starting Account Balance**: `$1,000.00 USD` (`INITIAL_CAPITAL_USD=1000.0`)
* **Margin Per Trade**: `$20.00 USD` (`TRADE_MARGIN_USD=20.0`)
* **Leverage**: `5x` (`LEVERAGE=5.0`)
* **Notional Order Size**: `$100.00 USD` per Post-Only quote (`~0.0334 ETH`).
* **Maximum Concurrent Trades**: `10 trades at a time` (`$1,000.00 USD` maximum exposure ceiling / `~0.3333 ETH`).

---

## 📁 Repository Structure

```text
lighter_hft_bot/
├── README.md            # Architecture, setup, and mathematical strategy guide
├── .env                 # Centralized configuration file (modes, sizing, leverage, credentials)
├── config.py            # Config loader reading directly from .env
├── ws_feed.py           # Asynchronous WebSocket client (BBO ticker & 50ms order book diffs)
├── executor.py          # Cryptographic signing, local nonce management, and live execution
├── toxic_flow_guard.py  # OFI velocity clamping & adverse selection defense shield
├── external_feed.py     # Binance WebSocket fast feed for lead-lag alpha front-running
├── dry_run.py           # Paper trading virtual engine simulating realistic queue fills & latency
├── backtester.py        # Micro-tick high-frequency backtest replay & institutional report generator
├── strategy_mm.py       # Avellaneda-Stoikov multi-level ladder & microprice model
├── dashboard.py         # Rich live PowerShell dashboard rendering UI tables & internal states
└── main.py              # Unified entrypoint orchestrator
```

---

## 🚀 How to Run the Bot (Windows PowerShell)

### Step 1: Install Dependencies (Once)
```powershell
pip install rich websockets asyncio python-dotenv
```

### Step 2: Open `.env` and Select Your Mode
Inside `lighter_hft_bot/.env` (or root `.env`), set `BOT_MODE`:
```properties
# Options: 'dry_run' (paper trading), 'backtest' (simulation), 'live' (real money)
BOT_MODE=dry_run
USE_DASHBOARD=True
```

### Step 3: Run the Bot
```powershell
python lighter_hft_bot/main.py
```

When you press **`Ctrl + C`**, the bot exports your course-correction diagnostics to **`dry_run_diagnostics.json`** and **`dry_run_report.html`**.
