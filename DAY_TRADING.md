# Day trading com o TraderBot (100 USDT)

Guia prático. Pressupõe o bot já instalado ([COMO_USAR.md](./COMO_USAR.md)). Aqui o assunto é **como** usar o robô para day trade de sessão — não swing de 4h nem scalp de 5 minutos.

O TraderBot é **long-only** na Binance Spot: compra e depois vende. Não há venda a descoberto.

## 1. O que é day trade neste bot

Não é gráfico de 1 minuto nem posição overnight.

| | Significado aqui |
|---|---|
| Janela | 12:00–20:00 UTC (09:00–17:00 em Brasília) |
| Candle | 15 minutos, decisão no **close** da barra |
| Ideia | Uma por sessão, por ativo |
| Entrada | Ruptura da faixa das primeiras 30 min (12:00–12:30 UTC), com volume e ADX em expansão |
| Saída | Fim da janela (obrigatória), close de volta para dentro da faixa, ou stop do engine (2%) |

A estratégia que implementa isso é a `orb_day` (Opening Range Breakout). Ela **não** é a `vwap_scalp` (fade ao VWAP em 5m, ADX baixo). São teses opostas. Não misture as duas no mesmo `strategy.main`.

Na maior parte dos dias o sinal é `None`: a faixa não rompe com qualidade. Isso é o modo normal, não um defeito.

## 2. 100 USDT: uma crypto, não uma carteira

Com cem dólares a carteira de quatro pares **piora** o day trade.

O YAML atual ainda lista BTC 40% + ETH 30% + SOL 10% + XRP 10%. Em 100 USDT isso vira fatias de 40 / 30 / 10 / 10. Os problemas:

- A Binance Spot exige um **notional mínimo** (em geral ~5 USDT). Fatia de 10 USDT sobra pouco depois de taxa, arredondamento de lote e um stop de 2%.
- `max_daily_loss_usdt` e `max_trades_per_day` são **por ativo**, não da conta inteira. Quatro pares com perda diária 20 USDT cada permitem, no papel, até 80 USDT de perda no mesmo dia — 80% de 100 USDT.
- `orb_day` já mira **um** trade por sessão. Quatro ativos = até quatro tentativas correlacionadas (BTC e ETH costumam andar juntos).
- Taxa de ida e volta (~0,15% no hurdle da estratégia) come mais, em percentual, nas fatias pequenas.

**Recomendação para 100 USDT:** um único par líquido — `BTCUSDT` ou `ETHUSDT`. Deixe o USDT que não entrar na ordem parado. Diversificação de altcoins não é gestão de risco nesse tamanho; é fragmentação.

BTC costuma ter faixa mais “cara” de romper (muitos dias a OR fica estreita demais e o bot não compra — o teste de 30 dias na mainnet teve **um** `True` em BTC). ETH rompe um pouco mais, e também erra mais. Escolha um e viva com ele por algumas semanas antes de mudar.

## 3. Conta que 100 USDT realmente faz

Números redondos, ordem de 50 USDT (50% de 100), taxa spot ~0,075% por lado, stop 2%:

| Item | Conta | Valor |
|---|---|---|
| Tamanho da compra | 100 × 50% | 50 USDT |
| Taxa ida + volta | 50 × 0,15% | ~0,08 USDT |
| Stop 2% | 50 × 2% | 1,00 USDT |
| Perda ruim (stop + taxas) | | ~1,1 USDT (~1,1% da conta) |
| Hurdle da faixa | largura da OR ≥ 3 × 0,15% | ≥ 0,45% |

Se a faixa de abertura tiver menos de ~0,45% de largura, a `orb_day` devolve `None` (`Faixa estreita`). Não force. O mercado daquele dia não paga a taxa.

O take profit de 7% do YAML de swing **quase nunca** dispara num day trade de algumas horas. A saída normal é o flatten das 17:00 BRT ou o stop. Não calibre a expectativa em “+7% ao dia”.

Cem dólares não são capital para “viver de day trade”. São capital para **aprender o ciclo** com perda limitada. Quem precisa do dinheiro na conta não deveria ligar o bot na mainnet.

