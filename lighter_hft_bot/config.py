"""
Configuration module for Lighter.xyz Institutional HFT Bot.
Loads environment variables automatically from `.env` file via `python-dotenv`.
Supports Dynamic Liquidity Scanning and Multi-Asset Market Making across top active markets.
"""
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Tuple

try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
    else:
        load_dotenv()
except ImportError:
    for path_str in [Path(__file__).parent / ".env", Path(".env")]:
        if path_str.exists():
            with open(path_str, "r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ.setdefault(key.strip(), val.strip())
            break

def parse_active_markets() -> List[Tuple[int, str, str]]:
    auto_scan = os.getenv("AUTO_SCAN_MARKETS", "True").lower() == "true"
    base_url = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")
    max_scan = int(os.getenv("MAX_SCAN_MARKETS", "3"))
    
    if auto_scan:
        from liquidity_scanner import LiquidityScanner
        scanner = LiquidityScanner(base_url)
        return scanner.scan_top_markets(max_markets=max_scan)
        
    raw = os.getenv("ACTIVE_MARKETS", "0:ETH-PERP:ethusdt").strip("\"'")
    markets = []
    for item in raw.split(","):
        parts = [p.strip().strip("\"'") for p in item.split(":")]
        if len(parts) == 3:
            markets.append((int(parts[0]), parts[1], parts[2]))
        elif len(parts) == 2:
            markets.append((int(parts[0]), parts[1], parts[1].lower().replace("-perp", "usdt")))
    if not markets:
        markets = [(0, "ETH-PERP", "ethusdt")]
    return markets

@dataclass
class BotConfig:
    MODE: str = os.getenv("BOT_MODE", "dry_run")
    
    # Network & Auth
    BASE_URL: str = os.getenv("LIGHTER_BASE_URL", "https://mainnet.zklighter.elliot.ai")
    WS_URL: str = os.getenv("LIGHTER_WS_URL", "wss://mainnet.zklighter.elliot.ai/stream")
    L1_ADDRESS: str = os.getenv("LIGHTER_L1_ADDRESS", "0x0000000000000000000000000000000000000000")
    ACCOUNT_INDEX: int = int(os.getenv("LIGHTER_ACCOUNT_INDEX", "0"))
    API_KEY_INDEX: int = int(os.getenv("LIGHTER_API_KEY_INDEX", "2"))
    PRIVATE_KEY: str = os.getenv("LIGHTER_PRIVATE_KEY", "0x" + "0"*64)
    
    # Active Markets (List of (market_index, symbol, binance_symbol))
    MARKETS: List[Tuple[int, str, str]] = field(default_factory=parse_active_markets)
    MARKET_INDEX: int = int(os.getenv("LIGHTER_MARKET_INDEX", "0"))
    SYMBOL: str = os.getenv("SYMBOL", "ETH-PERP")
    BINANCE_SYMBOL: str = os.getenv("BINANCE_SYMBOL", "ethusdt")
    
    # Account Profile
    IS_PREMIUM_ACCOUNT: bool = os.getenv("IS_PREMIUM_ACCOUNT", "True").lower() == "true"
    SIMULATED_LATENCY_MS: int = 0 if IS_PREMIUM_ACCOUNT else 200
    
    # Capital & Sizing ($1,000 | $20 margin * 5x leverage = $100 notional | 10 trades max per market)
    INITIAL_CAPITAL_USD: float = float(os.getenv("INITIAL_CAPITAL_USD", "1000.0"))
    TRADE_MARGIN_USD: float = float(os.getenv("TRADE_MARGIN_USD", "20.0"))
    LEVERAGE: float = float(os.getenv("LEVERAGE", "5.0"))
    TRADE_NOTIONAL_USD: float = TRADE_MARGIN_USD * LEVERAGE
    MAX_CONCURRENT_TRADES: int = int(os.getenv("MAX_CONCURRENT_TRADES", "10"))
    MAX_POSITION_USD: float = TRADE_NOTIONAL_USD * MAX_CONCURRENT_TRADES
    
    BASE_ORDER_SIZE: float = round(TRADE_NOTIONAL_USD / 3000.0, 4)
    MAX_POSITION_SIZE: float = round(MAX_POSITION_USD / 3000.0, 4)
    
    # Strategy Parameters
    RISK_AVERSION_GAMMA: float = float(os.getenv("RISK_AVERSION_GAMMA", "0.10"))
    ORDER_BOOK_DEPTH_K: float = float(os.getenv("ORDER_BOOK_DEPTH_K", "3.5"))
    MIN_SPREAD_BPS: float = float(os.getenv("MIN_SPREAD_BPS", "1.5"))
    MAX_SPREAD_BPS: float = float(os.getenv("MAX_SPREAD_BPS", "12.0"))
    
    # Multi-Level Ladder & Institutional Alpha
    NUM_QUOTE_LEVELS: int = int(os.getenv("NUM_QUOTE_LEVELS", "3"))
    LADDER_STEP_BPS: float = float(os.getenv("LADDER_STEP_BPS", "2.5"))
    ENABLE_TOXIC_GUARD: bool = os.getenv("ENABLE_TOXIC_GUARD", "True").lower() == "true"
    OFI_TOXICITY_THRESHOLD: float = float(os.getenv("OFI_TOXICITY_THRESHOLD", "0.65"))
    ENABLE_EXTERNAL_FEED: bool = os.getenv("ENABLE_EXTERNAL_FEED", "True").lower() == "true"
    LEAD_LAG_THRESHOLD_BPS: float = float(os.getenv("LEAD_LAG_THRESHOLD_BPS", "2.5"))
    
    POST_ONLY: bool = True
    BATCH_CANCEL_REQUOTE: bool = True
    REPORT_FILE_DRY_RUN: str = "dry_run_diagnostics.json"
    REPORT_FILE_BACKTEST: str = "backtest_report.json"
    BACKTEST_SEED: int = int(os.getenv("BACKTEST_SEED", "42"))  # Deterministic seed for reproducible backtests
    PRICE_DECIMALS: int = int(os.getenv("PRICE_DECIMALS", "2")) # Default 2 decimals ($0.01)
    SIZE_DECIMALS: int = int(os.getenv("SIZE_DECIMALS", "4"))   # Default 4 decimals (0.0001 ETH)

config = BotConfig()
