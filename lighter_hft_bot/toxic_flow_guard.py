"""
Toxic Flow Guard & Adverse Selection Shield for Lighter.xyz HFT Bot.
Monitors Order Flow Imbalance Velocity (OFI) and Volume-Synchronized Toxicity.
When informed taker flow (whales dumping/pumping) hits the order book, the guard triggers
asymmetric spread widening or quote withdrawal to prevent getting adversely selected.
"""
import time
import logging
from typing import List, Tuple

logger = logging.getLogger("ToxicFlowGuard")

class ToxicFlowGuard:
    def __init__(self, config):
        self.config = config
        self.trade_window_sec = 5.0  # Rolling 5-second window for toxicity evaluation
        self.recent_volume_buy = 0.0
        self.recent_volume_sell = 0.0
        self._flow_history: List[Tuple[float, str, float]] = [] # (timestamp, side, size)
        self.toxicity_score = 0.0       # Range 0.0 (balanced) to 1.0 (extremely toxic one-sided flow)
        self.toxic_side = "NONE"        # 'BUY_TOXIC' (heavy buying pressure) or 'SELL_TOXIC'

    def record_market_trade(self, side: str, size: float):
        """Records incoming taker trades (BUY or SELL) and recomputes OFI toxicity."""
        now = time.time()
        self._flow_history.append((now, side, size))
        self._prune_old_flow(now)
        self._recompute_toxicity()

    def _prune_old_flow(self, now: float):
        cutoff = now - self.trade_window_sec
        while self._flow_history and self._flow_history[0][0] < cutoff:
            self._flow_history.pop(0)

    def _recompute_toxicity(self):
        buy_vol = sum(size for t, side, size in self._flow_history if side == "BUY")
        sell_vol = sum(size for t, side, size in self._flow_history if side == "SELL")
        total_vol = buy_vol + sell_vol
        
        self.recent_volume_buy = buy_vol
        self.recent_volume_sell = sell_vol
        
        if total_vol < 0.05:  # Low volume silence
            self.toxicity_score = 0.0
            self.toxic_side = "NONE"
            return
            
        imbalance = (buy_vol - sell_vol) / total_vol
        self.toxicity_score = round(abs(imbalance), 3)
        
        if self.toxicity_score >= self.config.OFI_TOXICITY_THRESHOLD:
            if imbalance > 0:
                self.toxic_side = "BUY_TOXIC"   # Whales aggressively buying (danger to our ASK quotes)
            else:
                self.toxic_side = "SELL_TOXIC"  # Whales aggressively selling (danger to our BID quotes)
        else:
            self.toxic_side = "NONE"

    def get_defense_multiplier(self, is_ask_quote: bool) -> float:
        """
        Returns spread multiplier based on toxicity score.
        If whales are aggressively buying ('BUY_TOXIC'), our ASK quote is in danger of being run over:
        we multiply ASK spread by 2.5x or pull it entirely.
        """
        if not self.config.ENABLE_TOXIC_GUARD or self.toxic_side == "NONE":
            return 1.0
            
        if self.toxic_side == "BUY_TOXIC" and is_ask_quote:
            return 2.5 + (self.toxicity_score * 2.0)  # Widen ask spread sharply or pull
        elif self.toxic_side == "SELL_TOXIC" and not is_ask_quote:
            return 2.5 + (self.toxicity_score * 2.0)  # Widen bid spread sharply or pull
            
        return 1.0

    def get_state(self) -> dict:
        return {
            "toxicity_score": self.toxicity_score,
            "toxic_side": self.toxic_side,
            "recent_volume_buy": self.recent_volume_buy,
            "recent_volume_sell": self.recent_volume_sell,
            "is_active": self.toxicity_score >= self.config.OFI_TOXICITY_THRESHOLD
        }
