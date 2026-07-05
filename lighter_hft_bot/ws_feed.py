"""
WebSocket Data Feed Handler for Lighter.xyz
Subscribes to real-time BBO ticker and order book diff feeds with mandatory 2-minute keepalive ping.
Automatically connects to live mainnet WebSocket stream or falls back to synthetic flow if network is unavailable.
"""
import asyncio
import json
import logging
import time
import random
from typing import Callable, Dict, Any

logger = logging.getLogger("LighterWsFeed")

class LighterWsFeed:
    def __init__(self, ws_url: str, market_index: int, symbol: str, on_bbo_update: Callable, on_book_update: Callable):
        self.ws_url = ws_url
        self.market_index = market_index
        self.symbol = symbol
        self.on_bbo_update = on_bbo_update
        self.on_book_update = on_book_update
        self.is_running = True
        self._last_frame_sent = time.time()
        
        # Set realistic starting price per symbol
        if "BTC" in symbol.upper():
            start_price = 64500.00
        elif "SOL" in symbol.upper():
            start_price = 145.50
        else:
            start_price = 3000.00
            
        self.best_bid: float = round(start_price - 0.25, 2)
        self.best_ask: float = round(start_price + 0.25, 2)
        self.best_bid_size: float = 1.5
        self.best_ask_size: float = 1.2
        self.order_book: Dict[str, Any] = {"bids": [], "asks": []}
        self.last_nonce: int = -1

    async def start(self):
        """Starts the WebSocket connection and maintain keep-alive loop."""
        self.is_running = True
        logger.info(f"Connecting to Lighter WebSocket at {self.ws_url} for market {self.market_index} ({self.symbol})...")
        
        try:
            import websockets
            # Disable library auto-ping to prevent collision with Lighter custom keepalive loop
            async with websockets.connect(self.ws_url, ping_interval=None) as ws:
                await self.subscribe_channels(ws)
                keepalive_task = asyncio.create_task(self.keep_alive_loop(ws))
                try:
                    async for raw_msg in ws:
                        if not self.is_running:
                            break
                        await self.handle_message(raw_msg)
                finally:
                    keepalive_task.cancel()
        except Exception as e:
            from config import config
            if config.MODE.lower() == "live":
                logger.critical(f"FATAL: Live mainnet WebSocket disconnected ({e}). Halting bot immediately to protect real capital!")
                self.is_running = False
                raise RuntimeError(f"Live WebSocket failure: {e}")
            else:
                logger.warning(f"Live WebSocket connection unavailable ({e}). Running high-frequency simulated live feed for {self.symbol}...")
                await self._run_simulated_feed()

    async def _run_simulated_feed(self):
        """Fallback synthetic feed generator if running offline or without network access."""
        current_mid = (self.best_bid + self.best_ask) / 2.0
        while self.is_running:
            await asyncio.sleep(0.15)  # ~150ms ticks
            jump = current_mid * 0.0003 * random.gauss(0, 1)
            current_mid = max(1.0, current_mid + jump)
            half_spread_bps = random.uniform(0.5, 1.8)
            half_spread = (half_spread_bps / 10000.0) * current_mid
            self.best_bid = round(current_mid - half_spread, 2)
            self.best_ask = round(current_mid + half_spread, 2)
            self.best_bid_size = round(random.expovariate(1.0 / 5.0), 2)
            self.best_ask_size = round(random.expovariate(1.0 / 5.0), 2)
            if self.on_bbo_update:
                await self.on_bbo_update(self.best_bid, self.best_ask, self.best_bid_size, self.best_ask_size)

    async def subscribe_channels(self, ws):
        bbo_sub = {
            "type": "subscribe",
            "channel": f"ticker/{self.market_index}"
        }
        book_sub = {
            "type": "subscribe",
            "channel": f"order_book/{self.market_index}"
        }
        await ws.send(json.dumps(bbo_sub))
        await ws.send(json.dumps(book_sub))
        self._last_frame_sent = time.time()
        logger.info(f"Subscribed to ticker/{self.market_index} and order_book/{self.market_index} ({self.symbol})")

    async def handle_message(self, raw_msg: str):
        try:
            msg = json.loads(raw_msg)
            msg_type = msg.get("type", "")
            
            if msg_type == "update/ticker":
                ticker_data = msg.get("ticker", {})
                self.best_ask = float(ticker_data.get("a", {}).get("price", 0))
                self.best_ask_size = float(ticker_data.get("a", {}).get("size", 0))
                self.best_bid = float(ticker_data.get("b", {}).get("price", 0))
                self.best_bid_size = float(ticker_data.get("b", {}).get("size", 0))
                
                if self.on_bbo_update:
                    await self.on_bbo_update(self.best_bid, self.best_ask, self.best_bid_size, self.best_ask_size)
                    
            elif msg_type == "update/order_book":
                book_data = msg.get("order_book", {})
                begin_nonce = book_data.get("begin_nonce", -1)
                nonce = book_data.get("nonce", -1)
                
                if self.last_nonce != -1 and begin_nonce != self.last_nonce:
                    logger.warning(f"Order book discontinuity on {self.symbol} (last: {self.last_nonce}, begin: {begin_nonce}). Resynchronizing book state...")
                    self.order_book = {"bids": [], "asks": []}
                    self.last_nonce = -1
                    return
                    
                self.last_nonce = nonce
                self.order_book["asks"] = [(float(level["price"]), float(level["size"])) for level in book_data.get("asks", [])]
                self.order_book["bids"] = [(float(level["price"]), float(level["size"])) for level in book_data.get("bids", [])]
                
                if self.on_book_update:
                    await self.on_book_update(self.order_book)
                    
        except Exception as e:
            logger.error(f"Error handling WS message: {e}")

    async def keep_alive_loop(self, ws):
        while self.is_running:
            await asyncio.sleep(60)
            if time.time() - self._last_frame_sent > 60:
                try:
                    await ws.ping()
                    self._last_frame_sent = time.time()
                except Exception as e:
                    logger.error(f"Keep-alive ping failed: {e}")
                    break
