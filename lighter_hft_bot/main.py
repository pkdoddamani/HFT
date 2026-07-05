# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "rich",
#     "websockets",
#     "python-dotenv",
# ]
# ///
"""
Main Entrypoint for Lighter.xyz Institutional High-Frequency Trading Bot.
Orchestrates Multi-Asset Market Making across multiple concurrent markets (ETH, BTC, SOL).
Includes Institutional HFT modules: Toxic Flow Guard, External Lead-Lag Feed, and Multi-Level Quoting.
Supports `uv run python main.py` directly with PEP 723 inline dependencies.
"""
import asyncio
import logging
import sys
import os
import json

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import config
from executor import LighterExecutor
from dry_run import DryRunExecutor
from backtester import HighFrequencyBacktester
from ws_feed import LighterWsFeed
from strategy_mm import AvellanedaStoikovMM
from toxic_flow_guard import ToxicFlowGuard
from external_feed import ExternalLeadLagFeed
from risk_manager import RiskManager
from dashboard import LiveTerminalDashboard
from rich.live import Live

USE_DASHBOARD = os.getenv("USE_DASHBOARD", "True").lower() == "true" and config.MODE.lower() != "backtest"

logging.basicConfig(
    level=logging.WARNING if USE_DASHBOARD else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Main")

async def setup_market_instance(market_idx: int, symbol: str, binance_sym: str):
    toxic_guard = ToxicFlowGuard(config)
    external_feed = ExternalLeadLagFeed(config)
    risk_manager = RiskManager(config)
    external_feed.binance_ws_url = f"wss://fstream.binance.com/ws/{binance_sym.lower()}@bookTicker"
    
    if config.MODE == "dry_run":
        executor = DryRunExecutor(config, toxic_guard=toxic_guard, symbol=symbol)
    else:
        executor = LighterExecutor(config)
        
    await executor.initialize()
    strategy = AvellanedaStoikovMM(config, executor, toxic_guard=toxic_guard, external_feed=external_feed, risk_manager=risk_manager)
    executor.on_fill_callback = strategy.on_fill
    
    async def on_bbo(best_bid: float, best_ask: float, bid_size: float, ask_size: float):
        if config.MODE == "dry_run":
            await executor.on_bbo_tick(best_bid, best_ask)
        await strategy.on_market_update(best_bid, best_ask, bid_size, ask_size)
        
    ws_feed = LighterWsFeed(
        ws_url=config.WS_URL,
        market_index=market_idx,
        symbol=symbol,
        on_bbo_update=on_bbo,
        on_book_update=strategy.on_book_update
    )
    
    ws_feed.is_running = True
    external_feed.is_running = True
    
    return {
        "symbol": symbol,
        "executor": executor,
        "strategy": strategy,
        "toxic_guard": toxic_guard,
        "external_feed": external_feed,
        "risk_manager": risk_manager,
        "ws_feed": ws_feed
    }

async def run_live_or_dry_run():
    markets_data = []
    for market_idx, symbol, binance_sym in config.MARKETS:
        inst = await setup_market_instance(market_idx, symbol, binance_sym)
        markets_data.append(inst)
        
    dashboard = LiveTerminalDashboard(config) if USE_DASHBOARD else None
    
    tasks = []
    for inst in markets_data:
        tasks.append(asyncio.create_task(inst["ws_feed"].start()))
        tasks.append(asyncio.create_task(inst["external_feed"].start()))
        
    try:
        if USE_DASHBOARD:
            with Live(dashboard.generate_layout(markets_data), refresh_per_second=2, screen=False) as live:
                while any(inst["ws_feed"].is_running for inst in markets_data):
                    await asyncio.sleep(0.5)
                    live.update(dashboard.generate_layout(markets_data))
        else:
            await asyncio.gather(*tasks)
    except KeyboardInterrupt:
        for inst in markets_data:
            inst["ws_feed"].is_running = False
            inst["external_feed"].is_running = False
        await asyncio.sleep(0.5)
    finally:
        for inst in markets_data:
            inst["ws_feed"].is_running = False
            inst["external_feed"].is_running = False
            if config.MODE == "dry_run":
                summary = inst["executor"].export_summary()
                if not USE_DASHBOARD:
                    print(f"\nFINAL SUMMARY FOR {inst['symbol']}:\n{json.dumps(summary, indent=2)}")

def run_backtest():
    logger.info("==========================================================")
    logger.info("Starting Lighter.xyz HFT Backtesting Framework")
    logger.info("==========================================================")
    backtester = HighFrequencyBacktester(config)
    report = backtester.run_backtest()
    print(json.dumps(report, indent=2))
    print("HTML Report generated at: backtest_report.html")

if __name__ == "__main__":
    if config.MODE.lower() == "backtest":
        run_backtest()
    else:
        try:
            asyncio.run(run_live_or_dry_run())
        except KeyboardInterrupt:
            pass
