import json
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "traderbot.db"


@dataclass
class BotState:
    operation_code: str
    take_profit_index: int = 0
    last_trade_decision: Optional[bool] = None
    last_buy_price: float = 0.0
    last_sell_price: float = 0.0
    actual_trade_position: bool = False
    active_mode: str = "trend"
    grid_support: float = 0.0
    grid_resistance: float = 0.0
    breakout_cooldown_candles: int = 0
    updated_at: str = ""

    def touch(self):
        self.updated_at = datetime.now(timezone.utc).isoformat()


class StateStore:
    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS bot_state (
                    operation_code TEXT PRIMARY KEY,
                    take_profit_index INTEGER NOT NULL DEFAULT 0,
                    last_trade_decision INTEGER,
                    last_buy_price REAL NOT NULL DEFAULT 0,
                    last_sell_price REAL NOT NULL DEFAULT 0,
                    actual_trade_position INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    operation_code TEXT NOT NULL,
                    order_id INTEGER,
                    side TEXT,
                    order_type TEXT,
                    status TEXT,
                    quantity REAL,
                    price REAL,
                    total_quote REAL,
                    raw_json TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._migrate(conn)

    def _migrate(self, conn):
        columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(bot_state)").fetchall()
        }
        migrations = {
            "active_mode": "TEXT NOT NULL DEFAULT 'trend'",
            "grid_support": "REAL NOT NULL DEFAULT 0",
            "grid_resistance": "REAL NOT NULL DEFAULT 0",
            "breakout_cooldown_candles": "INTEGER NOT NULL DEFAULT 0",
        }
        for name, ddl in migrations.items():
            if name not in columns:
                conn.execute(f"ALTER TABLE bot_state ADD COLUMN {name} {ddl}")

    def load_state(self, operation_code: str) -> BotState:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM bot_state WHERE operation_code = ?",
                (operation_code,),
            ).fetchone()
        if not row:
            state = BotState(operation_code=operation_code)
            state.touch()
            return state
        return BotState(
            operation_code=row["operation_code"],
            take_profit_index=row["take_profit_index"],
            last_trade_decision=(
                None if row["last_trade_decision"] is None else bool(row["last_trade_decision"])
            ),
            last_buy_price=row["last_buy_price"],
            last_sell_price=row["last_sell_price"],
            actual_trade_position=bool(row["actual_trade_position"]),
            active_mode=row["active_mode"] if "active_mode" in row.keys() else "trend",
            grid_support=row["grid_support"] if "grid_support" in row.keys() else 0.0,
            grid_resistance=row["grid_resistance"] if "grid_resistance" in row.keys() else 0.0,
            breakout_cooldown_candles=(
                row["breakout_cooldown_candles"]
                if "breakout_cooldown_candles" in row.keys()
                else 0
            ),
            updated_at=row["updated_at"],
        )

    def save_state(self, state: BotState):
        state.touch()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO bot_state (
                    operation_code, take_profit_index, last_trade_decision,
                    last_buy_price, last_sell_price, actual_trade_position,
                    active_mode, grid_support, grid_resistance,
                    breakout_cooldown_candles, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(operation_code) DO UPDATE SET
                    take_profit_index = excluded.take_profit_index,
                    last_trade_decision = excluded.last_trade_decision,
                    last_buy_price = excluded.last_buy_price,
                    last_sell_price = excluded.last_sell_price,
                    actual_trade_position = excluded.actual_trade_position,
                    active_mode = excluded.active_mode,
                    grid_support = excluded.grid_support,
                    grid_resistance = excluded.grid_resistance,
                    breakout_cooldown_candles = excluded.breakout_cooldown_candles,
                    updated_at = excluded.updated_at
                """,
                (
                    state.operation_code,
                    state.take_profit_index,
                    None if state.last_trade_decision is None else int(state.last_trade_decision),
                    state.last_buy_price,
                    state.last_sell_price,
                    int(state.actual_trade_position),
                    state.active_mode,
                    state.grid_support,
                    state.grid_resistance,
                    state.breakout_cooldown_candles,
                    state.updated_at,
                ),
            )

    def log_order(self, operation_code: str, order: dict):
        fills = order.get("fills") or [{}]
        price = float(fills[0].get("price", order.get("price", 0) or 0))
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders_log (
                    operation_code, order_id, side, order_type, status,
                    quantity, price, total_quote, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    operation_code,
                    order.get("orderId"),
                    order.get("side"),
                    order.get("type"),
                    order.get("status"),
                    float(order.get("executedQty", 0) or 0),
                    price,
                    float(order.get("cummulativeQuoteQty", 0) or 0),
                    json.dumps(order),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )

    def reconcile(
        self,
        local: BotState,
        position_open: bool,
        last_buy_price: float,
        last_sell_price: float,
    ) -> BotState:
        """Exchange state wins on conflicts."""
        local.actual_trade_position = position_open
        if last_buy_price > 0:
            local.last_buy_price = last_buy_price
        if last_sell_price > 0:
            local.last_sell_price = last_sell_price
        if not position_open:
            local.take_profit_index = 0
        local.touch()
        self.save_state(local)
        return local
