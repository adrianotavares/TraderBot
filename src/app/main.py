import sys
import os

# Obtém o caminho correto do diretório `src`
SRC_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Adiciona `src` ao sys.path
sys.path.append(SRC_PATH)

import threading
import time
import json
import logging

from binance.client import Client
from Models.StockStartModel import StockStartModel
from modules.BinanceTraderBot import BinanceTraderBot
from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy


# Configuração de logging
logging.basicConfig(
    filename="src/logs/trading_bot.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

# Carregar configurações do JSON
with open("src/app/config.json", "r") as f:
    config = json.load(f)

# Carregar estratégias dinamicamente
strategies = {
    "getMovingAverageAntecipationTradeStrategy": getMovingAverageAntecipationTradeStrategy,
    "getMovingAverageTradeStrategy": getMovingAverageTradeStrategy,
    "getVortexTradeStrategy": getVortexTradeStrategy,
}

# Aplicar configurações do JSON
MAIN_STRATEGY = strategies[config["MAIN_STRATEGY"]]
FALLBACK_STRATEGY = strategies[config["FALLBACK_STRATEGY"]]

stocks_traded_list = [
    StockStartModel(
        stockCode=stock["stockCode"],
        operationCode=stock["operationCode"],
        tradedQuantity=stock["tradedQuantity"],
        mainStrategy=MAIN_STRATEGY,
        mainStrategyArgs=config["MAIN_STRATEGY_ARGS"],
        fallbackStrategy=FALLBACK_STRATEGY,
        fallbackStrategyArgs=config["FALLBACK_STRATEGY_ARGS"],
        # candlePeriod=config["CANDLE_PERIOD"],
        candlePeriod=Client.KLINE_INTERVAL_15MINUTE,
        stopLossPercentage=config["STOP_LOSS_PERCENTAGE"],
        tempoEntreTrades=config["TEMPO_ENTRE_TRADES"],
        delayEntreOrdens=config["DELAY_ENTRE_ORDENS"],
        acceptableLossPercentage=config["ACCEPTABLE_LOSS_PERCENTAGE"],
        fallBackActivated=config["FALLBACK_ACTIVATED"],
        takeProfitAtPercentage=config["TP_AT_PERCENTAGE"],
        takeProfitAmountPercentage=config["TP_AMOUNT_PERCENTAGE"],
    )
    for stock in config["stocks_traded_list"]
]

THREAD_LOCK = config["THREAD_LOCK"]

thread_lock = threading.Lock()


def trader_loop(stockStart: StockStartModel):
    MaTrader = BinanceTraderBot(
        stock_code=stockStart.stockCode,
        operation_code=stockStart.operationCode,
        traded_quantity=stockStart.tradedQuantity,
        traded_percentage=stockStart.tradedPercentage,
        candle_period=stockStart.candlePeriod,
        time_to_trade=stockStart.tempoEntreTrades,
        delay_after_order=stockStart.delayEntreOrdens,
        acceptable_loss_percentage=stockStart.acceptableLossPercentage,
        stop_loss_percentage=stockStart.stopLossPercentage,
        fallback_activated=stockStart.fallBackActivated,
        take_profit_at_percentage=stockStart.takeProfitAtPercentage,
        take_profit_amount_percentage=stockStart.takeProfitAmountPercentage,
        main_strategy=stockStart.mainStrategy,
        main_strategy_args=stockStart.mainStrategyArgs,
        fallback_strategy=stockStart.fallbackStrategy,
        fallback_strategy_args=stockStart.fallbackStrategyArgs,
    )
    total_executed = 1

    while True:
        if THREAD_LOCK:
            with thread_lock:
                MaTrader.execute()
                total_executed += 1
        else:
            MaTrader.execute()
            total_executed += 1
        time.sleep(MaTrader.time_to_sleep)


threads = []
for asset in stocks_traded_list:
    thread = threading.Thread(target=trader_loop, args=(asset,))
    thread.daemon = True
    thread.start()
    threads.append(thread)

print("Threads iniciadas para todos os ativos.")

try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\nPrograma encerrado pelo usuário.")
