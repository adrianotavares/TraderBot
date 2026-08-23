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
* **Dashboard servido por WSGI de produção** (waitress), com login por senha e sessão assinada
* **Editor de configuração completo**: formulário gerado do schema, preview de impacto e histórico de versões
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

# Dashboard
FLASK_HOST=127.0.0.1
FLASK_PORT=5000
WSGI_THREADS=8
DASHBOARD_PASSWORD_HASH=
FLASK_TOKEN=
FLASK_SECRET_KEY=
FLASK_COOKIE_SECURE=0
```

`TRADING_ENV` deve coincidir com `environment` em `config/trading.yaml` (`testnet` ou `mainnet`). Quando definido, ele **sobrepõe** o valor do YAML — o dashboard sinaliza esse conflito na página de Config.

Variáveis do dashboard estão detalhadas em [Dashboard web](#dashboard-web). Use `TRADERBOT_ENV_FILE` para apontar para outro arquivo `.env`.

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
| `asset_variation` | Variação % do candle atual (ex.: `BTC subiu 1.23% nas últimas 4h - 67234.50 usd`) — **todo ciclo** |
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

### Dashboard web

```bash
PYTHONPATH=src python src/app/app.py
```

O dashboard roda sobre **waitress**, um servidor WSGI de produção — não há mais o aviso `This is a development server`. São páginas de Tracking (`/`), Profit (`/profit`) e Config (`/config`), mais `/healthz` para healthcheck.

Deliberadamente é **um único processo** com um pool de threads (`WSGI_THREADS`, padrão 8). As rotas mantêm cache de portfólio, cache de histórico e um cliente Binance reaproveitado no próprio processo; múltiplos workers duplicariam esse estado, abririam conexões redundantes e fariam escritas concorrentes no SQLite. Para iterar localmente com reload automático, use `FLASK_DEV_SERVER=1`.

O bot continua sendo um processo separado (`src/main.py`). O dashboard não inicia threads de negociação.

#### Autenticação

Gere o hash da senha e coloque no `.env`:

```bash
python src/app/hash_password.py
```

Com `DASHBOARD_PASSWORD_HASH` definido, **todas** as páginas e endpoints exigem sessão autenticada; há tela de login em `/login`, logout na barra superior, sessão de 12h em cookie assinado (`HttpOnly`, `SameSite=Lax`), proteção CSRF em requisições que alteram estado e limite de 5 tentativas de login por IP a cada 5 minutos. Defina `FLASK_COOKIE_SECURE=1` quando estiver atrás de HTTPS.

`FLASK_TOKEN` continua disponível para scripts, enviado no header `X-TraderBot-Token` ou como `Authorization: Bearer`. O token **não** é mais aceito via query string (`?token=`) nem exposto no HTML das páginas.

Sem `DASHBOARD_PASSWORD_HASH`, o comportamento antigo é mantido para uso local: só os endpoints de API e de config são protegidos, e apenas se `FLASK_TOKEN` estiver definido.

**Um bind fora de `127.0.0.1` exige `DASHBOARD_PASSWORD_HASH` e aborta a inicialização sem ele.** `FLASK_TOKEN` sozinho não serve: um token compartilhado não consegue autenticar um navegador sem ser embutido na página — era exatamente assim que ele vazava para qualquer visitante anônimo. Se você definir `FLASK_TOKEN` sem senha, as páginas carregam mas não conseguem ler a API, e um aviso é registrado no log ao subir.

A chave de assinatura da sessão vem de `FLASK_SECRET_KEY`; se ausente, é gerada e persistida em `data/.flask_secret` com permissão `600`.

#### Página de Config

O formulário é gerado a partir do schema Pydantic, então expõe todas as seções do YAML (`strategy`, `risk`, `timing`, `assets`, `regime`, `grid`, `breakout`, `operation`, `alerts`) com rótulo, descrição e limites vindos do próprio modelo. Recursos:

* **Preview de impacto** antes de salvar: "Verificar impacto" faz um dry-run que classifica a mudança em *aplica no próximo ciclo* ou *exige restart do bot*, usando a mesma lógica que o bot usa para recarregar o YAML
* **Erros por campo**, destacados no input em vez de uma mensagem única
* **Histórico de versões**: cada save guarda uma cópia byte a byte do YAML anterior em `config/history/` (últimas 20), preservando comentários que o `yaml.safe_dump` descartaria, com botão de restaurar
* **Confirmação explícita** para campos sensíveis (ambiente, quantidade e percentual negociados, stop loss, perda diária máxima) e para mudanças que exigem restart
* **Painel de status**: se o bot está rodando, ambiente efetivo e sua origem, data do último save e restart pendente
* **Badge TESTNET/MAINNET** fixo na barra superior

Mudanças de `risk`, `timing`, `regime`, `grid`, `breakout`, `alerts` e `operation` são recarregadas pelo bot no próximo ciclo. Troca de par, `environment`, `strategy.main` ou `timing.candle_period` exige **restart do bot** — o dashboard avisa quais.

#### Endpoints da API

| Método | Rota | Descrição |
|--------|------|-----------|
| GET | `/api/config/schema` | Schema do formulário derivado dos modelos Pydantic |
| GET | `/api/config` | Config atual do YAML + origem do `environment` |
| POST | `/api/config/validate` | Dry-run: erros por campo e impacto, sem escrever |
| POST | `/api/config` | Salva após validar, guardando backup |
| GET | `/api/config/history` | Lista os backups disponíveis |
| POST | `/api/config/revert` | Restaura um backup |
| GET | `/api/status` | Estado do bot, do YAML e eventos de reload |
| GET | `/api/portfolio`, `/api/profit`, `/api/logs` | Dados das páginas de Tracking e Profit |
| GET | `/healthz` | Healthcheck, sem autenticação |

### Docker

```bash
docker compose up -d
```

Serviços: `bot` (trading loop) e `dashboard` (porta `127.0.0.1:5000`, com healthcheck em `/healthz`). O serviço `dashboard` faz bind em `0.0.0.0` dentro do container, então exige `DASHBOARD_PASSWORD_HASH` ou `FLASK_TOKEN` no `.env`.

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

Suíte atual cobre: `atr_trend`, `regime_detector`, `grid_spot`, `breakout_detector`, `trading_engine` (roteamento), `binance_client`, `risk_manager`, `state_store`, `order_executor`, `config`, a API de configuração do dashboard (`test_config_api.py`) e a autenticação do dashboard (`test_flask_security.py`).

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
