"""
Avellaneda-Stoikov Institutional High-Frequency Market Making Strategy for Lighter.xyz.
Uses unified `strategy_core.py` math functions, dynamic volatility estimation,
and integrates `RiskManager` for strict drawdown kill switches and position ceilings.
"""
import math
import logging
from typing import Dict, Any, List
from strategy_core import compute_microprice, compute_reservation_price, compute_optimal_half_spread_bps, compute_ladder_quotes

logger = logging.getLogger("AvellanedaStoikovMM")

class AvellanedaStoikovMM:
    def __init__(self, config, executor, toxic_guard=None, external_feed=None, risk_manager=None):
        self.config = config
        self.executor = executor
        self.toxic_guard = toxic_guard
        self.external_feed = external_feed
        self.risk_manager = risk_manager
        
        # Market & Inventory State
        self.current_inventory: float = 0.0     # Current net position size (+ Long, - Short)
        self.mid_price: float = 0.0
        self.micro_price: float = 0.0
        self.reservation_price: float = 0.0
        self.volatility: float = 0.0003         # Dynamic return volatility (sigma)
        self.optimal_half_spread_bps: float = 2.0
        
        # Rolling price window for dynamic volatility estimation
        self._price_history: List[float] = []
        
        # Active Quote Ladder
        self.active_bids: List[Dict[str, Any]] = []
        self.active_asks: List[Dict[str, Any]] = []

    def on_fill(self, side: str, size: float, price: float):
        """Callback invoked by executor whenever an order fills."""
        if side == "BID":
            self.current_inventory += size
        elif side == "ASK":
            self.current_inventory -= size
        logger.info(f"Strategy inventory updated via fill callback: {self.current_inventory:.4f} ETH/Tokens")

    def _update_dynamic_volatility(self, mid: float):
        self._price_history.append(mid)
        if len(self._price_history) > 40:
            self._price_history.pop(0)
        if len(self._price_history) >= 10:
            returns = [
                (self._price_history[i] - self._price_history[i-1]) / self._price_history[i-1]
                for i in range(1, len(self._price_history))
            ]
            mean_r = sum(returns) / len(returns)
            var = sum((r - mean_r) ** 2 for r in returns) / len(returns)
            self.volatility = max(0.0001, var ** 0.5)

    async def on_market_update(self, best_bid: float, best_ask: float, bid_size: float, ask_size: float):
        if best_bid <= 0 or best_ask <= 0:
            return
            
        self.mid_price = (best_bid + best_ask) / 2.0
        self._update_dynamic_volatility(self.mid_price)
        self.micro_price = compute_microprice(best_bid, best_ask, bid_size, ask_size)
        
        # Evaluate Volatility Circuit Breaker
        if self.risk_manager:
            self.risk_manager.evaluate_volatility(self.volatility)
            
        # Check External Lead-Lag Feed
        pull_bids_lead = False
        pull_asks_lead = False
        if self.external_feed:
            self.external_feed.update_against_lighter_mid(self.mid_price)
            pull_bids_lead = self.external_feed.should_pull_bid()
            pull_asks_lead = self.external_feed.should_pull_ask()
            
        self.reservation_price = compute_reservation_price(
            self.micro_price, self.current_inventory, self.config.RISK_AVERSION_GAMMA, self.volatility
        )
        self.optimal_half_spread_bps = compute_optimal_half_spread_bps(
            self.config.RISK_AVERSION_GAMMA, self.config.ORDER_BOOK_DEPTH_K,
            self.volatility, self.config.MIN_SPREAD_BPS, self.config.MAX_SPREAD_BPS, self.mid_price
        )
        
        # Check Toxic Flow Guard
        bid_mult = self.toxic_guard.get_defense_multiplier(is_ask_quote=False) if self.toxic_guard else 1.0
        ask_mult = self.toxic_guard.get_defense_multiplier(is_ask_quote=True) if self.toxic_guard else 1.0
        
        order_size = round(self.config.TRADE_NOTIONAL_USD / max(self.mid_price, 1.0), 4)
        
        # Pre-quote risk evaluation via RiskManager
        can_bid_rm, _ = self.risk_manager.can_quote(self.current_inventory, self.mid_price, is_ask=False) if self.risk_manager else (True, "OK")
        can_ask_rm, _ = self.risk_manager.can_quote(self.current_inventory, self.mid_price, is_ask=True) if self.risk_manager else (True, "OK")
        
        quote_bid = can_bid_rm and not pull_bids_lead and (bid_mult < 4.0)
        quote_ask = can_ask_rm and not pull_asks_lead and (ask_mult < 4.0)
        
        target_bids, target_asks = compute_ladder_quotes(
            self.reservation_price, self.optimal_half_spread_bps, self.mid_price,
            order_size, self.config.NUM_QUOTE_LEVELS, self.config.LADDER_STEP_BPS,
            best_bid, best_ask, quote_bid, quote_ask, bid_mult, ask_mult
        )
        
        drift_threshold = self.mid_price * 0.0004
        bid_needs_update = len(self.active_bids) != len(target_bids)
        if not bid_needs_update and target_bids:
            for ab, tb in zip(self.active_bids, target_bids):
                if abs(ab["price"] - tb["price"]) > drift_threshold:
                    bid_needs_update = True
                    break
                    
        ask_needs_update = len(self.active_asks) != len(target_asks)
        if not ask_needs_update and target_asks:
            for aa, ta in zip(self.active_asks, target_asks):
                if abs(aa["price"] - ta["price"]) > drift_threshold:
                    ask_needs_update = True
                    break
                    
        if not bid_needs_update and not ask_needs_update:
            return
            
        cancels = []
        new_orders = []
        
        if bid_needs_update:
            for ab in self.active_bids:
                cancels.append(ab["cid"])
            self.active_bids = []
            for tb in target_bids:
                new_orders.append({"price": tb["price"], "size": tb["size"], "is_ask": False, "level": tb["level"]})
                
        if ask_needs_update:
            for aa in self.active_asks:
                cancels.append(aa["cid"])
            self.active_asks = []
            for ta in target_asks:
                new_orders.append({"price": ta["price"], "size": ta["size"], "is_ask": True, "level": ta["level"]})
                
        if cancels or new_orders:
            new_cids = await self.executor.batch_cancel_and_replace(cancels, new_orders)
            idx = 0
            if bid_needs_update:
                for tb in target_bids:
                    if idx < len(new_cids):
                        tb["cid"] = new_cids[idx]
                        self.active_bids.append(tb)
                        idx += 1
            if ask_needs_update:
                for ta in target_asks:
                    if idx < len(new_cids):
                        ta["cid"] = new_cids[idx]
                        self.active_asks.append(ta)
                        idx += 1

    async def on_book_update(self, book: dict):
        """Processes full L2 order book depth to compute deeper volume-weighted microprice."""
        bids = book.get("bids", [])
        asks = book.get("asks", [])
        if bids and asks:
            top_bid_price, top_bid_size = bids[0][0], bids[0][1]
            top_ask_price, top_ask_size = asks[0][0], asks[0][1]
            if top_bid_price > 0 and top_ask_price > 0:
                self.micro_price = compute_microprice(top_bid_price, top_ask_price, top_bid_size, top_ask_size)

    def get_state(self) -> Dict[str, Any]:
        l1_bid = self.active_bids[0]["price"] if self.active_bids else 0.0
        l1_ask = self.active_asks[0]["price"] if self.active_asks else 0.0
        return {
            "mid_price": self.mid_price,
            "micro_price": self.micro_price,
            "reservation_price": self.reservation_price,
            "volatility": self.volatility,
            "optimal_half_spread_bps": self.optimal_half_spread_bps,
            "active_bid_price": l1_bid,
            "active_ask_price": l1_ask,
            "active_bids_count": len(self.active_bids),
            "active_asks_count": len(self.active_asks),
            "inventory": self.current_inventory
        }
