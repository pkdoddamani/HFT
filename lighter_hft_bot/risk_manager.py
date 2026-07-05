"""
Institutional Risk Manager (`risk_manager.py`).
Enforces hard safety boundaries across Live, Dry Run, and Backtesting modes:
1. Maximum Position Ceiling Check
2. Maximum Peak-to-Trough Drawdown Kill Switch
3. Extreme Volatility Circuit Breaker
"""
import logging
from typing import Dict, Any, Tuple

logger = logging.getLogger("RiskManager")

class RiskManager:
    def __init__(self, config):
        self.config = config
        self.peak_equity = config.INITIAL_CAPITAL_USD
        self.current_drawdown_pct = 0.0
        self.kill_switch_triggered = False
        self.kill_switch_reason = ""
        self.volatility_circuit_breaker = False
        
        # Risk thresholds
        self.max_allowed_drawdown_pct = getattr(config, "MAX_DRAWDOWN_PCT", 5.0)  # 5% max drawdown halt
        self.max_allowed_volatility = getattr(config, "MAX_VOLATILITY_THRESHOLD", 0.008) # 0.8% per tick circuit breaker

    def update_equity(self, current_equity: float) -> bool:
        """
        Updates equity tracking and evaluates the Drawdown Kill Switch.
        Returns True if trading can proceed, False if Kill Switch triggered.
        """
        if current_equity > self.peak_equity:
            self.peak_equity = current_equity
            
        if self.peak_equity > 0:
            self.current_drawdown_pct = ((self.peak_equity - current_equity) / self.peak_equity) * 100.0
            
        if self.current_drawdown_pct >= self.max_allowed_drawdown_pct and not self.kill_switch_triggered:
            self.kill_switch_triggered = True
            self.kill_switch_reason = f"Drawdown limit reached ({self.current_drawdown_pct:.2f}% >= {self.max_allowed_drawdown_pct:.2f}%)"
            logger.critical(f"🚨 KILL SWITCH TRIGGERED: {self.kill_switch_reason}. Halting all new quotes!")
            
        return not self.kill_switch_triggered

    def evaluate_volatility(self, volatility: float) -> bool:
        """
        Evaluates the Volatility Circuit Breaker.
        Returns True if normal, False if circuit breaker tripped.
        """
        if volatility >= self.max_allowed_volatility:
            if not self.volatility_circuit_breaker:
                logger.warning(f"⚡ Volatility Circuit Breaker tripped (sigma={volatility*100:.3f}% >= {self.max_allowed_volatility*100:.3f}%). Pausing quotes.")
            self.volatility_circuit_breaker = True
        else:
            if self.volatility_circuit_breaker:
                logger.info("⚡ Volatility normalized. Circuit breaker reset.")
            self.volatility_circuit_breaker = False
            
        return not self.volatility_circuit_breaker

    def can_quote(self, current_inventory_eth: float, mid_price: float, is_ask: bool) -> Tuple[bool, str]:
        """
        Comprehensive pre-quote risk check.
        Returns (can_quote: bool, reason: str).
        """
        if self.kill_switch_triggered:
            return False, f"KILL_SWITCH: {self.kill_switch_reason}"
            
        if self.volatility_circuit_breaker:
            return False, "CIRCUIT_BREAKER: Extreme market volatility"
            
        max_pos_eth = round(self.config.MAX_POSITION_USD / max(mid_price, 100.0), 4)
        
        if is_ask:  # Selling increases short exposure (-)
            if current_inventory_eth <= -max_pos_eth:
                return False, f"CEILING: Max short exposure reached ({current_inventory_eth:.4f} ETH)"
        else:       # Buying increases long exposure (+)
            if current_inventory_eth >= max_pos_eth:
                return False, f"CEILING: Max long exposure reached ({current_inventory_eth:.4f} ETH)"
                
        return True, "OK"

    def get_state(self) -> Dict[str, Any]:
        return {
            "kill_switch_triggered": self.kill_switch_triggered,
            "kill_switch_reason": self.kill_switch_reason,
            "current_drawdown_pct": round(self.current_drawdown_pct, 2),
            "volatility_circuit_breaker": self.volatility_circuit_breaker
        }
