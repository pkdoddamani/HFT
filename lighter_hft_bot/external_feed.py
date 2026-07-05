"""
External Leading Indicator Alpha Feed for Lighter.xyz HFT Bot.
Connects to centralized high-liquidity exchanges (Binance Futures WebSocket) to monitor
fast directional momentum before it reflects on Lighter's order book.
Calculates Lead-Lag Price Delta (Delta_Binance - Lighter) to front-run adverse price jumps.
"""
import asyncio
import json
import logging
import time
import random
from typing import Optional

logger = logging.getLogger("ExternalLeadLagFeed")

class ExternalLeadLagFeed:
    def __init__(self, config):
        self.config = config
        self.binance_ws_url = f"wss://fstream.binance.com/ws/{config.BINANCE_SYMBOL.lower()}@bookTicker"
        self.binance_mid_price: float = 0.0
        self.lead_lag_delta_bps: float = 0.0
        self.last_update_ts: float = 0.0
        self.is_running = True

    async def start(self):
        if not self.config.ENABLE_EXTERNAL_FEED:
            logger.info("External Lead-Lag feed disabled in config.")
            return
            
        self.is_running = True
        logger.info(f"Connecting to Binance Leading Indicator feed at {self.binance_ws_url}...")
        
        try:
            import websockets
            async with websockets.connect(self.binance_ws_url, ping_interval=30) as ws:
                async for raw_msg in ws:
                    if not self.is_running:
                        break
                    msg = json.loads(raw_msg)
                    bid = float(msg.get("b", 0))
                    ask = float(msg.get("a", 0))
                    if bid > 0 and ask > 0:
                        self.binance_mid_price = (bid + ask) / 2.0
                        self.last_update_ts = time.time()
        except Exception as e:
            from config import config
            if config.MODE.lower() == "live":
                logger.error(f"Binance external WebSocket feed unavailable ({e}). Disabling external lead-lag alpha for safety.")
                self.is_running = False
            else:
                logger.warning(f"Binance external WebSocket unavailable ({e}). Running synthetic lead-lag simulator...")
                await self._run_synthetic_lead_feed()

    async def _run_synthetic_lead_feed(self):
        """Simulates external leading indicator fluctuations relative to local Lighter price."""
        while self.is_running:
            await asyncio.sleep(0.2)
            # Simulated lead-lag micro jumps between -4.0 bps and +4.0 bps
            self.lead_lag_delta_bps = round(random.gauss(0, 1.2), 2)
            self.last_update_ts = time.time()

    def update_against_lighter_mid(self, lighter_mid: float) -> float:
        """
        Computes price lead delta in basis points: ((BinanceMid - LighterMid) / LighterMid) * 10000.
        Positive delta means Binance jumped higher (Lighter about to jump UP).
        Negative delta means Binance crashed lower (Lighter about to crash DOWN).
        """
        if not self.config.ENABLE_EXTERNAL_FEED:
            return 0.0
            
        if self.binance_mid_price > 0 and lighter_mid > 0:
            self.lead_lag_delta_bps = round(((self.binance_mid_price - lighter_mid) / lighter_mid) * 10000.0, 2)
            
        return self.lead_lag_delta_bps

    def should_pull_bid(self) -> bool:
        """If external price crashed lower by > 2.5 bps, pull our BID immediately before getting dumped on."""
        return self.lead_lag_delta_bps <= -self.config.LEAD_LAG_THRESHOLD_BPS

    def should_pull_ask(self) -> bool:
        """If external price spiked higher by > 2.5 bps, pull our ASK immediately before getting pumped on."""
        return self.lead_lag_delta_bps >= self.config.LEAD_LAG_THRESHOLD_BPS

    def get_state(self) -> dict:
        return {
            "binance_mid_price": self.binance_mid_price,
            "lead_lag_delta_bps": self.lead_lag_delta_bps,
            "should_pull_bid": self.should_pull_bid(),
            "should_pull_ask": self.should_pull_ask()
        }