## 4. Configuração sugerida (100 USDT + `orb_day`)

No dashboard: **Config**. Depois de salvar, `strategy.main` e `timing.candle_period` exigem **restart** do `./run.sh`.

Alinhe `.env` e YAML: `TRADING_ENV=mainnet` **e** `environment: mainnet` (ou os dois em testnet). O `.env` prevalece se divergirem.

```yaml
environment: mainnet          # ou testnet, os dois lados iguais
strategy:
  main: orb_day
  main_args:
    session_start_utc: "12:00"
    session_end_utc: "20:00"
    opening_range_bars: 2      # 2 × 15m = 30 min de faixa
    adx_period: 14
    adx_min: 25.0              # expansão; o inverso do scalp
    adx_rising_bars: 2
    volume_sma: 20
    volume_mult: 1.5
    require_bullish_candle: true
    htf_sma_period: 50         # 0 desliga o filtro 4h (ORBP)
    fee_round_trip_pct: 0.15
    min_edge_multiple: 3.0
  fallback_enabled: false      # sem média móvel “tapando” o None
risk:
  acceptable_loss_pct: 1.5
  stop_loss_pct: 2.0           # não afrouxar
  take_profit:
    - at: 7.0
      amount: 100.0
  max_daily_loss_usdt: 5.0     # teto da CONTA neste tamanho; o YAML live pode estar em 20
  max_trades_per_day: 2        # um de folga; a estratégia já limita a 1/sessão
  max_open_orders: 3
timing:
  candle_period: 15m
  tempo_entre_trades: 60
  delay_entre_ordens: 60
assets:
  - stock_code: BTC
    operation_code: BTCUSDT
    traded_quantity: 0.0
    traded_percentage: 50.0    # metade da conta por sinal; o resto fica em USDT
# (remova ETH, SOL, XRP neste perfil)
regime:
  enabled: false
grid:
  enabled: false
breakout:
  enabled: false
```

Por quê esses números:

- **50%** deixa reserva para taxa, arredondamento e um segundo dia se o primeiro stopar. Não use 100% no primeiro mês.
- **`max_daily_loss_usdt: 5`** é ~5% de 100 USDT. O valor 20 do YAML atual é razoável para contas maiores; em 100 USDT é frouxo demais. Apertar o teto **não** exige confirmação extra; afrouxar, sim.
- **`max_trades_per_day: 2`** é o teto do `RiskManager`. A `orb_day` já se recusa a emitir um segundo `True` no mesmo dia UTC.
- **Fallback off, regime/grid off:** o day trade é a tese. Grid e `atr_trend` são outro sistema.

`traded_quantity: 0` significa “usar o percentual”. Não coloque quantidade fixa de BTC (0,001 BTC já pode ser dezenas de dólares a mais do que você quer).

## 5. Rotina do dia

Dois processos, **sempre**. O dashboard não liga o bot.

```bash
./run.sh                                 # terminal 1 — uma instância só
PYTHONPATH=src python src/app/app.py     # terminal 2
```

Abra http://127.0.0.1:5000.

1. **Antes das 09:00 BRT** — confira badge **mainnet** (ou testnet), saldo em USDT, e se não há posição aberta residual no Profit. Se houver lixo de ontem, o flatten das 17:00 deveria ter saído; se o bot estava desligado, trate a posição na mão ou deixe o Hold e decida.
2. **09:00–09:30 BRT** — o bot só acumula máxima/mínima. Não haverá compra. Use o Hold se não quiser que o resto do dia opere sozinho.
3. **09:30–17:00 BRT** — no close de cada 15m a `orb_day` testa ruptura + volume + ADX + (opcional) SMA de 4h. Um `True` tenta a compra; um `False` flatten se estiver comprado.
4. **17:00 BRT (20:00 UTC)** — fora da sessão o plug-in devolve `False`. O engine vende se houver posição. Não carregue para o dia seguinte “porque ainda não deu 7%”.
5. **Hold / Start** no Tracking — Hold bloqueia **compras**. Stop, take profit e saídas `False` continuam. É o jeito certo de ficar de fora num dia morto (ADX baixo, notícia, você ausente).

