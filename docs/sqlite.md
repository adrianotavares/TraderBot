# SQLite — inspeção (somente leitura)

O bot (`src/main.py`) e o dashboard (`src/app/app.py`) compartilham o mesmo arquivo:

```
data/traderbot.db
```

Caminho relativo à raiz do repositório. Não precisa de `PYTHONPATH`. Não suba uma segunda instância de `src/main.py` só para olhar o banco (`ProcessLock`).

Não commitar: `.env`, `data/traderbot.db`, `data/.flask_secret`, logs. Não imprimir `BINANCE_*`, `FLASK_SECRET_KEY` nem hashes de senha.

## Abrir

Na raiz do repo, prefira **somente leitura** (evita lock de escrita enquanto o bot está rodando):

```bash
sqlite3 "file:data/traderbot.db?mode=ro"
```

Alternativa (sqlite3 recente):

```bash
sqlite3 -readonly data/traderbot.db
```

Consulta única sem entrar no prompt:

```bash
sqlite3 "file:data/traderbot.db?mode=ro" "SELECT operation_code, active_mode FROM bot_state;"
```

GUI opcional: DB Browser for SQLite ou extensão SQLite do VS Code — abrir o arquivo em modo leitura, se a ferramenta oferecer. O CLI acima é o caminho padrão.

Se for experimentar `UPDATE`/`DELETE`, **copie** o `.db` primeiro e mexa só na cópia.

## Descobrir o schema

No prompt do `sqlite3`:

```sql
.tables
.schema
PRAGMA table_info(bot_state);
.headers on
.mode column
```

## Não faça (banco live)

No `data/traderbot.db` de produção:

- **Nunca** `UPDATE`, `DELETE`, `INSERT`, `DROP`, `ALTER`
- **Nunca** `.backup` por cima do arquivo live, nem abrir com ferramenta que grave WAL/journal sem necessidade
- **Nunca** `SELECT *` em `orders_log.raw_json` para colar em tickets (eco da exchange; use as colunas nominais)

Só `SELECT`. Circuit breaker, limites diários e estado de posição passam por este banco.

---

## Tabelas

### `bot_state`

Estado por ativo (`operation_code` = PK). Sobrevive ao restart. `actual_trade_position` é 0/1; `active_mode` é `trend` ou `grid`.

```sql
SELECT operation_code, active_mode, actual_trade_position,
       last_buy_price, last_sell_price, grid_support, grid_resistance,
       take_profit_index, stop_loss_peak_price, updated_at
FROM bot_state;

SELECT * FROM bot_state WHERE operation_code = 'BTCUSDT';
```

### `orders_log`

Ecos da exchange: lado, tipo, status, quantidade, preço. Não selecione `raw_json` no dia a dia.

```sql
SELECT id, operation_code, order_id, side, order_type, status,
       quantity, price, total_quote, created_at
FROM orders_log
ORDER BY created_at DESC
LIMIT 20;

SELECT operation_code, side, status, quantity, price, created_at
FROM orders_log
WHERE operation_code = 'BTCUSDT'
ORDER BY created_at DESC
LIMIT 10;
```

### `trade_outcomes`

P&L realizado/reconstruído. Único em `(kind, operation_code, occurred_at)`. `source` é `live` ou rebuild.

```sql
SELECT kind, operation_code, pnl_usd, pnl_pct, source, filled, occurred_at
FROM trade_outcomes
ORDER BY occurred_at DESC
LIMIT 20;

SELECT operation_code, SUM(pnl_usd) AS pnl
FROM trade_outcomes
WHERE filled = 1
GROUP BY operation_code;
```

### `daily_risk`

Contadores do dia (UTC) usados pelos caps e pelo circuit breaker. PK `(day_key, operation_code)`.

```sql
SELECT day_key, operation_code, trades, grid_trades, loss_usdt
FROM daily_risk
ORDER BY day_key DESC
LIMIT 8;

SELECT * FROM daily_risk WHERE operation_code = 'BTCUSDT' ORDER BY day_key DESC LIMIT 5;
```

### `regime_history`

Regime por vela. PK `(operation_code, candle_time)` — `candle_time` é Unix epoch.

```sql
SELECT operation_code, regime, score, action,
       datetime(candle_time, 'unixepoch') AS candle_utc
FROM regime_history
ORDER BY candle_time DESC
LIMIT 20;

SELECT regime, score, adx, rsi, action, datetime(candle_time, 'unixepoch')
FROM regime_history
WHERE operation_code = 'BTCUSDT'
ORDER BY candle_time DESC
LIMIT 15;
```

### `cycle_heartbeat`

Heartbeat do ciclo (countdown do dashboard): fase, próximo ciclo, motivo do sleep.

```sql
SELECT operation_code, phase, sleep_seconds, next_cycle_at, sleep_reason, updated_at
FROM cycle_heartbeat;

SELECT * FROM cycle_heartbeat WHERE operation_code = 'BTCUSDT';
```

### `app_meta`

Chave/valor interno (ex.: `action_hold`, `operator_hold`, marcadores de rebuild). Valores são flags, não secrets — ainda assim não misture com `.env`.

```sql
SELECT key, value FROM app_meta;
```

---

## Receita rápida

Listar tabelas, contar linhas, espiar estado / regime / ordens:

```bash
sqlite3 "file:data/traderbot.db?mode=ro" <<'SQL'
.headers on
.mode column
.tables

SELECT 'bot_state' AS t, COUNT(*) FROM bot_state
UNION ALL SELECT 'orders_log', COUNT(*) FROM orders_log
UNION ALL SELECT 'trade_outcomes', COUNT(*) FROM trade_outcomes
UNION ALL SELECT 'daily_risk', COUNT(*) FROM daily_risk
UNION ALL SELECT 'regime_history', COUNT(*) FROM regime_history
UNION ALL SELECT 'cycle_heartbeat', COUNT(*) FROM cycle_heartbeat
UNION ALL SELECT 'app_meta', COUNT(*) FROM app_meta;

SELECT operation_code, active_mode, actual_trade_position, updated_at FROM bot_state;

SELECT operation_code, regime, score, action, datetime(candle_time,'unixepoch')
FROM regime_history ORDER BY candle_time DESC LIMIT 10;

SELECT operation_code, side, status, quantity, price, created_at
FROM orders_log ORDER BY created_at DESC LIMIT 10;
SQL
```

Sair do prompt: `.quit`.
