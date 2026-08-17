from config.settings import load_settings
from modules.BinanceTraderBot import BinanceTraderBot
from binance.client import Client
from tests.backtestRunner import backtestRunner
from strategies.ut_bot_alerts import *
from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.moving_average import getMovingAverageTradeStrategy
from strategies.rsi_strategy import getRsiTradeStrategy
from strategies.vortex_strategy import getVortexTradeStrategy
from strategies.ma_rsi_volume_strategy import getMovingAverageRSIVolumeStrategy

settings, env = load_settings()
asset = settings.assets[0]

STOCK_CODE = asset.stock_code
OPERATION_CODE = asset.operation_code
INITIAL_BALANCE = asset.traded_quantity or 0.00025
CANDLE_PERIOD = settings.timing.candle_interval()
CLANDES_RODADOS   = 7 * 24
VOLATILITY_FACTOR = 0.5
FAST_WINDOW       = 7
SLOW_WINDOW       = 30

# ------------------------------------------------------------------------
# ⏬ SELEÇÃO DE ESTRATÉGIAS ⏬

devTrader = BinanceTraderBot(
    stock_code=STOCK_CODE,
    operation_code=OPERATION_CODE,
    traded_quantity=0,
    traded_percentage=100,
    candle_period=CANDLE_PERIOD,
    api_key=env.api_key,
    secret_key=env.secret_key,
    testnet=settings.environment == "testnet",
)


devTrader.updateAllData()

print(f"\n{STOCK_CODE} - UT BOTS - {str(CANDLE_PERIOD)}")
result = backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = utBotAlerts,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    atr_multiplier    = 2,
    atr_period        = 1,
    verbose           = False,
)
print(f"Lucro: {result['profit_percentage']:.2f}%")

print(f"\n{STOCK_CODE} - MA RSI e VOLUME - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = getMovingAverageRSIVolumeStrategy,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    verbose           = False,
)

  
print(f"\n{STOCK_CODE} - MA ANTECIPATION - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = getMovingAverageAntecipationTradeStrategy,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    volatility_factor = VOLATILITY_FACTOR,
    fast_window       = FAST_WINDOW,
    slow_window       = SLOW_WINDOW,
    verbose           = False,
)

print(f"\n{STOCK_CODE} - MA SIMPLES FALLBACK - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = getMovingAverageTradeStrategy,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    fast_window       = FAST_WINDOW,
    slow_window       = SLOW_WINDOW,
    verbose           = False,
)

print(f"\n{STOCK_CODE} - RSI - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = getRsiTradeStrategy,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    low               = 30,
    high              = 70,
    verbose           = False,
)

print(f"\n{STOCK_CODE} - VORTEX - {str(CANDLE_PERIOD)}")
backtestRunner(
    stock_data        = devTrader.stock_data,
    strategy_function = getVortexTradeStrategy,
    periods           = CLANDES_RODADOS,
    initial_balance   = INITIAL_BALANCE,
    verbose           = False,
)

print("\n\n")
