"""
Unified Avellaneda-Stoikov Quantitative Core (`strategy_core.py`).
Pure mathematical functions shared across Live execution (`strategy_mm.py`),
Dry Run virtual engine (`dry_run.py`), and Backtesting framework (`backtester.py`).
Guarantees identical risk modeling across simulation and live trading.
"""
import math
from typing import List, Dict, Any

def compute_microprice(best_bid: float, best_ask: float, bid_size: float, ask_size: float) -> float:
    """Calculates volume-weighted Order Book Imbalance (OIB) microprice."""
    if bid_size + ask_size == 0:
        return (best_bid + best_ask) / 2.0
    imbalance = bid_size / (bid_size + ask_size)
    return best_bid * (1.0 - imbalance) + best_ask * imbalance

def compute_reservation_price(micro_price: float, inventory: float, gamma: float, volatility: float) -> float:
    """
    Avellaneda-Stoikov Reservation Price formula: r(s, q) = s - q * gamma * sigma^2.
    Skews quotes away from accumulated inventory exposure.
    """
    sigma2 = max(1e-8, volatility ** 2)
    return micro_price - (inventory * gamma * sigma2)

def compute_optimal_half_spread_bps(gamma: float, k: float, volatility: float, min_bps: float, max_bps: float, mid_price: float) -> float:
    """
    Avellaneda-Stoikov Optimal Half-Spread formula in basis points.
    delta = gamma * sigma^2 + (2 / gamma) * ln(1 + gamma / k).
    """
    sigma2 = max(1e-8, volatility ** 2)
    theoretical_half_spread = (gamma * sigma2) + (2.0 / max(1e-4, gamma)) * math.log(1.0 + gamma / max(1e-4, k))
    spread_bps = (theoretical_half_spread / max(1.0, mid_price)) * 10000.0
    return max(min_bps, min(max_bps, spread_bps))

def compute_ladder_quotes(
    reservation_price: float,
    half_spread_bps: float,
    mid_price: float,
    order_size: float,
    num_levels: int,
    step_bps: float,
    best_bid: float,
    best_ask: float,
    quote_bid: bool,
    quote_ask: bool,
    bid_multiplier: float = 1.0,
    ask_multiplier: float = 1.0
) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
    """
    Generates multi-level Post-Only order ladder for BID and ASK sides.
    """
    target_bids = []
    target_asks = []
    
    base_spread_abs = (half_spread_bps / 10000.0) * mid_price
    step_abs = (step_bps / 10000.0) * mid_price
    
    if quote_bid:
        for lvl in range(num_levels):
            p = round(reservation_price - (base_spread_abs * bid_multiplier) - (lvl * step_abs), 2)
            p = min(p, best_bid)  # Post-Only guarantee
            if p > 0:
                target_bids.append({"price": p, "size": order_size, "level": lvl + 1})
                
    if quote_ask:
        for lvl in range(num_levels):
            p = round(reservation_price + (base_spread_abs * ask_multiplier) + (lvl * step_abs), 2)
            p = max(p, best_ask)  # Post-Only guarantee
            if p > 0:
                target_asks.append({"price": p, "size": order_size, "level": lvl + 1})
                
    return target_bids, target_asks
