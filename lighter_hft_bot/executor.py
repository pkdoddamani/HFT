"""
Execution Engine for Lighter.xyz High-Frequency Bot.
Handles cryptographic transaction signing, local nonce tracking, and low-latency order execution via batching.
Supports real mainnet execution via `lighter-sdk` when `config.MODE == 'live'`.
"""
import asyncio
import logging
from typing import List, Dict, Any, Tuple, Callable

logger = logging.getLogger("LighterExecutor")

class LighterExecutor:
    def __init__(self, config, on_fill_callback: Callable = None):
        self.config = config
        self.on_fill_callback = on_fill_callback
        self.signer = None
        self.current_nonce = 1
        self.active_orders: Dict[int, Dict[str, Any]] = {}
        self._next_client_order_index = 100000
        self.is_live = (config.MODE.lower() == "live")

    async def initialize(self):
        logger.info(f"Initializing Lighter Executor (Live Mode: {self.is_live})")
        if self.is_live:
            try:
                import lighter
                self.signer = lighter.SignerClient(
                    url=self.config.BASE_URL,
                    api_private_keys={self.config.API_KEY_INDEX: self.config.PRIVATE_KEY},
                    account_index=self.config.ACCOUNT_INDEX
                )
                tx_api = lighter.TransactionApi(lighter.ApiClient(lighter.Configuration(host=self.config.BASE_URL)))
                self.current_nonce = await tx_api.next_nonce(account_index=self.config.ACCOUNT_INDEX, api_key_index=self.config.API_KEY_INDEX)
                logger.info(f"Connected to Lighter live SDK. Starting nonce: {self.current_nonce}")
            except Exception as e:
                logger.critical(f"FATAL: Failed to initialize live Lighter SDK signer: {e}")
                raise RuntimeError(f"Live execution initialization failed: {e}")
        else:
            logger.info("Dry run / Backtest mode: Live signer bypassed.")

    def get_next_client_order_index(self) -> int:
        self._next_client_order_index += 1
        return self._next_client_order_index

    async def place_post_only_limit_order(self, price: float, size: float, is_ask: bool, level: int = 1) -> Tuple[int, str]:
        client_oid = self.get_next_client_order_index()
        formatted_price = int(round(price * (10 ** self.config.PRICE_DECIMALS)))
        formatted_size = int(round(size * (10 ** self.config.SIZE_DECIMALS)))
        
        if self.is_live:
            try:
                tx, tx_hash, err = await self.signer.create_order(
                    market_index=self.config.MARKET_INDEX,
                    client_order_index=client_oid,
                    base_amount=formatted_size,
                    price=formatted_price,
                    is_ask=is_ask,
                    order_type=self.signer.ORDER_TYPE_LIMIT,
                    time_in_force=self.signer.ORDER_TIME_IN_FORCE_POST_ONLY,
                    reduce_only=False,
                    order_expiry=self.signer.DEFAULT_28_DAY_ORDER_EXPIRY
                )
                if err:
                    logger.error(f"Live order rejection: {err}")
                    return -1, ""
            except Exception as e:
                logger.error(f"Live create_order error: {e}")
                return -1, ""
        else:
            tx_hash = f"0xsimulated_{client_oid}"
            
        self.active_orders[client_oid] = {
            "client_oid": client_oid,
            "price": price,
            "size": size,
            "is_ask": is_ask,
            "level": level,
            "status": "open"
        }
        return client_oid, tx_hash

    async def cancel_order(self, client_order_index: int) -> bool:
        if client_order_index not in self.active_orders:
            return False
            
        if self.is_live:
            try:
                tx, tx_hash, err = await self.signer.cancel_order(
                    market_index=self.config.MARKET_INDEX,
                    order_index=client_order_index
                )
                if err:
                    logger.error(f"Live cancel rejection: {err}")
                    return False
            except Exception as e:
                logger.error(f"Live cancel_order error: {e}")
                return False
                
        self.active_orders.pop(client_order_index, None)
        return True

    async def batch_cancel_and_replace(self, cancel_cids: List[int], new_orders: List[Dict[str, Any]]) -> List[int]:
        if not cancel_cids and not new_orders:
            return []
            
        # Execute batch cancels & inserts
        for cid in cancel_cids:
            await self.cancel_order(cid)
            
        new_cids = []
        for order in new_orders:
            cid, _ = await self.place_post_only_limit_order(
                price=order["price"],
                size=order["size"],
                is_ask=order["is_ask"],
                level=order.get("level", 1)
            )
            if cid != -1:
                new_cids.append(cid)
                
        return new_cids

    def notify_live_fill(self, client_oid: int, price: float, size: float, is_ask: bool):
        """Called when WebSocket confirms a live fill."""
        self.active_orders.pop(client_oid, None)
        if self.on_fill_callback:
            self.on_fill_callback("ASK" if is_ask else "BID", size, price)
