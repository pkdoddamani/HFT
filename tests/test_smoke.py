"""
Smoke Test Suite (`tests/test_smoke.py`).
Verifies unified quantitative math core, config loading, and risk management boundaries.
"""
import os
import sys
import unittest

# Ensure lighter_hft_bot is in path
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "lighter_hft_bot"))

from strategy_core import compute_microprice, compute_reservation_price, compute_optimal_half_spread_bps, compute_ladder_quotes
from config import BotConfig
from risk_manager import RiskManager

class SmokeTestSuite(unittest.TestCase):
    def test_strategy_core_microprice(self):
        """Verify volume-weighted OIB microprice calculation."""
        # When ask size is larger than bid size, microprice tilts lower toward bid
        mp = compute_microprice(100.0, 102.0, bid_size=10.0, ask_size=30.0)
        self.assertAlmostEqual(mp, 100.5)

    def test_reservation_price_skew(self):
        """Verify Avellaneda-Stoikov reservation price skews opposite to inventory."""
        # Long inventory (q=1.0) should shift reservation price below microprice
        res_long = compute_reservation_price(100.0, inventory=1.0, gamma=0.1, volatility=0.01)
        self.assertLess(res_long, 100.0)
        
        # Short inventory (q=-1.0) should shift reservation price above microprice
        res_short = compute_reservation_price(100.0, inventory=-1.0, gamma=0.1, volatility=0.01)
        self.assertGreater(res_short, 100.0)

    def test_risk_manager_kill_switch(self):
        """Verify peak-to-trough drawdown kill switch triggers when threshold is breached."""
        config = BotConfig()
        config.INITIAL_CAPITAL_USD = 1000.0
        config.MAX_DRAWDOWN_PCT = 5.0
        
        rm = RiskManager(config)
        rm.update_equity(1000.0)
        self.assertFalse(rm.kill_switch_triggered)
        
        # Drop 6% ($940 equity)
        can_trade = rm.update_equity(940.0)
        self.assertFalse(can_trade)
        self.assertTrue(rm.kill_switch_triggered)

    def test_risk_manager_position_ceiling(self):
        """Verify position ceiling blocks quote insertion on maxed exposure side."""
        config = BotConfig()
        config.MAX_POSITION_USD = 1000.0
        rm = RiskManager(config)
        
        # At $3000 ETH, max position is ~0.3333 ETH. If inventory is +0.3335 ETH, asking to BUY (bid) should fail.
        can_bid, _ = rm.can_quote(0.3335, mid_price=3000.0, is_ask=False)
        self.assertFalse(can_bid)
        
        # Asking to SELL (ask) should pass because it reduces exposure
        can_ask, _ = rm.can_quote(0.3335, mid_price=3000.0, is_ask=True)
        self.assertTrue(can_ask)

if __name__ == "__main__":
    unittest.main()
