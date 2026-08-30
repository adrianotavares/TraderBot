# TraderBot — agent notes

Python bot for Binance Spot + Flask dashboard. Read `.cursor/rules/` first. Domain workflows live in `.cursor/skills/`.

## Commands

```bash
./run.sh                                          # bot
PYTHONPATH=src python src/app/app.py              # dashboard → http://127.0.0.1:5000
PYTHONPATH=src pytest tests/ -q
PYTHONPATH=src python src/backtests_compare.py
```

## Layout

- `src/main.py` — bot (one instance; ProcessLock)
- `src/app/` — dashboard (waitress, one process)
- `src/core/trading_engine.py` — cycle
- `src/strategies/` — plug-ins via `registry.py`
- `config/trading.yaml` — Pydantic-validated settings
- `data/traderbot.db` — live state (read-only unless asked)

## MCP

- Context7 (`.cursor/mcp.json`) — docs na versao de `python-binance`, Flask, Pydantic, pandas.

## Skills

- `trading-safety` — secrets, testnet, no live orders
- `add-strategy` — new strategy + tests
- `run-backtest` — compare 4h strategies
- `investigate-live` — logs + SQLite + `/api/status`
- `dashboard-verify` — browser pass on Flask UI
