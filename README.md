# TraderBot
### Robô de Negociação Automatizada para Binance

TraderBot é um robô de negociação automatizada desenvolvido em Python para operar na Binance Spot com configuração versionada, dashboard web, persistência de estado, guardrails de risco, detecção de regime de mercado, grid spot em canal lateral e suporte a testnet.

## Funcionalidades

* **Negociação automatizada** com estratégias plugáveis e fallback
* **Estratégia principal `atr_trend`**: trailing stop ATR + filtro SMA200 em candles 4h
* **Detector de regime** (lateral / tendência / zona cinza) com roteamento automático
* **Grid spot** em mercado lateral, dentro de canal de suporte/resistência válido
* **Breakout detector** para reativar `atr_trend` após rompimento com volume
* **Multi-asset**: uma thread por ativo (ex.: BTC + ETH), com `thread_lock` opcional
* **Configuração unificada** via `config/trading.yaml` + dashboard Flask
* **Testnet e mainnet** controlados por `TRADING_ENV` no `.env`
* **Persistência de estado** em SQLite (`data/traderbot.db`) com modo ativo (`trend` / `grid`)
* **Guardrails de risco**: min notional, limites diários, circuit breaker, limites de grid
* **Cliente Binance resiliente**: sync de relógio, retry em conexões mortas, `recvWindow` ampliado
* **Backtesting** com taxas e slippage estimados
* **Logs estruturados** em JSON (`src/logs/trading_bot.json.log`) com rotação automática

## Pré-requisitos

