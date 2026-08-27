# Como usar o TraderBot

Guia prático de operação. Detalhes de arquitetura, schema do YAML e API estão no [README](./README.md).

O TraderBot tem **dois processos independentes**. O dashboard não liga o bot.

| Processo | Comando | Função |
|----------|---------|--------|
| Bot | `./run.sh` | Coloca e gerencia ordens na Binance Spot |
| Dashboard | `PYTHONPATH=src python src/app/app.py` | Acompanhar, lucro e editar config no navegador |

Os dois compartilham `.env`, `config/trading.yaml` e `data/traderbot.db`.

## 1. Preparar o ambiente

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Edite o `.env` (nunca commite este arquivo):

1. Cole `BINANCE_API_KEY` e `BINANCE_SECRET_KEY` da [Spot Testnet](https://testnet.binance.vision/) para o primeiro uso.
2. Defina `TRADING_ENV=testnet`.
3. Alinhe `environment: testnet` em `config/trading.yaml`. Se os dois divergirem, **o `.env` prevalece**.

Gere a senha do dashboard (recomendado mesmo em localhost):

```bash
python src/app/hash_password.py
```

Cole a linha `DASHBOARD_PASSWORD_HASH='...'` no `.env`. Sem esse hash, o bind fora de `127.0.0.1` é recusado.

`FLASK_TOKEN` é só para scripts (`curl` com header `X-TraderBot-Token`). Ele **não** faz login no navegador.

## 2. Ligar

Dois terminais, na raiz do repositório, com o venv ativo:

```bash
# Terminal 1 — bot
./run.sh

# Terminal 2 — dashboard
PYTHONPATH=src python src/app/app.py
```

Abra [http://127.0.0.1:5000](http://127.0.0.1:5000). Com senha configurada, entre em `/login`.

Rode **uma única instância** do bot. Uma segunda `src/main.py` é bloqueada pelo `ProcessLock` e, se o lock falhar, duplicaria ordens.

Para os dois juntos via Docker:

```bash
python src/app/hash_password.py    # obrigatório no compose
docker compose up -d
```

O dashboard fica em `127.0.0.1:5000`. Healthcheck público: `GET /healthz`.

## 3. Dashboard

Barra superior: **Tracking** · **Profit** · **Config**, badge de ambiente (testnet/mainnet) e o seletor de aparência (sol = claro, lua = escuro). A escolha fica no navegador.

### Tracking (`/`)

Acompanha o ciclo ao vivo: saldo, P&L, chips por ativo, gráfico (candles, regime, TP/SL) e a lista de eventos.

- **Todos** mostra o gráfico agregado do portfólio; cada ticker mostra o ativo.
- **1d / 1w / 1m** só mudam o zoom do gráfico já carregado.
- **Atualizar** recarrega logs e portfólio. Os gráficos renovam sozinhos com menos frequência (candles 4h mudam pouco).

Eventos típicos: variação do candle, regime detectado, pause, ciclo de grid, breakout, erro de loop.

### Profit (`/profit`)

P&L **realizado** (fechamentos BUY/SELL sincronizados da Binance) e **posição aberta**. Não é o P&L não realizado do gráfico de Tracking.

### Config (`/config`)

Formulário gerado a partir do schema de `config/trading.yaml`.

1. Altere os campos.
2. **Verificar impacto** classifica a mudança:
   - *aplica no próximo ciclo* — risco, delays, args da estratégia, grid, regime, alertas;
   - *exige restart do bot* — `environment`, `strategy.main`, par do ativo, `timing.candle_period`.
3. **Salvar** pede confirmação em campos sensíveis (stop, perda diária, tamanho da ordem, ambiente) e grava backup em `config/history/` (últimas 20 versões).
4. **Histórico de versões** restaura um YAML anterior.

O painel no topo mostra se o bot está rodando, o ambiente efetivo e se há restart pendente.

## 4. O que o bot faz a cada ciclo

Em cada ativo, no intervalo de `tempo_entre_trades`:

1. Lê o candle (`candle_period`, padrão 4h).
2. Classifica o **regime**: tendência, lateral ou indefinido (zona cinza).
3. Roteia:
   - tendência → estratégia principal (`atr_trend` por padrão);
   - lateral → grid spot se o canal for válido, senão pausa;
   - cinza → pausa.
4. Stop loss e take profit continuam ativos em todos os modos.

Tamanho da ordem: `traded_quantity` > 0 usa quantidade fixa; `0` usa `traded_percentage` do saldo disponível. Há limite de notional mínimo da Binance, teto diário de perda, máximo de trades e circuit breaker.

## 5. Antes de ir para mainnet

1. `PYTHONPATH=src pytest tests/ -q`
2. `PYTHONPATH=src python src/backtests_compare.py` — resultado em `data/backtest_compare_4h.csv` (o backtest **não** simula regime, grid nem limites diários).
3. Rodar **48–72 h na testnet** e revisar `src/logs/trading_bot.json.log`.
4. Só então: chaves **mainnet**, `TRADING_ENV=mainnet` **e** `environment: mainnet` no YAML, exposição baixa (`traded_percentage`) no primeiro dia.

Não reutilize chaves de produção na testnet. Não afrouxe `stop_loss_pct`, `max_daily_loss_usdt`, `max_trades_per_day` ou percentuais sem revisar o impacto.

## 6. Parar e reiniciar

- Dashboard: `Ctrl+C` no processo `src/app/app.py`.
- Bot: `Ctrl+C` no `./run.sh`. Com `cancel_orders_on_shutdown: true`, o bot tenta cancelar ordens abertas ao sair.
- Depois de uma mudança **hard** no YAML, reinicie só o bot (`./run.sh`). O dashboard não precisa.

O estado (modo `trend`/`grid`, posição, canal) fica em `data/traderbot.db` e sobrevive ao restart.

## 7. Problemas comuns

| Sintoma | O que fazer |
|---------|-------------|
| `No module named 'waitress'` | Ative o venv e `pip install -r requirements.txt` |
| Dashboard recusa subir em `0.0.0.0` | Defina `DASHBOARD_PASSWORD_HASH` |
| Páginas abrem, API dá 401 | Faça login; `FLASK_TOKEN` não autentica o navegador |
| Bot recusa a segunda instância | Já existe um `src/main.py`; não suba outro |
| Badge mainnet com YAML testnet (ou o inverso) | Alinhe `TRADING_ENV` e `environment` |
| Config salva mas o par novo não opera | Identidade do ativo exige **restart do bot** |
| Eventos vazios no Tracking | O bot ainda não rodou um ciclo; confira o terminal do `./run.sh` |

Logs JSON: `src/logs/trading_bot.json.log`. Warnings `RemoteDisconnected` do urllib3 costumam ser retry automático, não falha permanente.

## Responsabilidade

O robô opera com dinheiro real na mainnet. Ordens, perdas e chaves de API são de quem opera. Comece na testnet. Licença: [AGPL](./LICENSE).
