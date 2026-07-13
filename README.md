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
  main: weapon_candle
  fallback: moving_average
  fallback_enabled: true
assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0.001
risk:
  stop_loss_pct: 0.5
  max_daily_loss_usdt: 100
```

Estratégias disponíveis: `weapon_candle`, `moving_average`, `moving_average_antecipation`, `vortex`, `rsi`, `ma_rsi_volume`, `ut_bot_alerts`.

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
