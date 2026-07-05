"""
Real-Time Terminal Dashboard for Lighter.xyz Institutional HFT Bot.
Built with `rich` for stunning layout rendering in Windows PowerShell / Unix Terminals.
Displays Multi-Asset live BBOs (ETH, BTC, SOL), multi-level ladders, Avellaneda-Stoikov states,
OFI toxicity scores, external Binance lead-lag alpha deltas, and unified recent trade history.
"""
import time
from datetime import datetime
from typing import Dict, Any, List
from rich.console import Console
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.align import Align

class LiveTerminalDashboard:
    def __init__(self, config):
        self.config = config
        self.console = Console()
        self.start_time = time.time()
        
    def generate_layout(self, markets_data: List[Dict[str, Any]]) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="metrics", size=7),
            Layout(name="middle", size=12),
            Layout(name="trades", size=10)
        )
        
        # 1. Header Panel
        runtime = round(time.time() - self.start_time)
        hrs, rem = divmod(runtime, 3600)
        mins, secs = divmod(rem, 60)
        runtime_str = f"{hrs:02d}:{mins:02d}:{secs:02d}"
        
        mode_color = "yellow" if self.config.MODE == "dry_run" else ("green" if self.config.MODE == "live" else "cyan")
        symbols_str = ", ".join([inst["symbol"] for inst in markets_data])
        header_text = Text.from_markup(
            f"[bold white]LIGHTER.XYZ MULTI-ASSET INSTITUTIONAL HFT BOT[/bold white] | "
            f"Mode: [bold {mode_color}]{self.config.MODE.upper()}[/bold {mode_color}] | "
            f"Markets: [bold cyan]{symbols_str}[/bold cyan] | "
            f"Account: [bold magenta]{'PREMIUM 0ms Latency' if self.config.IS_PREMIUM_ACCOUNT else 'STANDARD 200ms Delay'}[/bold magenta] | "
            f"Runtime: [bold white]{runtime_str}[/bold white]"
        )
        layout["header"].update(Panel(Align.center(header_text), style="blue"))
        
        # 2. Portfolio Metrics Table (Aggregated across all active markets)
        metrics_table = Table.grid(expand=True)
        metrics_table.add_column(justify="center", ratio=1)
        metrics_table.add_column(justify="center", ratio=1)
        metrics_table.add_column(justify="center", ratio=1)
        metrics_table.add_column(justify="center", ratio=1)
        
        total_eq = 0.0
        total_realized = 0.0
        total_unrealized = 0.0
        total_trades = 0
        total_wins = 0
        total_losses = 0
        all_recent_trades = []
        
        for inst in markets_data:
            est = inst["executor"].get_state() if hasattr(inst["executor"], "get_state") else {}
            total_eq += est.get("equity", self.config.INITIAL_CAPITAL_USD)
            total_realized += est.get("realized_pnl", 0.0)
            total_unrealized += est.get("unrealized_pnl", 0.0)
            total_trades += est.get("total_trades", 0)
            total_wins += est.get("winning_trades", 0)
            total_losses += est.get("losing_trades", 0)
            for t in est.get("recent_trades", []):
                t["symbol"] = inst["symbol"]
                all_recent_trades.append(t)
                
        # Sort recent trades by timestamp
        all_recent_trades.sort(key=lambda x: x["timestamp"])
        
        base_cap = self.config.INITIAL_CAPITAL_USD * len(markets_data)
        ret_pct = ((total_eq - base_cap) / base_cap) * 100.0 if base_cap > 0 else 0.0
        eq_color = "green" if ret_pct >= 0 else "red"
        win_rate = (total_wins / max(1, total_wins + total_losses)) * 100.0
        
        metrics_table.add_row(
            f"[dim]COMBINED EQUITY[/dim]\n[bold {eq_color}]${total_eq:,.2f} ({ret_pct:+.2f}%)[/bold {eq_color}]",
            f"[dim]REALIZED / UNREALIZED PNL[/dim]\n[bold green]${total_realized:+,.2f}[/bold green] / [bold {'green' if total_unrealized>=0 else 'red'}]${total_unrealized:+,.2f}[/bold {'green' if total_unrealized>=0 else 'red'}]",
            f"[dim]ACTIVE MARKETS COUNT[/dim]\n[bold cyan]{len(markets_data)} Markets Active[/bold cyan] [dim]($100/order each)[/dim]",
            f"[dim]COMBINED ACCURACY[/dim]\n[bold yellow]{win_rate:.1f}%[/bold yellow] [dim]({total_wins}W / {total_losses}L / {total_trades} total)[/dim]"
        )
        layout["metrics"].update(Panel(metrics_table, title="[bold white]Multi-Asset Portfolio Performance[/bold white]", border_style="cyan"))
        
        # 3. Middle Section: Per-Market Breakdown Table
        market_breakdown = Table(expand=True, border_style="blue", box=None)
        market_breakdown.add_column("Market", style="bold cyan", width=12)
        market_breakdown.add_column("Mid Price", justify="right", width=12)
        market_breakdown.add_column("Ask Ladder (Level 1)", justify="right", width=22)
        market_breakdown.add_column("Bid Ladder (Level 1)", justify="right", width=22)
        market_breakdown.add_column("OFI Toxicity", justify="center", width=14)
        market_breakdown.add_column("Binance Alpha", justify="right", width=14)
        market_breakdown.add_column("Net Inv ($ value)", justify="right", width=16)
        
        for inst in markets_data:
            sst = inst["strategy"].get_state() if hasattr(inst["strategy"], "get_state") else {}
            tst = inst["toxic_guard"].get_state()
            fst = inst["external_feed"].get_state()
            
            sym = inst["symbol"]
            mid = sst.get("mid_price", 0.0)
            ask_p = sst.get("active_ask_price", 0.0)
            bid_p = sst.get("active_bid_price", 0.0)
            ask_cnt = sst.get("active_asks_count", 0)
            bid_cnt = sst.get("active_bids_count", 0)
            inv = sst.get("inventory", 0.0)
            inv_val = inv * mid
            
            ask_str = f"${ask_p:,.2f} ({ask_cnt}L)" if ask_p > 0 else "[dim]Paused[/dim]"
            bid_str = f"${bid_p:,.2f} ({bid_cnt}L)" if bid_p > 0 else "[dim]Paused[/dim]"
            
            ofi = tst.get("toxicity_score", 0.0)
            ofi_side = tst.get("toxic_side", "NONE")
            ofi_str = f"[bold {'red' if ofi_side!='NONE' else 'green'}]{ofi:.2f} ({ofi_side})[/bold {'red' if ofi_side!='NONE' else 'green'}]"
            
            lead_delta = fst.get("lead_lag_delta_bps", 0.0)
            lead_str = f"[bold {'cyan' if lead_delta>=0 else 'yellow'}]{lead_delta:+.2f} bps[/bold {'cyan' if lead_delta>=0 else 'yellow'}]"
            
            inv_str = f"{inv:+.3f} (${inv_val:+,.0f})"
            market_breakdown.add_row(sym, f"${mid:,.2f}", ask_str, bid_str, ofi_str, lead_str, inv_str)
            
        layout["middle"].update(Panel(market_breakdown, title="[bold white]Active Market Making Engines & Institutional Alpha[/bold white]", border_style="blue"))
        
        # 4. Fills & Trade History Table
        trades_table = Table(expand=True, border_style="dim", box=None)
        trades_table.add_column("Time", style="dim", width=10)
        trades_table.add_column("Market", style="bold cyan", width=10)
        trades_table.add_column("Side", justify="center", width=8)
        trades_table.add_column("Size", justify="right", width=10)
        trades_table.add_column("Exec Price", justify="right", width=12)
        trades_table.add_column("PnL ($)", justify="right", width=12)
        trades_table.add_column("Status / Alpha Note", style="dim", justify="left")
        
        recent_list = all_recent_trades[-5:]
        if not recent_list:
            trades_table.add_row("-", "-", "-", "-", "-", "-", "Waiting for multi-asset high-frequency fills...")
        else:
            for t in reversed(recent_list):
                t_time = datetime.fromtimestamp(t["timestamp"]).strftime("%H:%M:%S")
                side_str = "[bold green]BUY[/bold green]" if t["side"] == "BID" else "[bold red]SELL[/bold red]"
                pnl_val = t["pnl"]
                pnl_str = f"[bold green]+${pnl_val:.2f}[/bold green]" if pnl_val > 0 else (f"[bold red]-${abs(pnl_val):.2f}[/bold red]" if pnl_val < 0 else "$0.00")
                note = "Post-Only Maker Fill (0% Fee)"
                if pnl_val > 0:
                    note = "[green]Spread Harvest / Take-Profit[/green]"
                trades_table.add_row(t_time, t["symbol"], side_str, f"{t['size']:.4f}", f"${t['price']:,.2f}", pnl_str, note)
                
        layout["trades"].update(Panel(trades_table, title="[bold white]Unified Multi-Asset Live Fills[/bold white]", border_style="yellow"))
        return layout
