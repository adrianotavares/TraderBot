# TraderBot
### Robô de Negociação Automatizada para Binance

TraderBot é um robô de negociação automatizada desenvolvido em Python para operar na Binance Spot com configuração versionada, dashboard web, persistência de estado, guardrails de risco, detecção de regime de mercado, grid spot em canal lateral e suporte a testnet.

O **bot** (`src/main.py`) e o **dashboard** (`src/app/app.py`) são processos separados: o primeiro executa as ordens; o segundo monitora logs, P&L e configuração via navegador.

## Funcionalidades

* **Negociação automatizada** com estratégias plugáveis e fallback
* **Estratégia principal `atr_trend`**: trailing stop ATR + filtro SMA200 em candles 4h
* **Detector de regime** (lateral / tendência / zona cinza) com roteamento automático
* **Grid spot** em mercado lateral, dentro de canal de suporte/resistência válido
* **Breakout detector** para reativar `atr_trend` após rompimento com volume
* **Multi-asset**: uma thread por ativo (ex.: BTC + ETH), com `thread_lock` opcional
* **Configuração unificada** via `config/trading.yaml` + dashboard web
* **Dashboard em produção** (waitress): login por senha, sessão assinada e editor completo do YAML
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
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edite o `.env` com suas chaves da Binance. O pacote `waitress` (servidor WSGI do dashboard) vem no `requirements.txt` — sem ele, `python src/app/app.py` falha com `ModuleNotFoundError: No module named 'waitress'`.

## Início rápido

Depois de instalar e configurar o `.env`:

```bash
# 1. Senha do dashboard (recomendado)
python src/app/hash_password.py
# Cole a linha DASHBOARD_PASSWORD_HASH=... gerada no .env

# 2. Bot de trading (terminal 1)
./run.sh

# 3. Dashboard web (terminal 2)
PYTHONPATH=src python src/app/app.py
```

Abra **http://localhost:5000** — Tracking (`/`), Profit (`/profit`), Config (`/config`). Com senha configurada, faça login em `/login`.

| Componente | Comando | URL / porta |
|------------|---------|-------------|
| Bot | `./run.sh` ou `PYTHONPATH=src python src/main.py` | — |
| Dashboard | `PYTHONPATH=src python src/app/app.py` | `http://127.0.0.1:5000` (padrão) |
| Docker (ambos) | `docker compose up -d` | dashboard em `127.0.0.1:5000` |

O dashboard **não** inicia o bot. Para operar de verdade, rode os dois processos (ou use Docker com os serviços `bot` e `dashboard`).

## Configuração

### 1. Variáveis de ambiente (`.env`)

Copie `.env.example` para `.env` e ajuste os valores:

```bash
cp .env.example .env
```

**Trading (obrigatório para operar):**

| Variável | Descrição |
|----------|-----------|
| `BINANCE_API_KEY` | API key Spot |
| `BINANCE_SECRET_KEY` | Secret key Spot |
| `TRADING_ENV` | `testnet` ou `mainnet` — **sobrepõe** `environment` do YAML quando definido |
| `LOG_LEVEL` | `INFO`, `DEBUG`, etc. |
| `TRADING_CONFIG` | Caminho do YAML (padrão: `config/trading.yaml`) |

**Dashboard:**

| Variável | Padrão | Descrição |
|----------|--------|-----------|
| `FLASK_HOST` | `127.0.0.1` | Interface de escuta |
| `FLASK_PORT` | `5000` | Porta HTTP |
| `WSGI_THREADS` | `8` | Threads do waitress (mantenha **um** processo) |
| `FLASK_DEV_SERVER` | `0` | `1` = servidor Flask com reload (só desenvolvimento) |
| `DASHBOARD_PASSWORD_HASH` | — | Hash da senha (`python src/app/hash_password.py`) |
| `FLASK_TOKEN` | — | Token para `curl`/scripts (`X-TraderBot-Token`); opcional |
| `FLASK_SECRET_KEY` | auto | Chave da sessão; se vazia, gravada em `data/.flask_secret` |
| `FLASK_COOKIE_SECURE` | `0` | `1` atrás de HTTPS |

**Outros:**

| Variável | Descrição |
|----------|-----------|
| `TRADERBOT_ENV_FILE` | Caminho alternativo do `.env` (testes ou múltiplos ambientes) |
| `TRADERBOT_LOG_DIR` | Diretório de logs (padrão: `src/logs`) |

`TRADING_ENV` deve coincidir com `environment` em `config/trading.yaml`. Se divergirem, o valor do `.env` prevalece na operação do bot — a página **Config** do dashboard exibe um aviso quando isso acontece.

