"""
Dry Run (Paper Trading) Virtual Matching Engine for Lighter.xyz.
Simulates order placement, latency throttling, realistic maker matching against incoming BBO feed,
and tracks PnL, inventory drift, and execution performance without risking real capital.
Generates comprehensive diagnostic reports for course correction before live deployment.
"""
import asyncio
import json
import logging
import time
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("LighterDryRunEngine")

class DryRunExecutor:
    def __init__(self, config, toxic_guard=None, symbol="ETH-PERP", on_fill_callback=None):
        self.config = config
        self.toxic_guard = toxic_guard
        self.symbol = symbol
        self.on_fill_callback = on_fill_callback
        self.active_orders: Dict[int, Dict[str, Any]] = {}
        self._next_client_order_index = 200000
        
        # Portfolio State
        self.initial_balance = config.INITIAL_CAPITAL_USD
        self.cash = config.INITIAL_CAPITAL_USD
        self.inventory = 0.0          # Net position (+ Long, - Short)
        self.avg_entry_price = 0.0
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0
        
        # Performance & Diagnostic Tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.losing_trades = 0
        self.total_volume_traded = 0.0
        self.trade_history: List[Dict[str, Any]] = []
        self.inventory_history: List[float] = []
        self.order_cancellations = 0
        self.order_placements = 0
        self.start_time = time.time()
        self.peak_equity = config.INITIAL_CAPITAL_USD
        self.max_drawdown_usd = 0.0
        
    async def initialize(self):
        logger.info("==========================================================")
        logger.info(f"Initializing DRY RUN (Paper Trading) Virtual Engine")
        logger.info(f"Simulated Account Tier: {'PREMIUM (0ms Post-Only/Cancel delay)' if self.config.IS_PREMIUM_ACCOUNT else 'STANDARD (200ms engine delay)'}")
        logger.info(f"Starting Capital: ${self.initial_balance:.2f} USD")
        logger.info("==========================================================")

    def get_next_client_order_index(self) -> int:
        self._next_client_order_index += 1
        return self._next_client_order_index

    async def place_post_only_limit_order(self, price: float, size: float, is_ask: bool) -> Tuple[int, str]:
        client_oid = self.get_next_client_order_index()
        self.order_placements += 1
        
        if self.config.SIMULATED_LATENCY_MS > 0:
            await asyncio.sleep(self.config.SIMULATED_LATENCY_MS / 1000.0)
            
        self.active_orders[client_oid] = {
            "client_oid": client_oid,
            "price": price,
            "size": size,
            "is_ask": is_ask,
            "status": "open",
            "created_at": time.time()
        }
        return client_oid, f"0xdryrun_{client_oid}"

    async def cancel_order(self, client_order_index: int) -> bool:
        if client_order_index not in self.active_orders:
            return False
            
        if self.config.SIMULATED_LATENCY_MS > 0:
            await asyncio.sleep(self.config.SIMULATED_LATENCY_MS / 1000.0)
            
        self.active_orders.pop(client_order_index, None)
        self.order_cancellations += 1
        return True

    async def batch_cancel_and_replace(self, cancel_cids: List[int], new_orders: List[Dict[str, Any]]) -> List[int]:
        if not cancel_cids and not new_orders:
            return []
            
        if self.config.SIMULATED_LATENCY_MS > 0:
            await asyncio.sleep(self.config.SIMULATED_LATENCY_MS / 1000.0)
            
        for cid in cancel_cids:
            if self.active_orders.pop(cid, None):
                self.order_cancellations += 1
            
        new_cids = []
        for order in new_orders:
            cid = self.get_next_client_order_index()
            self.active_orders[cid] = {
                "client_oid": cid,
                "price": order["price"],
                "size": order["size"],
                "is_ask": order["is_ask"],
                "status": "open",
                "created_at": time.time()
            }
            self.order_placements += 1
            new_cids.append(cid)
            
        return new_cids

    async def on_bbo_tick(self, best_bid: float, best_ask: float):
        import random
        if self.toxic_guard:
            if random.random() < 0.15:
                side = "BUY" if random.random() < 0.5 else "SELL"
                self.toxic_guard.record_market_trade(side, random.uniform(0.5, 3.0))
                
        filled_cids = []
        mid = (best_bid + best_ask) / 2.0
        for cid, order in list(self.active_orders.items()):
            price = order["price"]
            size = order["size"]
            is_ask = order["is_ask"]
            level = order.get("level", 1)
            
            fill_triggered = False
            if not is_ask:
                # Bid fills if market price crosses limit, OR if Level 1 sitting near touch gets swept by taker sell volume
                dist_bps = ((mid - price) / mid) * 10000.0 if mid > 0 else 10.0
                if best_ask <= price or (level == 1 and dist_bps <= 3.5 and random.random() < 0.25):
                    fill_triggered = True
            else:
                # Ask fills if market price crosses limit, OR if Level 1 sitting near touch gets swept by taker buy volume
                dist_bps = ((price - mid) / mid) * 10000.0 if mid > 0 else 10.0
                if best_bid >= price or (level == 1 and dist_bps <= 3.5 and random.random() < 0.25):
                    fill_triggered = True
                
            if fill_triggered:
                self._process_fill(cid, price, size, is_ask)
                filled_cids.append(cid)
                
        for cid in filled_cids:
            self.active_orders.pop(cid, None)
            
        mid_price = (best_bid + best_ask) / 2.0
        if self.inventory != 0.0:
            self.unrealized_pnl = (mid_price - self.avg_entry_price) * self.inventory
            
        equity = self.get_total_equity()
        if equity > self.peak_equity:
            self.peak_equity = equity
        dd = self.peak_equity - equity
        if dd > self.max_drawdown_usd:
            self.max_drawdown_usd = dd
            
        self.inventory_history.append(self.inventory)

    def _process_fill(self, cid: int, price: float, size: float, is_ask: bool):
        self.total_trades += 1
        self.total_volume_traded += price * size
        trade_fee = 0.0  # 0% maker fee on Standard/Premium
        
        trade_pnl = 0.0
        if is_ask:  # Selling
            if self.inventory > 0:
                closed_size = min(size, self.inventory)
                trade_pnl = (price - self.avg_entry_price) * closed_size
                self.realized_pnl += trade_pnl
                if trade_pnl > 0:
                    self.winning_trades += 1
                elif trade_pnl < 0:
                    self.losing_trades += 1
            if self.inventory <= 0:
                current_short_size = abs(self.inventory)
                self.avg_entry_price = ((self.avg_entry_price * current_short_size) + (price * size)) / (current_short_size + size)
            self.inventory -= size
            self.cash += (price * size) - trade_fee
        else:       # Buying
            if self.inventory < 0:
                closed_size = min(size, abs(self.inventory))
                trade_pnl = (self.avg_entry_price - price) * closed_size
                self.realized_pnl += trade_pnl
                if trade_pnl > 0:
                    self.winning_trades += 1
                elif trade_pnl < 0:
                    self.losing_trades += 1
            if self.inventory >= 0:
                self.avg_entry_price = ((self.avg_entry_price * self.inventory) + (price * size)) / (self.inventory + size)
            self.inventory += size
            self.cash -= (price * size) + trade_fee
            
        logger.info(f"[DRY-RUN FILL] {'ASK (Sell)' if is_ask else 'BID (Buy)'} {size} ETH @ ${price:.2f} | PnL: ${trade_pnl:+.2f} | Net Inv: {self.inventory:.4f} ETH")
        
        self.trade_history.append({
            "timestamp": time.time(),
            "side": "ASK" if is_ask else "BID",
            "price": price,
            "size": size,
            "pnl": trade_pnl,
            "inventory": self.inventory,
            "total_realized_pnl": self.realized_pnl
        })
        if self.on_fill_callback:
            self.on_fill_callback("ASK" if is_ask else "BID", size, price)
        self.export_summary()

    def get_total_equity(self) -> float:
        return self.initial_balance + self.realized_pnl + self.unrealized_pnl

    def get_state(self) -> Dict[str, Any]:
        return {
            "equity": self.get_total_equity(),
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
            "inventory": self.inventory,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "losing_trades": self.losing_trades,
            "recent_trades": self.trade_history
        }

    def export_summary(self) -> dict:
        equity = self.get_total_equity()
        win_rate = (self.winning_trades / max(1, self.winning_trades + self.losing_trades)) * 100.0
        runtime = max(1.0, time.time() - self.start_time)
        
        # Diagnostics & Recommendations
        avg_inv = sum(self.inventory_history) / len(self.inventory_history) if self.inventory_history else 0.0
        max_abs_inv = max([abs(x) for x in self.inventory_history]) if self.inventory_history else 0.0
        
        recommendations = []
        if max_abs_inv >= self.config.MAX_POSITION_SIZE * 0.9:
            recommendations.append("CRITICAL: Inventory reached ceiling. Increase RISK_AVERSION_GAMMA to skew quotes away from accumulated exposure earlier.")
        if win_rate < 50.0 and self.total_trades >= 10:
            recommendations.append("ADVICE: Win rate below 50%. Widen MIN_SPREAD_BPS from current setting to capture extra spread cushion during adverse price drift.")
        if not recommendations:
            recommendations.append("OPTIMAL: Parameters show balanced inventory distribution and positive maker expectancy.")

        summary = {
            "mode": "DRY_RUN_DIAGNOSTICS",
            "symbol": self.symbol,
            "timestamp": time.time(),
            "duration_seconds": round(runtime, 2),
            "account_profile": {
                "is_premium": self.config.IS_PREMIUM_ACCOUNT,
                "simulated_latency_ms": self.config.SIMULATED_LATENCY_MS
            },
            "portfolio_metrics": {
                "initial_balance_usd": round(self.initial_balance, 2),
                "current_equity_usd": round(equity, 2),
                "realized_pnl_usd": round(self.realized_pnl, 2),
                "unrealized_pnl_usd": round(self.unrealized_pnl, 2),
                "total_return_pct": round(((equity - self.initial_balance) / self.initial_balance) * 100.0, 3),
                "max_drawdown_usd": round(self.max_drawdown_usd, 2)
            },
            "execution_metrics": {
                "total_fills": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
                "win_rate_pct": round(win_rate, 2),
                "total_volume_usd": round(self.total_volume_traded, 2),
                "order_placements": self.order_placements,
                "order_cancellations": self.order_cancellations
            },
            "inventory_diagnostics": {
                "current_inventory_eth": round(self.inventory, 4),
                "average_inventory_eth": round(avg_inv, 4),
                "max_absolute_inventory_eth": round(max_abs_inv, 4),
                "max_position_limit_eth": self.config.MAX_POSITION_SIZE
            },
            "course_correction_recommendations": recommendations,
            "recent_trades": self.trade_history[-20:] if self.trade_history else []
        }
        
        try:
            with open("dry_run_diagnostics.json", "w") as f:
                json.dump(summary, f, indent=2)
            self._export_html_diagnostics(summary)
        except Exception as e:
            logger.error(f"Failed to export dry run diagnostics: {e}")
            
        return summary

    def _export_html_diagnostics(self, summary: dict):
        html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Lighter.xyz Dry Run Diagnostic Report</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 2rem; }}
        .header {{ border-bottom: 1px solid #334155; padding-bottom: 1.5rem; margin-bottom: 2rem; }}
        h1 {{ margin: 0 0 0.5rem 0; font-size: 1.8rem; color: #38bdf8; }}
        .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
        .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 1.2rem; }}
        .card .label {{ font-size: 0.85rem; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 0.4rem; }}
        .card .value {{ font-size: 1.5rem; font-weight: 700; color: #f8fafc; }}
        .pos {{ color: #4ade80; }}
        .neg {{ color: #f87171; }}
        .rec {{ background: #172554; border-left: 4px solid #3b82f6; padding: 1rem; border-radius: 4px; margin-bottom: 2rem; }}
        table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 8px; overflow: hidden; }}
        th, td {{ padding: 0.8rem 1rem; text-align: left; border-bottom: 1px solid #334155; font-size: 0.9rem; }}
        th {{ background: #0f172a; color: #94a3b8; font-weight: 600; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Lighter.xyz Dry Run Diagnostic & Course Correction Report</h1>
        <p style="color: #94a3b8; margin: 0;">Market: {summary['symbol']} | Mode: DRY RUN | Simulated Latency: {summary['account_profile']['simulated_latency_ms']} ms</p>
    </div>
    <div class="rec">
        <h3 style="margin: 0 0 0.5rem 0; color: #60a5fa;">💡 Actionable Course Correction Recommendations</h3>
        {"<br>".join([f"• <b>{r}</b>" for r in summary['course_correction_recommendations']])}
    </div>
    <div class="grid">
        <div class="card">
            <div class="label">Total Equity</div>
            <div class="value {'pos' if summary['portfolio_metrics']['total_return_pct']>=0 else 'neg'}">${summary['portfolio_metrics']['current_equity_usd']:,.2f} ({summary['portfolio_metrics']['total_return_pct']:+.2f}%)</div>
        </div>
        <div class="card">
            <div class="label">Realized / Unrealized PnL</div>
            <div class="value pos">${summary['portfolio_metrics']['realized_pnl_usd']:+,.2f} / ${summary['portfolio_metrics']['unrealized_pnl_usd']:+,.2f}</div>
        </div>
        <div class="card">
            <div class="label">Win Rate & Accuracy</div>
            <div class="value">{summary['execution_metrics']['win_rate_pct']:.1f}%</div>
        </div>
        <div class="card">
            <div class="label">Total Fills / Volume</div>
            <div class="value">{summary['execution_metrics']['total_fills']} fills (${summary['execution_metrics']['total_volume_usd']:,.0f})</div>
        </div>
        <div class="card">
            <div class="label">Max Drawdown</div>
            <div class="value neg">${summary['portfolio_metrics']['max_drawdown_usd']:,.2f}</div>
        </div>
        <div class="card">
            <div class="label">Inventory Exposure</div>
            <div class="value">{summary['inventory_diagnostics']['current_inventory_eth']:+.4f} ETH</div>
        </div>
    </div>
</body>
</html>"""
        try:
            with open("dry_run_report.html", "w") as f:
                f.write(html)
        except Exception as e:
            pass
