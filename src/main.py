import threading
import time
import logging
import asyncio
from modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from Models.StockStartModel import StockStartModel
from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy
from strategies.rsi_strategy import getRsiTradeStrategy
from strategies.weapon_candle_trade_strategy import getWeaponCandleTradeStrategy

# Define o logger
logging.basicConfig(
    filename="src/logs/trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# fmt: off
# -----------------------------------------------------------------
# CONFIGURAÇÕES - INICIO

# ESTRATÉGIA PRINCIPAL

# MAIN_STRATEGY      = getMovingAverageAntecipationTradeStrategy
# MAIN_STRATEGY_ARGS = {"volatility_factor": 0.5, # Interfere na antecipação e nos lances de compra de venda limitados 
#                             "fast_window": 7,
#                             "slow_window": 25}

# VORTEX_STRATEGY = getVortexTradeStrategy
# VORTEX_STRATEGY_ARGS = {}

MAIN_STRATEGY = getWeaponCandleTradeStrategy
MAIN_STRATEGY_ARGS = {}

# MAIN_STRATEGY = getVortexTradeStrategy
# MAIN_STRATEGY_ARGS = {}

# MAIN_STRATEGY = getRsiTradeStrategy
# MAIN_STRATEGY_ARGS = {}

# MAIN_STRATEGY = getMovingAverageRSIVolumeStrategy
# MAIN_STRATEGY_ARGS = {  "fast_window":  7,
#                         "slow_window":  25,
#                         "rsi_window":  14,
#                         "rsi_overbought":  70,
#                         "rsi_oversold":  30,
#                         "volume_multiplier":  1.5
#                         }

# ESTRATÉGIA DE FALLBACK (reserva)
FALLBACK_ACTIVATED     = True
FALLBACK_STRATEGY      = getMovingAverageTradeStrategy
FALLBACK_STRATEGY_ARGS = {}

# AJUSTES TÉCNICOS

# Ajustes de LOSS PROTECTION
ACCEPTABLE_LOSS_PERCENTAGE = -1         # (Em base 100%) O quando o bot aceita perder de % (se for negativo, o bot só aceita lucro)
STOP_LOSS_PERCENTAGE       = 3.5       # (Em base 100%) % Máxima de loss que ele aceita para vender à mercado independente

# Ajustes de TAKE PROFIT (Em base 100%)                        
TP_AT_PERCENTAGE     = [10, 25, 50]     # Em [X%, Y%]                       
TP_AMOUNT_PERCENTAGE = [50, 50, 100]   # Vende [A%, B%]

# AJUSTES DE TEMPO
CANDLE_PERIOD      = Client.KLINE_INTERVAL_15MINUTE    # Périodo do candle análisado
TEMPO_ENTRE_TRADES = 15 * 60                           # Tempo que o bot espera para verificar o mercado (em segundos)
DELAY_ENTRE_ORDENS = 30 * 60                           # Tempo que o bot espera depois de realizar uma ordem de compra ou venda (ajuda a diminuir trades de borda)

# MOEDAS NEGOCIADAS
BTC_USDT = StockStartModel(      stockCode = "BTC",
                             operationCode = "BTCUSDT",
                            tradedQuantity = 0.0017,
                              mainStrategy = MAIN_STRATEGY, 
                          mainStrategyArgs = MAIN_STRATEGY_ARGS, 
                          fallbackStrategy = FALLBACK_STRATEGY, 
                      fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
                              candlePeriod = CANDLE_PERIOD, 
                        stopLossPercentage = STOP_LOSS_PERCENTAGE, 
                          tempoEntreTrades = TEMPO_ENTRE_TRADES, 
                          delayEntreOrdens = DELAY_ENTRE_ORDENS, 
                  acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, 
                         fallBackActivated = FALLBACK_ACTIVATED, 
                    takeProfitAtPercentage = TP_AT_PERCENTAGE, 
                takeProfitAmountPercentage = TP_AMOUNT_PERCENTAGE)

# ETH_USDT = StockStartModel(      stockCode = "ETH",
#                              operationCode = "ETHUSDT",
#                             tradedQuantity = 0.012,
#                               mainStrategy = VORTEX_STRATEGY, 
#                           mainStrategyArgs = VORTEX_STRATEGY_ARGS, 
#                           fallbackStrategy = FALLBACK_STRATEGY, 
#                       fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
#                               candlePeriod = CANDLE_PERIOD, 
#                         stopLossPercentage = STOP_LOSS_PERCENTAGE, 
#                           tempoEntreTrades = TEMPO_ENTRE_TRADES, 
#                           delayEntreOrdens = DELAY_ENTRE_ORDENS, 
#                   acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, 
#                          fallBackActivated = FALLBACK_ACTIVATED, 
#                     takeProfitAtPercentage = TP_AT_PERCENTAGE, 
#                takeProfitAmountPercentage = TP_AMOUNT_PERCENTAGE)

# SOL_USDT = StockStartModel(      stockCode = "SOL",
#                              operationCode = "SOLUSDT",
#                             tradedQuantity = 0.15,
#                               mainStrategy = MAIN_STRATEGY, 
#                           mainStrategyArgs = MAIN_STRATEGY_ARGS, 
#                           fallbackStrategy = FALLBACK_STRATEGY, 
#                       fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
#                               candlePeriod = CANDLE_PERIOD, 
#                         stopLossPercentage = STOP_LOSS_PERCENTAGE, 
#                           tempoEntreTrades = TEMPO_ENTRE_TRADES, 
#                           delayEntreOrdens = DELAY_ENTRE_ORDENS, 
#                   acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, 
#                          fallBackActivated = FALLBACK_ACTIVATED, 
#                     takeProfitAtPercentage = TP_AT_PERCENTAGE, 
#                 takeProfitAmountPercentage = TP_AMOUNT_PERCENTAGE)

# HMSTR_USDT = StockStartModel(    stockCode = "HMSTR",
#                              operationCode = "HMSTRUSDT",
#                             tradedQuantity = 8,
#                               mainStrategy = MAIN_STRATEGY, 
#                           mainStrategyArgs = MAIN_STRATEGY_ARGS, 
#                           fallbackStrategy = FALLBACK_STRATEGY, 
#                       fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
#                               candlePeriod = CANDLE_PERIOD, 
#                         stopLossPercentage = STOP_LOSS_PERCENTAGE, 
#                           tempoEntreTrades = TEMPO_ENTRE_TRADES, 
#                           delayEntreOrdens = DELAY_ENTRE_ORDENS, 
#                   acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, 
#                          fallBackActivated = FALLBACK_ACTIVATED, 
#                     takeProfitAtPercentage = TP_AT_PERCENTAGE, 
#                 takeProfitAmountPercentage = TP_AMOUNT_PERCENTAGE)

# XRP_USDT = StockStartModel(  stockCode = "XRP",
#                             operationCode = "XRPUSDT",
#                             tradedQuantity = 3,
#                             mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
#                             candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)

# ADA_USDT = StockStartModel(  stockCode = "ADA",
#                             operationCode = "ADAUSDT",
#                             tradedQuantity = 0,
#                             mainStrategy = MAIN_STRATEGY, mainStrategyArgs = MAIN_STRATEGY_ARGS, fallbackStrategy = FALLBACK_STRATEGY, fallbackStrategyArgs = FALLBACK_STRATEGY_ARGS,
#                             candlePeriod = CANDLE_PERIOD, stopLossPercentage = STOP_LOSS_PERCENTAGE, tempoEntreTrades = TEMPO_ENTRE_TRADES, delayEntreOrdens = DELAY_ENTRE_ORDENS, acceptableLossPercentage = ACCEPTABLE_LOSS_PERCENTAGE, fallBackActivated= FALLBACK_ACTIVATED, takeProfitAtPercentage=TP_AT_PERCENTAGE, takeProfitAmountPercentage=TP_AMOUNT_PERCENTAGE)

# Array de moedas que serão negociadas
stocks_traded_list = [BTC_USDT]

# True = Executa 1 moeda por vez | False = Executa todas simultânemaente
THREAD_LOCK = True 

# -----------------------------------------------------------------
# CONFIGURAÇÕES - FIM

# LOOP PRINCIPAL

thread_lock = threading.Lock()

def trader_loop(stockStart: StockStartModel):
    
    # Adiciona um loop de eventos na thread
    try:
        asyncio.set_event_loop(asyncio.new_event_loop()) 
    except Exception as e:
        print(f"Erro ao definir event loop: {e}")
        
    MaTrader = BinanceTraderBot(stock_code = stockStart.stockCode
                                , operation_code = stockStart.operationCode
                                , traded_quantity = stockStart.tradedQuantity
                                , traded_percentage = stockStart.tradedPercentage
                                , candle_period = stockStart.candlePeriod
                                , time_to_trade = stockStart.tempoEntreTrades
                                , delay_after_order = stockStart.delayEntreOrdens
                                , acceptable_loss_percentage = stockStart.acceptableLossPercentage
                                , stop_loss_percentage = stockStart.stopLossPercentage
                                , fallback_activated = stockStart.fallBackActivated
                                , take_profit_at_percentage = stockStart.takeProfitAtPercentage
                                , take_profit_amount_percentage= stockStart.takeProfitAmountPercentage
                                , main_strategy = stockStart.mainStrategy
                                , main_strategy_args =  stockStart.mainStrategyArgs
                                , fallback_strategy = stockStart.fallbackStrategy
                                , fallback_strategy_args = stockStart.fallbackStrategyArgs)
    
    total_executed:int = 1

    while(True):
        if(THREAD_LOCK):
            with thread_lock:
                print(f"[{MaTrader.operation_code}][{total_executed}] '{MaTrader.operation_code}'")
                MaTrader.execute()
                print(f"^ [{MaTrader.operation_code}][{total_executed}] time_to_sleep = '{MaTrader.time_to_sleep/60:.2f} min'")
                print(f"------------------------------------------------")
                total_executed += 1
        else:
            print(f"[{MaTrader.operation_code}][{total_executed}] '{MaTrader.operation_code}'")
            MaTrader.execute()
            print(f"^ [{MaTrader.operation_code}][{total_executed}] time_to_sleep = '{MaTrader.time_to_sleep/60:.2f} min'")
            print(f"------------------------------------------------")
            total_executed += 1
        time.sleep(MaTrader.time_to_sleep)

# Criando e iniciando uma thread para cada objeto
threads = []

for asset in stocks_traded_list:
    thread = threading.Thread(target=trader_loop, args=(asset,))
    thread.daemon = True  # Permite finalizar as threads ao encerrar o programa
    thread.start()
    threads.append(thread)

print("Threads iniciadas para todos os ativos.")

# O programa principal continua executando sem bloquear
try:
    while True:
        time.sleep(1)  # Mantenha o programa rodando
except KeyboardInterrupt:
    print("\nPrograma encerrado pelo usuário.")

# -----------------------------------------------------------------
# fmt: on