Detalhes de autenticação e da API do dashboard estão em [Dashboard web](#dashboard-web).

### 2. Configuração de trading (`config/trading.yaml`)

Arquivo principal de parâmetros. Pode ser editado à mão ou pela página **Config** do dashboard (`/config`). Cada save pelo dashboard gera backup em `config/history/` (últimas 20 versões).

Exemplo das seções (valores ilustrativos — confira o arquivo ativo no repositório):

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
    - at: 7
      amount: 100
  max_daily_loss_usdt: 50.0
  max_trades_per_day: 5
  max_open_orders: 3
  max_grid_trades_per_day: 20

timing:
  candle_period: 4h
  tempo_entre_trades: 150
  delay_entre_ordens: 7200

assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0
    traded_percentage: 50
    breakout_price: 78000
  - stock_code: ETH
    operation_code: ETHUSDT
    traded_quantity: 0
    traded_percentage: 50
    breakout_price: 2450

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
  rsi_low: 40
  rsi_high: 60
  ema_fast: 20
  ema_slow: 50
  ema_compression_pct: 0.5
  range_lookback: 60
  min_touches: 3
  min_lateral_signals: 3
  action_in_lateral: grid       # pause | grid | hold_cash

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
  reentry_adx_max: 25
```

**Recarregamento pelo bot:** mudanças em `risk`, `timing`, `regime`, `grid`, `breakout`, `alerts` e `operation` valem no próximo ciclo. Troca de par, `environment`, `strategy.main` ou `timing.candle_period` exige **restart** do processo `src/main.py`.

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
  tempo_entre_trades: 150   # segundos entre ciclos (ajuste conforme o ativo)
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

### Bot de trading

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

Servidor **waitress** (WSGI de produção) em `http://127.0.0.1:5000` por padrão (`FLASK_HOST` / `FLASK_PORT` no `.env`).

| Rota | Descrição |
|------|-----------|
| `/` | Tracking — logs estruturados e portfólio |
| `/profit` | P&L realizado e posições abertas |
| `/config` | Editor completo do YAML |
| `/login` | Autenticação (quando `DASHBOARD_PASSWORD_HASH` está definido) |
| `/healthz` | Healthcheck (sem autenticação) |

**Produção vs desenvolvimento**

* Padrão: waitress, um processo, `WSGI_THREADS` threads (padrão 8). Não use múltiplos workers — o dashboard mantém cache e cliente Binance em memória.
* Desenvolvimento com reload: `FLASK_DEV_SERVER=1 PYTHONPATH=src python src/app/app.py`

**Problemas comuns**

| Erro | Solução |
|------|---------|
| `No module named 'waitress'` | Ative o venv e rode `pip install -r requirements.txt` |
| `DASHBOARD_PASSWORD_HASH is required when FLASK_HOST=0.0.0.0` | Gere o hash com `python src/app/hash_password.py` e defina no `.env` |
| Páginas carregam mas API retorna 401 | Defina `DASHBOARD_PASSWORD_HASH` e faça login — `FLASK_TOKEN` sozinho não autentica o navegador |

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

Regras de recarregamento: ver [Configuração de trading](#2-configuração-de-trading-configtradingyaml). O endpoint legado `POST /update-config` (formato `MAIN_STRATEGY`, etc.) continua funcionando; a UI usa `POST /api/config`.

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

Rotas legadas ainda disponíveis: `GET /get-config`, `POST /update-config`.

Exemplo de chamada autenticada com token (scripts):

```bash
curl -s -H "X-TraderBot-Token: $FLASK_TOKEN" http://127.0.0.1:5000/api/status | jq .
```

### Docker

Antes de subir, defina `DASHBOARD_PASSWORD_HASH` no `.env` (obrigatório para o serviço `dashboard`):

```bash
python src/app/hash_password.py   # copie a linha gerada para o .env
docker compose up -d
```

| Serviço | Função | Porta |
|---------|--------|-------|
| `bot` | Loop de trading (`src/main.py`) | — |
| `dashboard` | Interface web (`src/app/app.py`) | `127.0.0.1:5000` |

O container do dashboard escuta em `0.0.0.0` internamente; o compose exige `DASHBOARD_PASSWORD_HASH` — `FLASK_TOKEN` sozinho **não** libera bind público nem login no navegador. Healthcheck: `GET /healthz`.

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
2. Definir `TRADING_ENV=testnet` no `.env` e `environment: testnet` no YAML (mantenha os dois alinhados)
3. Gerar `DASHBOARD_PASSWORD_HASH` se for expor o dashboard fora de localhost
4. Validar `config/trading.yaml` com quantidades pequenas (ou pela página Config)
5. Rodar o bot por **48–72 horas** na testnet e revisar logs em `src/logs/`
6. Confirmar reconciliação de estado após restart (`data/traderbot.db`)
7. Verificar `regime_detected`, stop loss, take profit e bloqueios de risco nos logs JSON
8. Rodar `pytest tests/` sem falhas
9. Trocar para chaves **mainnet** e `TRADING_ENV=mainnet`
10. Reduzir exposição inicial (`traded_percentage`) e monitorar o primeiro dia manualmente

## Arquitetura

Dois processos independentes compartilham `config/trading.yaml`, `.env` e `data/traderbot.db`:

```
┌─────────────────────────────┐     ┌──────────────────────────────┐
│  src/main.py (bot)          │     │  src/app/app.py (dashboard)  │
│  · thread por ativo         │     │  · waitress (WSGI)           │
│  · SettingsWatch (YAML)     │     │  · sessão + CSRF             │
│  · ProcessLock (1 inst.)    │     │  · Tracking / Profit / Config│
└──────────────┬──────────────┘     └──────────────┬───────────────┘
               └────────────────┬───────────────────┘
                                ▼
              config/trading.yaml · .env · data/traderbot.db
```

**Bot (`src/main.py`):**

```
BinanceTraderBot (facade)
  └── TradingEngine
        ├── MarketDataService · OrderExecutor · RiskManager
        ├── StrategyRunner (atr_trend + fallback)
        ├── RegimeDetector · GridSpotManager · BreakoutDetector
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