* Python 3.10+
* Conta Binance com API Spot habilitada
* Para testes iniciais: [Binance Spot Testnet](https://testnet.binance.vision/)

## Instalação

```bash
git clone <URL_DO_SEU_REPOSITÓRIO>
cd TraderBot
pip install -r requirements.txt
```

## Configuração

### 1. Variáveis de ambiente (`.env`)

Copie `.env.example` para `.env`:

```bash
BINANCE_API_KEY="sua_api_key"
BINANCE_SECRET_KEY="sua_secret_key"
TRADING_ENV=testnet
LOG_LEVEL=INFO
TRADING_CONFIG=config/trading.yaml
```

`TRADING_ENV` deve coincidir com `environment` em `config/trading.yaml` (`testnet` ou `mainnet`).

### 2. Configuração de trading (`config/trading.yaml`)

Exemplo completo com as seções atuais:

```yaml
environment: mainnet
thread_lock: true

strategy:
  main: atr_trend
  main_args:
    atr_period: 14
    atr_multiplier: 2.5
    trend_sma_period: 200
  fallback: moving_average
  fallback_args:
    fast_window: 21
    slow_window: 55
  fallback_enabled: true

risk:
  acceptable_loss_pct: 1.5
  stop_loss_pct: 2.0
  take_profit:
    - at: 5
      amount: 30
    - at: 10
      amount: 40
    - at: 20
      amount: 30
  max_daily_loss_usdt: 50.0
  max_trades_per_day: 5
  max_open_orders: 3
  max_grid_trades_per_day: 20

timing:
  candle_period: 4h
  tempo_entre_trades: 3600      # segundos entre ciclos (ex.: 3600 = 1h)
  delay_entre_ordens: 7200

assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0
    traded_percentage: 10
    breakout_price: 67000
  - stock_code: ETH
    operation_code: ETHUSDT
    traded_quantity: 0
    traded_percentage: 10
    breakout_price: 2000

operation:
  cancel_orders_on_shutdown: false
  circuit_breaker_errors: 5
  circuit_breaker_pause_seconds: 300

alerts:
  enabled: false
  webhook_url: ""

regime:
  enabled: true
  adx_period: 14
  adx_lateral_threshold: 20
  adx_trend_threshold: 25
  rsi_low: 30
  rsi_high: 70
  ema_fast: 20
  ema_slow: 50
  ema_compression_pct: 0.5
  range_lookback: 60
  min_touches: 3
  min_lateral_signals: 3
  action_in_lateral: grid       # pause | grid

grid:
  enabled: true
  levels: 6
  capital_pct: 30
  min_channel_width_pct: 1.5
  max_channel_width_pct: 8.0
  min_profit_per_level_pct: 0.35
  max_open_orders: 10

breakout:
  enabled: true
  adx_min: 25
  adx_rising_bars: 2
  volume_multiplier: 1.5
  require_bullish_candle: true
  cooldown_candles: 3
  reentry_adx_max: 22
```

Estratégias disponíveis: `atr_trend`, `weapon_candle`, `moving_average`, `moving_average_antecipation`, `vortex`, `rsi`, `ma_rsi_volume`, `ut_bot_alerts`.

## Estratégia recomendada: ATR Trend 4h

A configuração padrão usa **trend following com trailing stop ATR + filtro SMA200** em candles de 4h:

```yaml
strategy:
  main: atr_trend
  main_args:
    atr_period: 14
    atr_multiplier: 2.5
    trend_sma_period: 200
timing:
  candle_period: 4h
  tempo_entre_trades: 3600
```

### Validar antes de operar

1. Comparar estratégias (retorno, drawdown, trades):

```bash
PYTHONPATH=src python src/backtests_compare.py
```

2. Rodar testes unitários:

```bash
PYTHONPATH=src pytest tests/ -q
```

3. Operar na testnet por 48h e revisar `src/logs/trading_bot.json.log`

Resultados do backtest comparativo são exportados para `data/backtest_compare_4h.csv`.

## Detector de regime e roteamento

A cada ciclo o `RegimeDetector` calcula um score (0–4) com base em quatro sinais:

| Sinal | Condição |
|-------|----------|
| ADX baixo | `ADX(14) < adx_lateral_threshold` (padrão 20) |
| RSI neutro | `rsi_low <= RSI <= rsi_high` |
| EMAs coladas | `\|EMA20 - EMA50\| / preço < ema_compression_pct` |
| Range S/R | ≥ `min_touches` toques no suporte e na resistência (`range_lookback` candles) |

**Regimes:**

| Regime | Critério | Ação padrão |
|--------|----------|-------------|
| `LATERAL` | score ≥ `min_lateral_signals` (padrão 3) | grid (se canal válido) ou pause |
| `TREND` | ADX > `adx_trend_threshold` e score ≤ 1 | `atr_trend` |
| `GRAY` | demais casos | pause |

**Grid spot** (`action_in_lateral: grid`) só ativa quando:

* regime é `LATERAL`
* suporte/resistência detectados com `range_bound: true`
* largura do canal entre `min_channel_width_pct` e `max_channel_width_pct`
* sem cooldown de breakout ativo (ADX ainda alto após rompimento)

O grid coloca ordens limit de compra abaixo do preço e venda acima, usando `capital_pct` do saldo em USDT, respeitando `max_grid_trades_per_day` e `max_open_orders`.

**Breakout** reativa `atr_trend` quando:

* ADX ≥ `adx_min` e subindo por `adx_rising_bars` candles
* preço fecha acima de `breakout_price` (por ativo)
* volume ≥ `volume_multiplier` × média (`volume_sma_period`)
* candle de alta (se `require_bullish_candle: true`)

Após breakout confirmado, o bot cancela ordens do grid, define `active_mode: trend` e opera `atr_trend`. O grid só volta após `cooldown_candles` e com ADX ≤ `reentry_adx_max`.

Stop loss e take profit **continuam ativos** em todos os modos.

### Eventos de log (JSON)

| `event` | Descrição |
|---------|-----------|
| `regime_detected` | Regime, score, ADX, RSI, sinais e ação resolvida — **todo ciclo** |
| `regime_pause` | Estratégia pausada (GRAY ou LATERAL sem grid válido) |
| `grid_cycle` | Ciclo de sincronização do grid |
| `regime_resume_breakout` | Breakout confirmado; retorno ao `atr_trend` |
| `loop_error` | Erro não tratado no loop do ativo |

## Execução

```bash
./run.sh
# ou
PYTHONPATH=src python src/main.py
```

Em background:

```bash
PYTHONUNBUFFERED=1 nohup ./run.sh >> src/logs/trading_bot.log 2>&1 &
```

O bot inicia uma thread por ativo configurado. Com `thread_lock: true`, os ciclos são serializados para evitar concorrência nas chamadas à API.

**Importante:** rode apenas **uma instância** do bot por vez. Múltiplos processos `src/main.py` duplicam chamadas à API e geram logs conflitantes.

### Dashboard web (opcional)

```bash
PYTHONPATH=src python src/app/app.py
```

Acesse `http://localhost:5000`. Alterações no dashboard gravam em `config/trading.yaml`. **Reinicie o bot** após salvar.

### Docker

```bash
docker compose up -d
```

Serviços: `bot` (trading loop) e `dashboard` (porta 5000).

### Backtests

Comparação recomendada (4 estratégias, 4h, ~180 dias):

```bash
PYTHONPATH=src python src/backtests_compare.py
```

Backtests legado de todas as estratégias:

```bash
PYTHONPATH=src python src/backtests.py
```

## Cliente Binance (`BinanceClient`)

Extensão do `python-binance` com melhorias de produção:

* **Sync de relógio** com offset local vs servidor Binance
* **Re-sync automático** em erro `-1021` (timestamp fora da janela)
* **`recvWindow: 10000`** ms em requisições assinadas
* **Retry em conexões mortas** (`RemoteDisconnected`) com reset da sessão HTTP
* **`HTTPAdapter`** com retry para erros de conexão e status 429/5xx
* **Intervalo de re-sync**: 5 min (`DEFAULT_SYNC_INTERVAL`), reduzindo chamadas desnecessárias entre ciclos longos

Warnings esporádicos `Retrying ... RemoteDisconnected` do urllib3 são normais — indicam retry automático bem-sucedido, não falha do bot.

## Testes

```bash
PYTHONPATH=src pytest tests/ -q
```

Suíte atual cobre: `atr_trend`, `regime_detector`, `grid_spot`, `breakout_detector`, `trading_engine` (roteamento), `binance_client`, `risk_manager`, `state_store`, `order_executor`, `config`.

## Checklist: Testnet → Mainnet

1. Criar chaves na **Binance Spot Testnet** (não reutilizar chaves de produção)
2. Definir `TRADING_ENV=testnet` no `.env` e `environment: testnet` no YAML
3. Validar `config/trading.yaml` com quantidades pequenas
4. Rodar o bot por **48–72 horas** na testnet e revisar logs em `src/logs/`
5. Confirmar reconciliação de estado após restart (`data/traderbot.db`)
6. Verificar `regime_detected`, stop loss, take profit e bloqueios de risco nos logs JSON
7. Rodar `pytest tests/` sem falhas
8. Trocar para chaves **mainnet** e `TRADING_ENV=mainnet`
9. Reduzir exposição inicial (`traded_percentage`) e monitorar o primeiro dia manualmente

## Arquitetura

```
src/main.py
  └── thread por ativo → BinanceTraderBot (facade)
        └── TradingEngine
              ├── MarketDataService
              ├── OrderExecutor
              ├── RiskManager
              ├── StrategyRunner (atr_trend + fallback)
              ├── RegimeDetector
              ├── GridSpotManager
              ├── BreakoutDetector
              ├── regime_router (resolve_regime_action)
              └── StateStore (SQLite)
        └── BinanceClient (sync, retry, recvWindow)
```

**Persistência (`BotState`):** `active_mode`, `grid_support`, `grid_resistance`, `breakout_cooldown_candles`, posição, take profit index e preços de referência — sobrevivem a restarts.

## Termos de Uso

Este robô é fornecido "como está". O uso é de sua total responsabilidade. Negocie com responsabilidade.

Licença: [GNU Affero General Public License](./LICENSE).

## Autores

* Desenvolvido inicialmente por Gabriel Freitas
* Fork em 05/02/2025 por Adriano Tavares
