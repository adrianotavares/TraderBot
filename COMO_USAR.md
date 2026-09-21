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

O dashboard fica em `127.0.0.1:5000`. Healthcheck do processo: `GET /healthz`.

## 3. Acesso remoto (Cloudflare Tunnel + Access)

O bot e o dashboard continuam nesta máquina. Um processo à parte (`cloudflared`) abre um túnel de **saída** até a Cloudflare. O celular usa só o navegador — sem app VPN e **sem** abrir a porta 5000 no roteador.

Não mude `FLASK_HOST` para `0.0.0.0` nem o mapeamento `127.0.0.1:5000:5000` do compose. Não coloque `cloudflared` no `docker-compose.yml` (a credencial do túnel não entra no git).

### Nesta máquina

1. Senha do dashboard no `.env` (`python src/app/hash_password.py` → `DASHBOARD_PASSWORD_HASH`).
2. `FLASK_HOST=127.0.0.1`, `FLASK_PORT=5000`, `FLASK_COOKIE_SECURE=1`.
3. Dashboard no ar em `http://127.0.0.1:5000`.
4. Túnel nomeado `traderbot` apontando **somente** para `http://127.0.0.1:5000`, hostname `bot.domogeo.xyz`, serviço systemd de usuário (`~/.config/systemd/user/cloudflared-traderbot.service`). Credenciais em `~/.cloudflared/`, fora do repositório. Binário: `~/.local/bin/cloudflared`.

Com `FLASK_COOKIE_SECURE=1`, o login em `http://127.0.0.1:5000` não mantém a sessão. Use o hostname HTTPS também em casa.

### Na Cloudflare

1. Domínio na conta Cloudflare (registrar da própria Cloudflare evita trocar nameserver).
2. Zero Trust, plano Free. Identity **One-time PIN**.
3. Aplicação Self-hosted no hostname do túnel (`bot.domogeo.xyz`).
4. Policy Allow → Include **Emails** = só `adriano.tavares@gmail.com` (não o domínio `@gmail.com` inteiro).
5. Access no hostname inteiro (inclui `/healthz`).

No celular (de preferência 4G): PIN no e-mail → `/login` do TraderBot → Tracking / Profit / Config.

Se o PC dormir ou o `cloudflared` cair, o site devolve 502 e o bot também parou. Não suba um segundo `src/main.py` em outro host.

## 4. Dashboard

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

## 5. O que o bot faz a cada ciclo

Em cada ativo, no intervalo de `tempo_entre_trades`:

1. Lê o candle (`candle_period`, padrão 4h).
2. Classifica o **regime**: tendência, lateral ou indefinido (zona cinza).
3. Roteia:
   - tendência → estratégia principal (`atr_trend` por padrão);
   - lateral → grid spot se o canal for válido, senão pausa;
   - cinza → pausa.
4. Stop loss e take profit continuam ativos em todos os modos.
   - `stop_loss_pct` = venda a **mercado** (risk overlay).
   - `acceptable_loss_pct` = só piso do preço **limite** nas vendas da estratégia (não dispara SL).
   - Com `stop_loss_confirm_with_atr: true` e `atr_trend`, o SL % só executa se o close também romper o trailing ATR.
   - `take_profit` aceita escada parcial (`amount: 50` deixa runner); lista vazia desliga TP fixo.
   - Após saída total, a reentrada espera um novo sinal long (`need_fresh_long`).

Tamanho da ordem: `traded_usdt` é o notional em USDT de cada compra (limitado ao saldo disponível). `0` desativa entradas neste par. Há limite de notional mínimo da Binance, teto diário de perda, máximo de trades e circuit breaker.

## 6. Antes de ir para mainnet

1. `PYTHONPATH=src pytest tests/ -q`
2. `PYTHONPATH=src python src/backtests_compare.py` — resultado em `data/backtest_compare_4h.csv` (o backtest **não** simula regime, grid nem limites diários).
3. Rodar **48–72 h na testnet** e revisar `src/logs/trading_bot.json.log`.
4. Só então: chaves **mainnet**, `TRADING_ENV=mainnet` **e** `environment: mainnet` no YAML, exposição baixa (`traded_usdt`) no primeiro dia.

Não reutilize chaves de produção na testnet. Não afrouxe `stop_loss_pct`, `max_daily_loss_usdt`, `max_trades_per_day` ou `traded_usdt` sem revisar o impacto.

## 7. Parar e reiniciar

- Dashboard: `Ctrl+C` no processo `src/app/app.py`.
- Bot: `Ctrl+C` no `./run.sh`. Com `cancel_orders_on_shutdown: true`, o bot tenta cancelar ordens abertas ao sair.
- Depois de uma mudança **hard** no YAML, reinicie só o bot (`./run.sh`). O dashboard não precisa.

O estado (modo `trend`/`grid`, posição, canal) fica em `data/traderbot.db` e sobrevive ao restart.

## 8. Problemas comuns

| Sintoma | O que fazer |
|---------|-------------|
| `No module named 'waitress'` | Ative o venv e `pip install -r requirements.txt` |
| Dashboard recusa subir em `0.0.0.0` | Defina `DASHBOARD_PASSWORD_HASH` |
| Páginas abrem, API dá 401 | Faça login; `FLASK_TOKEN` não autentica o navegador |
| Bot recusa a segunda instância | Já existe um `src/main.py`; não suba outro |
| Badge mainnet com YAML testnet (ou o inverso) | Alinhe `TRADING_ENV` e `environment` |
| Config salva mas o par novo não opera | Identidade do ativo exige **restart do bot** |
| Eventos vazios no Tracking | O bot ainda não rodou um ciclo; confira o terminal do `./run.sh` |
| Site remoto dá 502 | PC dormiu, dashboard ou `cloudflared` parou; não abra a porta 5000 no roteador |
| Login local em `127.0.0.1` não gruda | `FLASK_COOKIE_SECURE=1`; use o hostname HTTPS do túnel |

Logs JSON: `src/logs/trading_bot.json.log`. Warnings `RemoteDisconnected` do urllib3 costumam ser retry automático, não falha permanente.

## Responsabilidade

O robô opera com dinheiro real na mainnet. Ordens, perdas e chaves de API são de quem opera. Comece na testnet. Licença: [AGPL](./LICENSE).
