# TraderBot
### Robô de Negociação Automatizada para Binance

TraderBot é um robô de negociação automatizada desenvolvido em Python para operar na Binance Spot com configuração versionada, dashboard web, persistência de estado, guardrails de risco e suporte a testnet.

## Funcionalidades

* **Negociação automatizada** com estratégias plugáveis e fallback
* **Configuração unificada** via `config/trading.yaml` + dashboard Flask
* **Testnet e mainnet** controlados por `TRADING_ENV`
* **Persistência de estado** em SQLite (`data/traderbot.db`)
* **Guardrails de risco**: min notional, limites diários, circuit breaker
* **Backtesting** com taxas e slippage estimados
* **Logs estruturados** em JSON com rotação automática

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

### 2. Configuração de trading (`config/trading.yaml`)

Edite ativos, estratégias, risco e tempos. Exemplo:

```yaml
environment: testnet
strategy:
  main: atr_trend
  fallback: moving_average
  fallback_enabled: true
assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0
    traded_percentage: 10
timing:
  candle_period: 4h
risk:
  stop_loss_pct: 2.0
  max_daily_loss_usdt: 50
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
  fallback: moving_average
  fallback_args:
    fast_window: 21
    slow_window: 55
timing:
  candle_period: 4h
```

### Validar antes de operar

1. Comparar estratégias (retorno, drawdown, trades):

```bash
PYTHONPATH=src python src/backtests_compare.py
```

2. Rodar testes unitários:

```bash
PYTHONPATH=src pytest tests/test_atr_trend.py -q
```

3. Operar na testnet por 48h e revisar `src/logs/trading_bot.json.log`

Resultados do backtest comparativo são exportados para `data/backtest_compare_4h.csv`.

## Detector de regime (lateral vs tendência)

O bot avalia o mercado a cada ciclo com um score baseado no checklist de lateralização:

| Sinal | Condição |
|-------|----------|
| ADX baixo | `ADX(14) < 20` |
| RSI neutro | `40 <= RSI <= 60` |
| EMAs coladas | `\|EMA20 - EMA50\| / preço < 0.5%` |
| Range S/R | ≥3 toques no suporte e na resistência (60 candles) |

**Regimes:**
- `LATERAL` (score ≥ 3): ativa **grid spot** no canal (com `action_in_lateral: grid`)
- `TREND` (ADX > 25 e score ≤ 1): opera `atr_trend` normalmente
- `GRAY`: pausa conservadora

**Breakout:** quando ADX sobe, preço rompe `breakout_price` (ex.: US$ 67k) e volume confirma, o bot cancela o grid e reativa `atr_trend` automaticamente.

Stop loss e take profit **continuam ativos** em todos os modos.

Configuração em `config/trading.yaml`:

```yaml
regime:
  enabled: true
  min_lateral_signals: 3
  action_in_lateral: grid

grid:
  enabled: true
  levels: 6
  capital_pct: 30

breakout:
  enabled: true
  adx_min: 25
  volume_multiplier: 1.5
  cooldown_candles: 3

assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    breakout_price: 67000
```

Logs: `event: regime_detected`, `event: grid_cycle`, `event: regime_resume_breakout`, `event: regime_pause`

### 3. Dashboard web (opcional)

```bash
PYTHONPATH=src python src/app/app.py
```

Acesse `http://localhost:5000`. Alterações no dashboard gravam em `config/trading.yaml`. **Reinicie o bot** após salvar.

## Execução

```bash
./run.sh
# ou
PYTHONPATH=src python src/main.py
```

### Docker

```bash
docker compose up -d
```

Serviços: `bot` (trading loop) e `dashboard` (porta 5000).

### Backtests

Comparacao recomendada (4 estrategias, 4h, ~180 dias):

```bash
PYTHONPATH=src python src/backtests_compare.py
```

Backtests legado de todas as estrategias:

```bash
PYTHONPATH=src python src/backtests.py
```

## Testes

```bash
PYTHONPATH=src pytest tests/ -q
```

## Checklist: Testnet → Mainnet

1. Criar chaves na **Binance Spot Testnet** (não reutilizar chaves de produção)
2. Definir `TRADING_ENV=testnet` no `.env`
3. Validar `config/trading.yaml` com quantidades pequenas
4. Rodar o bot por **48–72 horas** na testnet e revisar logs em `src/logs/`
5. Confirmar reconciliação de estado após restart (`data/traderbot.db`)
6. Verificar stop loss, take profit e bloqueios de risco nos logs JSON
7. Rodar `pytest tests/` sem falhas
8. Trocar para chaves **mainnet** e `TRADING_ENV=mainnet`
9. Reduzir exposição inicial e monitorar o primeiro dia manualmente

## Arquitetura

```
src/main.py → BinanceTraderBot (facade) → TradingEngine
                ├── MarketDataService
                ├── OrderExecutor
                ├── RiskManager
                ├── StrategyRunner
                └── StateStore (SQLite)
```

## Termos de Uso

Este robô é fornecido "como está". O uso é de sua total responsabilidade. Negocie com responsabilidade.

Licença: [GNU Affero General Public License](./LICENSE).

## Autores

* Desenvolvido inicialmente por Gabriel Freitas
* Fork em 05/02/2025 por Adriano Tavares
