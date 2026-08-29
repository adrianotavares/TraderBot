import logging
import signal
import sys
import threading
import time

from config.reload import SettingsWatch
from config.settings import load_settings
from modules.logging_setup import setup_logging, log_event
from modules.BinanceTraderBot import BinanceTraderBot
from Models.StockStartModel import StockStartModel
from persistence.process_lock import ProcessLock, ProcessLockHeld, lock_path_for
from persistence.state_store import DEFAULT_DB_PATH
from services.cycle_heartbeat import mark_cycle_end, mark_cycle_start

shutdown_event = threading.Event()
thread_lock = threading.Lock()
active_bots: list[BinanceTraderBot] = []
_settings_watch: SettingsWatch | None = None


def trader_loop(stock_start: StockStartModel, watch: SettingsWatch, env):
    settings = watch.settings
    asset_cfg = next(
        asset for asset in settings.assets if asset.operation_code == stock_start.operationCode
    )
    bot = BinanceTraderBot(
        stock_code=stock_start.stockCode,
        operation_code=stock_start.operationCode,
        traded_quantity=stock_start.tradedQuantity,
        traded_percentage=stock_start.tradedPercentage,
        candle_period=stock_start.candlePeriod,
        time_to_trade=stock_start.tempoEntreTrades,
        delay_after_order=stock_start.delayEntreOrdens,
        acceptable_loss_percentage=stock_start.acceptableLossPercentage,
        stop_loss_percentage=stock_start.stopLossPercentage,
        fallback_activated=stock_start.fallBackActivated,
        take_profit_at_percentage=stock_start.takeProfitAtPercentage,
        take_profit_amount_percentage=stock_start.takeProfitAmountPercentage,
        main_strategy=stock_start.mainStrategy,
        main_strategy_args=stock_start.mainStrategyArgs,
        fallback_strategy=stock_start.fallbackStrategy,
        fallback_strategy_args=stock_start.fallbackStrategyArgs,
        api_key=env.api_key,
        secret_key=env.secret_key,
        testnet=settings.environment == "testnet",
        risk_config=settings.risk.model_dump(),
        alerts_config=settings.alerts.model_dump(),
        regime_config=settings.regime.model_dump(),
        grid_config=settings.grid.model_dump(),
        breakout_config=settings.breakout.model_dump(),
        breakout_price=asset_cfg.breakout_price,
    )
    active_bots.append(bot)
    bot._settings_generation = 0
    total_executed = 1

    while not shutdown_event.is_set():
        try:
            watch.poll()
            generation, settings = watch.snapshot()
            if bot._settings_generation < generation:
                bot.apply_soft_settings(settings)
                bot._settings_generation = generation
            if settings.thread_lock:
                with thread_lock:
                    _run_cycle(bot, total_executed)
            else:
                _run_cycle(bot, total_executed)
            total_executed += 1
        except Exception as e:
            log_event(
                logging.ERROR,
                f"Trader loop error: {e}",
                operation_code=bot.operation_code,
                event="loop_error",
            )
            bot.time_to_sleep = bot.time_to_trade
            mark_cycle_end(bot, error=True)

        shutdown_event.wait(bot.time_to_sleep)


def _run_cycle(bot, total_executed):
    print(f"[{bot.operation_code}][{total_executed}] cycle start")
    mark_cycle_start(bot)
    bot.execute()
    print(
        f"^ [{bot.operation_code}][{total_executed}] "
        f"time_to_sleep = '{bot.time_to_sleep/60:.2f} min'"
    )
    mark_cycle_end(bot)


def _handle_sighup(signum, frame):
    if _settings_watch is not None:
        _settings_watch.request_reload()


def _handle_shutdown(signum, frame):
    print("\nShutdown signal received, stopping bot...")
    shutdown_event.set()
    settings, _ = load_settings()
    if settings.operation.cancel_orders_on_shutdown:
        for bot in active_bots:
            try:
                bot.cancelAllOrders()
            except Exception as e:
                print(f"Failed to cancel orders for {bot.operation_code}: {e}")


def main():
    setup_logging()
    settings, env = load_settings()
    instance_lock = ProcessLock(lock_path_for(DEFAULT_DB_PATH))
    try:
        instance_lock.acquire(settings.environment)
    except ProcessLockHeld as exc:
        log_event(
            logging.ERROR,
            str(exc),
            event="process_lock_held",
            environment=settings.environment,
            holder=exc.holder,
        )
        print(exc)
        sys.exit(1)

    stocks = settings.build_stock_models()
    global _settings_watch
    _settings_watch = SettingsWatch(env.config_path, settings)

    print(f"TraderBot starting in {settings.environment} mode")
    print(f"Assets: {[s.operationCode for s in stocks]}")

    signal.signal(signal.SIGINT, _handle_shutdown)
    signal.signal(signal.SIGTERM, _handle_shutdown)
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, _handle_sighup)

    threads = []
    try:
        for asset in stocks:
            thread = threading.Thread(
                target=trader_loop, args=(asset, _settings_watch, env), daemon=True
            )
            thread.start()
            threads.append(thread)

        print("Threads started for all assets.")
        while not shutdown_event.is_set():
            time.sleep(1)

        for thread in threads:
            thread.join(timeout=5)
        print("TraderBot stopped.")
    finally:
        instance_lock.release()


if __name__ == "__main__":
    main()