Não suba segundo `./run.sh`. O `ProcessLock` existe para isso.

## 6. Riscos e como o bot (e você) mitigam

| Risco | O que acontece | Mitigação |
|---|---|---|
| Stop 2% | Preço anda contra depois da ruptura (falso rompimento clássico) | `stop_loss_pct: 2`; a estratégia também vende se o close voltar para dentro da faixa |
| Vários pares no mesmo dia | Quatro stops correlacionados | Um ativo só; teto diário apertado |
| Teto diário por ativo | 4 × 20 USDT = 80 USDT | Um par + `max_daily_loss_usdt` baixo (ex.: 5) |
| Taxa + slippage | 0,15% some o “lucro” de uma faixa estreita | Hurdle `min_edge_multiple × fee`; não descer o múltiplo |
| Notional mínimo | Ordem rejeitada ou tamanho maior que o planejado | 50 USDT em BTC/ETH fica acima do piso; evite fatias de 10 |
| Bot desligado no flatten | Posição overnight sem querer | Deixe o processo no ar até 17:05 BRT ou venda na mão |
| Chave de API | Terceiro opera sua conta | Só Spot; **sem saque**; IP restrict se possível; nunca commitar `.env` |
| Segunda instância | Ordens duplicadas | Um `./run.sh`; se o lock reclamar, não force |
| Circuito aberto | Erros de API em sequência | `circuit_breaker_errors: 3` pausa 5 min; não fique restartando no escuro |
| Mainnet ≠ testnet | Chave de produção na testnet (ou o inverso) falha ou opera o lugar errado | Badge do dashboard + `TRADING_ENV` alinhado ao YAML |
| Expectativa | “Day trade = vários trades por dia” | A `orb_day` recusa o segundo `True`; a maior parte dos candles é `None` |
| Drawdown emocional | Apertar SL ou subir percentual depois de um ganho | Não afrouxe `stop_loss_pct`, `traded_percentage` nem o teto diário no calor do momento |

O backtest de 30 dias (klines públicos, sem SL diário) viu 1 entrada em BTC (+0,4% estimado) e 2 em ETH (−3% estimado). Isso **não** prova a estratégia. Serve para mostrar que o filtro é seletivo e que o ETH pode perder. O engine real ainda aplica stop 2% e o teto diário — o backtest simples não.

## 7. O que o robô não faz

- Não escolhe “a melhor moeda do dia”.
- Não escala a posição se o preço andar (o tamanho vem do `RiskManager`).
- Não opera short.
- Não substitui você no Hold de um dia de CPI, liquidação em cascata ou exchange instável.
- Não é HFT: o ciclo olha o close de 15m, a cada `tempo_entre_trades` (60 s).

## 8. Checklist antes do primeiro dia com dinheiro

1. Chave Spot, sem withdraw, IP restrito.
2. `TRADING_ENV` = `environment` no YAML.
3. Um par, `traded_percentage` ≤ 50, `orb_day`, candle `15m`, fallback/regime/grid off.
4. `max_daily_loss_usdt` compatível com 100 USDT (pense em 5, não em 20).
5. Dashboard aberto; saiba onde estão Hold, Profit e o badge de ambiente.
6. Você estará por perto pelo menos no flatten (17:00 BRT) no primeiro dia.
7. Uma só instância do bot.

Se a dúvida for “ainda não entendi o sinal”, ligue o bot em **Hold**: o ciclo roda, o Tracking atualiza, nenhuma compra sai. Depois, Start.

## 9. Quando não operar

- Conta com dinheiro que você não pode perder.
- Você não vai estar no computador perto das 17:00 BRT e não confia no flatten automático.
- O YAML ainda tem quatro ativos e teto de 20 USDT **por** par.
- `vwap_scalp` e `orb_day` tentando coexistir (troque o `main`, reinicie, não some as teses).
- Ambiente misturado (`.env` testnet + YAML mainnet, ou o contrário).

## Responsabilidade

Na mainnet as ordens são reais. O robô executa a regra; o risco residual (falso rompimento, gap, API fora, você ausente no flatten) é de quem liga o `./run.sh`.
