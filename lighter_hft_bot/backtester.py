"""
High-Frequency Backtesting Engine for Lighter.xyz.
Replays high-frequency micro-ticks or historical candle order book flow through `strategy_core.py`.
Supports deterministic runs via `BACKTEST_SEED` and loading historical tick data from CSV/JSON.
"""
import os
import json
import math
import random
import time
import logging
from typing import List, Dict, Any
from strategy_core import compute_microprice, compute_reservation_price, compute_optimal_half_spread_bps

logger = logging.getLogger("LighterBacktester")

class HighFrequencyBacktester:
    def __init__(self, config):
        self.config = config
        self.initial_capital = config.INITIAL_CAPITAL_USD
        self.capital = config.INITIAL_CAPITAL_USD
        self.inventory = 0.0
        self.avg_entry_price = 0.0
        self.realized_pnl = 0.0
        
        self.active_bid_price = 0.0
        self.active_ask_price = 0.0
        
        self.equity_curve: List[float] = [self.initial_capital]
        self.timestamps: List[float] = [0.0]
        self.inventory_history: List[float] = [0.0]
        self.trades: List[Dict[str, Any]] = []
        
    def load_historical_ticks_from_file(self, file_path: str) -> List[Dict[str, Any]]:
        """Loads historical ticks from JSON or CSV file for real-world replay."""
        if not os.path.exists(file_path):
            logger.warning(f"Historical file {file_path} not found.")
            return []
        ticks = []
        try:
            if file_path.endswith(".json"):
                with open(file_path, "r") as f:
                    ticks = json.load(f)
            elif file_path.endswith(".csv"):
                with open(file_path, "r") as f:
                    headers = f.readline().strip().split(",")
                    for idx, line in enumerate(f):
                        parts = line.strip().split(",")
                        if len(parts) >= 6:
                            ticks.append({
                                "tick_id": idx,
                                "timestamp_ms": float(parts[0]),
                                "best_bid": float(parts[1]),
                                "best_ask": float(parts[2]),
                                "bid_size": float(parts[3]),
                                "ask_size": float(parts[4]),
                                "mid_price": float(parts[5])
                            })
            logger.info(f"Loaded {len(ticks)} historical ticks from {file_path}.")
        except Exception as e:
            logger.error(f"Error loading historical ticks: {e}")
        return ticks

    def generate_synthetic_tick_flow(self, num_ticks: int = 5000, start_price: float = 3000.0) -> List[Dict[str, Any]]:
        """Generates deterministic high-frequency micro-ticks using BACKTEST_SEED."""
        random.seed(getattr(self.config, "BACKTEST_SEED", 42))
        logger.info(f"Generating {num_ticks} deterministic micro-ticks (seed: {self.config.BACKTEST_SEED}, start: ${start_price:.2f})...")
        ticks = []
        current_mid = start_price
        volatility = 0.0003
        
        for i in range(num_ticks):
            jump = current_mid * volatility * random.gauss(0, 1)
            current_mid = max(100.0, current_mid + jump)
            
            half_spread_bps = random.uniform(0.5, 2.0)
            best_bid = round(current_mid * (1 - half_spread_bps / 10000.0), 2)
            best_ask = round(current_mid * (1 + half_spread_bps / 10000.0), 2)
            
            bid_size = round(random.expovariate(1.0 / 15.0), 4)
            ask_size = round(random.expovariate(1.0 / 15.0), 4)
            
            ticks.append({
                "tick_id": i,
                "timestamp_ms": i * 100,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "bid_size": max(0.1, bid_size),
                "ask_size": max(0.1, ask_size),
                "mid_price": current_mid
            })
        return ticks

    def run_backtest(self, ticks: List[Dict[str, Any]] = None, file_path: str = None) -> Dict[str, Any]:
        if file_path:
            ticks = self.load_historical_ticks_from_file(file_path)
        if not ticks:
            ticks = self.generate_synthetic_tick_flow()
            
        logger.info(f"Running Avellaneda-Stoikov backtest over {len(ticks)} ticks using unified math core...")
        start_t = time.time()
        
        gamma = self.config.RISK_AVERSION_GAMMA
        k = self.config.ORDER_BOOK_DEPTH_K
        base_size = self.config.BASE_ORDER_SIZE
        max_pos = self.config.MAX_POSITION_SIZE
        
        returns = []
        last_mid = ticks[0]["mid_price"]
        
        for tick in ticks:
            best_bid = tick["best_bid"]
            best_ask = tick["best_ask"]
            bid_size = tick["bid_size"]
            ask_size = tick["ask_size"]
            mid = tick["mid_price"]
            
            ret = (mid - last_mid) / last_mid if last_mid > 0 else 0
            returns.append(ret)
            if len(returns) > 50:
                returns.pop(0)
            sigma = (sum([r**2 for r in returns]) / max(1, len(returns))) ** 0.5
            sigma = max(0.0001, sigma)
            last_mid = mid
            
            if self.active_bid_price > 0 and (best_ask <= self.active_bid_price or (best_bid <= self.active_bid_price and random.random() < 0.25)):
                self._process_backtest_fill("BID", self.active_bid_price, base_size, tick["tick_id"])
            if self.active_ask_price > 0 and (best_bid >= self.active_ask_price or (best_ask >= self.active_ask_price and random.random() < 0.25)):
                self._process_backtest_fill("ASK", self.active_ask_price, base_size, tick["tick_id"])
                
            micro_price = compute_microprice(best_bid, best_ask, bid_size, ask_size)
            reservation_price = compute_reservation_price(micro_price, self.inventory, gamma, sigma)
            half_spread_bps = compute_optimal_half_spread_bps(gamma, k, sigma, self.config.MIN_SPREAD_BPS, self.config.MAX_SPREAD_BPS, mid)
            half_spread_abs = (half_spread_bps / 10000.0) * mid
            
            target_bid = round(reservation_price - half_spread_abs, 2)
            target_ask = round(reservation_price + half_spread_abs, 2)
            
            self.active_bid_price = min(target_bid, best_bid) if self.inventory < max_pos else 0.0
            self.active_ask_price = max(target_ask, best_ask) if self.inventory > -max_pos else 0.0
            
            unrealized = (mid - self.avg_entry_price) * self.inventory if self.inventory != 0 else 0.0
            total_eq = self.initial_capital + self.realized_pnl + unrealized
            self.equity_curve.append(total_eq)
            self.timestamps.append(tick["timestamp_ms"] / 1000.0)
            self.inventory_history.append(self.inventory)
            
        elapsed = time.time() - start_t
        logger.info(f"Backtest completed in {elapsed:.3f} seconds.")
        return self._compute_metrics()

    def _process_backtest_fill(self, side: str, price: float, size: float, tick_id: int):
        trade_pnl = 0.0
        if side == "ASK":
            if self.inventory > 0:
                closed = min(size, self.inventory)
                trade_pnl = (price - self.avg_entry_price) * closed
                self.realized_pnl += trade_pnl
            if self.inventory <= 0:
                current_short_size = abs(self.inventory)
                self.avg_entry_price = ((self.avg_entry_price * current_short_size) + (price * size)) / (current_short_size + size)
            self.inventory -= size
        else:
            if self.inventory < 0:
                closed = min(size, abs(self.inventory))
                trade_pnl = (self.avg_entry_price - price) * closed
                self.realized_pnl += trade_pnl
            if self.inventory >= 0:
                self.avg_entry_price = ((self.avg_entry_price * self.inventory) + (price * size)) / (self.inventory + size)
            self.inventory += size
            
        self.trades.append({
            "tick_id": tick_id,
            "side": side,
            "price": price,
            "size": size,
            "pnl": trade_pnl,
            "inventory": self.inventory
        })

    def _compute_metrics(self) -> Dict[str, Any]:
        total_return_usd = self.equity_curve[-1] - self.initial_capital
        total_return_pct = (total_return_usd / self.initial_capital) * 100.0
        
        peak = self.initial_capital
        max_dd_usd = 0.0
        max_dd_pct = 0.0
        for eq in self.equity_curve:
            if eq > peak:
                peak = eq
            dd = peak - eq
            dd_pct = (dd / peak) * 100.0 if peak > 0 else 0.0
            if dd > max_dd_usd:
                max_dd_usd = dd
                max_dd_pct = dd_pct
                
        eq_diffs = [self.equity_curve[i] - self.equity_curve[i-1] for i in range(1, len(self.equity_curve))]
        mean_diff = sum(eq_diffs) / len(eq_diffs) if eq_diffs else 0.0
        std_diff = (sum([(d - mean_diff)**2 for d in eq_diffs]) / max(1, len(eq_diffs))) ** 0.5
        sharpe = (mean_diff / std_diff) * (315360000 ** 0.5) if std_diff > 0 else 0.0
        
        win_trades = [t for t in self.trades if t["pnl"] > 0]
        lose_trades = [t for t in self.trades if t["pnl"] < 0]
        win_rate = (len(win_trades) / max(1, len(win_trades) + len(lose_trades))) * 100.0
        
        report = {
            "strategy": "Avellaneda-Stoikov HF Market Maker",
            "symbol": self.config.SYMBOL,
            "seed": getattr(self.config, "BACKTEST_SEED", 42),
            "total_ticks_simulated": len(self.equity_curve),
            "initial_capital_usd": round(self.initial_capital, 2),
            "final_equity_usd": round(self.equity_curve[-1], 2),
            "total_pnl_usd": round(total_return_usd, 2),
            "total_return_pct": round(total_return_pct, 3),
            "sharpe_ratio": round(sharpe, 2),
            "max_drawdown_usd": round(max_dd_usd, 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
            "total_fills": len(self.trades),
            "win_rate_pct": round(win_rate, 2),
            "final_inventory_eth": round(self.inventory, 4)
        }
        
        try:
            with open(self.config.REPORT_FILE_BACKTEST, "w") as f:
                json.dump(report, f, indent=2)
        except Exception as e:
            pass
            
        return report
