# fmt: off
import os
import time
from datetime import datetime
import logging
import math

from dotenv import load_dotenv
import pandas as pd
from binance.client import Client
from binance.enums import *
from binance.enums import SIDE_SELL, ORDER_TYPE_STOP_LOSS_LIMIT
from binance.exceptions import BinanceAPIException

from modules.BinanceClient import BinanceClient
from modules.TraderOrder import TraderOrder
from modules.Logger import *

from modules.StrategyRunner import StrategyRunner


from strategies.moving_average_antecipation import getMovingAverageAntecipationTradeStrategy
from strategies.moving_average import getMovingAverageTradeStrategy

from indicators import Indicators
# fmt: on


load_dotenv()
api_key = os.getenv("BINANCE_API_KEY")
secret_key = os.getenv("BINANCE_SECRET_KEY")


# ------------------------------------------------------------------


# Classe Principal
class BinanceTraderBot:

    # --------------------------------------------------------------
    # Parâmetros da classe sem valor inicial
    last_trade_decision = None  # Última decisão de posição (False = Vender | True = Comprar)
    last_buy_price = 0  # Último valor de ordem de COMPRA executado
    last_sell_price = 0  # Ùltimo valor de ordem de VENDA executada
    open_orders = []
    # Valor que já foi executado e que será descontado da quantidade,
    # caso uma ordem não seja completamente executada
    partial_quantity_discount = 0

    tick_size: float
    step_size: float
    take_profit_index = 0

    # Construtor
    def __init__(
        self,
        stock_code,
        operation_code,
        traded_quantity,
        traded_percentage,
        candle_period,
        time_to_trade=30 * 60,
        delay_after_order=60 * 60,
        acceptable_loss_percentage=0.5,
        stop_loss_percentage=3.5,
        fallback_activated=True,
        take_profit_at_percentage=[],
        take_profit_amount_percentage=[],
        main_strategy=None,
        main_strategy_args=None,
        fallback_strategy=None,
        fallback_strategy_args=None,
    ):

        print("------------------------------------------------")
        print("🤖 Robo Trader iniciando...")

        # fmt: off

        self.stock_code = stock_code  # Código princial da stock negociada (ex: 'BTC')
        self.operation_code = operation_code  # Código negociado/moeda (ex:'BTCBRL')
        self.traded_quantity = traded_quantity  # Quantidade incial que será operada
        self.traded_percentage = traded_percentage  # Porcentagem do total da carteira, que será negociada        
        self.candle_period = candle_period  # Período levado em consideração para operação (ex: 15min)        

        self.fallback_activated = fallback_activated  # Define se a estratégia de Fallback será usada (ela pode entrar comprada em mercados subindo)
        self.acceptable_loss_percentage = acceptable_loss_percentage / 100 # % Máxima que o bot aceita perder quando vender
        self.stop_loss_percentage = stop_loss_percentage / 100 # % Máxima de loss que ele aceita, em caso de não vender na ordem limitada

        self.take_profit_at_percentage = take_profit_at_percentage # Quanto de valorização para pegar lucro. (Array exemplo: [2, 5, 10])
        self.take_profit_amount_percentage = take_profit_amount_percentage # Quanto da quantidade tira de lucro. (Array exemplo: [25, 25, 40])

        self.main_strategy = main_strategy # Estratégia principal
        self.main_strategy_args = main_strategy_args # (opcional) Argumentos da estratégia principal
        self.fallback_strategy = fallback_strategy # (opcional) Estratégia de Fallback
        self.fallback_strategy_args = fallback_strategy_args # (opcional) Argumentos da estratégia de fallback

        # Configurações de tempos de espera
        self.time_to_trade = time_to_trade
        self.delay_after_order = delay_after_order
        self.time_to_sleep = time_to_trade

        self.client_binance = BinanceClient(
            api_key, secret_key, sync=True, sync_interval=30000, verbose=False
        )  # Inicia o client da Binance

        self.setStepSizeAndTickSize() # Seta o time_step e step_size da classe (só precisa executar 1x)

        # fmt: on

    # Atualiza todos os dados da conta
    # Função importante, sempre incrementar ela, em caso de novos gets
    def updateAllData(
        self,
        verbose=False,
    ):
        try:
            # Dados atualizados do usuário e sua carteira
            self.account_data = self.getUpdatedAccountData()
            # Balanço atual do ativo na carteira
            self.last_stock_account_balance = self.getLastStockAccountBalance()
            # Posição atual (False = Vendido | True = Comprado)
            self.actual_trade_position = self.getActualTradePosition()
            # Atualiza dados usados nos modelos
            self.stock_data = self.getStockData()
            # Retorna uma lista com todas as ordens abertas
            self.open_orders = self.getOpenOrders()
            # Salva o último valor de compra executado com sucesso
            self.last_buy_price = self.getLastBuyPrice(verbose)
            # Salva o último valor de venda executado com sucesso
            self.last_sell_price = self.getLastSellPrice(verbose)
            # Se a posição atual for vendida, ele reseta o index do take profit
            if self.actual_trade_position == False:
                self.take_profit_index = 0

        except BinanceAPIException as e:
            print(f"Erro na atualização de dados: {e}")

    # ------------------------------------------------------------------
    # GETS Principais

    # Busca infos atualizada da conta Binance
    def getUpdatedAccountData(self):
        return self.client_binance.get_account()  # Busca infos da conta

    # Busca o último balanço da conta, na stock escolhida.
    def getLastStockAccountBalance(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                free = float(stock["free"])
                locked = float(stock["locked"])
                in_wallet_amount = free + locked
        return float(in_wallet_amount)

    # Checa se a posição atual é comprado ou vendido
    # Checa se a posição atual é comprado ou vendido
    def getActualTradePosition(self):
        """
        Determina a posição atual (comprado ou vendido) com base no saldo da moeda.
        Usa o stepSize da Binance para ajustar o limite mínimo.
        """
        # print(f'STEP SIZE: {self.step_size}')
        try:
            # Verifica se o saldo é maior que o step_size
            if self.last_stock_account_balance >= self.step_size:
                return True  # Comprado
            else:
                return False  # Vendido

        except Exception as e:
            print(f"Erro ao determinar a posição atual para {self.operation_code}: {e}")
            return False  # Retorna como vendido por padrão em caso de erro

    # Busca os dados do ativo no periodo
    def getStockData(
        self,
    ):

        # Busca dados na binance dos últimos 1000 períodos
        candles = self.client_binance.get_klines(
            symbol=self.operation_code,
            interval=self.candle_period,
            limit=1000,
        )

        # Transforma um um DataFrame Pandas
        prices = pd.DataFrame(candles)

        # Renomea as colunas baseada na Documentação da Binance
        prices.columns = [
            "open_time",
            "open_price",
            "high_price",
            "low_price",
            "close_price",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "-",
        ]

        # Pega apenas os indicadores que queremos para esse modelo
        prices = prices[
            [
                "close_price",
                "open_time",
                "open_price",
                "high_price",
                "low_price",
                "volume",
            ]
        ]

        # Converte as colunas para o tipo numérico
        prices["close_price"] = pd.to_numeric(
            prices["close_price"],
            errors="coerce",
        )
        prices["open_price"] = pd.to_numeric(
            prices["open_price"],
            errors="coerce",
        )
        prices["high_price"] = pd.to_numeric(
            prices["high_price"],
            errors="coerce",
        )
        prices["low_price"] = pd.to_numeric(
            prices["low_price"],
            errors="coerce",
        )
        prices["volume"] = pd.to_numeric(
            prices["volume"],
            errors="coerce",
        )

        # Corrige o tempo de fechamento
        prices["open_time"] = pd.to_datetime(
            prices["open_time"],
            unit="ms",
        ).dt.tz_localize("UTC")

        # Converte para o fuso horário UTC -3
        prices["open_time"] = prices["open_time"].dt.tz_convert("America/Sao_Paulo")

        # CÁLCULOS PRÉVIOS...

        return prices

    # Retorna o preço da última ordem de compra executada para o ativo configurado.
    # Retorna 0.0 se nenhuma ordem de compra foi encontrada.
    def getLastBuyPrice(
        self,
        verbose=False,
    ):
        try:
            # Obtém o histórico de ordens do par configurado
            all_orders = self.client_binance.get_all_orders(
                symbol=self.operation_code,
                limit=100,
            )

            # Filtra apenas as ordens de compra executadas (FILLED)
            executed_buy_orders = [order for order in all_orders if order["side"] == "BUY" and order["status"] == "FILLED"]

            if executed_buy_orders:
                # Ordena as ordens por tempo (timestamp) para obter a mais recente
                last_executed_order = sorted(
                    executed_buy_orders,
                    key=lambda x: x["time"],
                    reverse=True,
                )[0]

                # print(f'ÚLTIMA EXECUTADA: {last_executed_order}')

                # Retorna o preço da última ordem de compra executada
                last_buy_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])
                # Corrige o timestamp para a chave correta
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")
                if verbose:
                    print(f"\nÚltima ordem de COMPRA executada para {self.operation_code}:")
                    print(
                        f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_buy_price,self.tick_size, as_string=True)} | Qnt.: {self.adjust_to_step(float(last_executed_order['origQty']), self.step_size, as_string=True)}"
                    )

                return last_buy_price
            else:
                if verbose:
                    print(f"Não há ordens de COMPRA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de COMPRA executada para {self.operation_code}: {e}")
            return 0.0

    # Retorna o preço da última ordem de venda executada para o ativo configurado.
    # Retorna 0.0 se nenhuma ordem de venda foi encontrada.
    def getLastSellPrice(
        self,
        verbose=False,
    ):
        try:
            # Obtém o histórico de ordens do par configurado
            all_orders = self.client_binance.get_all_orders(
                symbol=self.operation_code,
                limit=100,
            )

            # Filtra apenas as ordens de venda executadas (FILLED)
            executed_sell_orders = [order for order in all_orders if order["side"] == "SELL" and order["status"] == "FILLED"]

            if executed_sell_orders:
                # Ordena as ordens por tempo (timestamp) para obter a mais recente
                last_executed_order = sorted(
                    executed_sell_orders,
                    key=lambda x: x["time"],
                    reverse=True,
                )[0]

                # Retorna o preço da última ordem de venda executada
                last_sell_price = float(last_executed_order["cummulativeQuoteQty"]) / float(last_executed_order["executedQty"])

                # Corrige o timestamp para a chave correta
                datetime_transact = datetime.utcfromtimestamp(last_executed_order["time"] / 1000).strftime("(%H:%M:%S) %d-%m-%Y")

                if verbose:
                    print(f"Última ordem de VENDA executada para {self.operation_code}:")
                    print(
                        f" - Data: {datetime_transact} | Preço: {self.adjust_to_step(last_sell_price,self.tick_size, as_string=True)} | Qnt.: {self.adjust_to_step(float(last_executed_order['origQty']), self.step_size, as_string=True)}"
                    )
                return last_sell_price
            else:
                if verbose:
                    print(f"Não há ordens de VENDA executadas para {self.operation_code}.")
                return 0.0

        except Exception as e:
            if verbose:
                print(f"Erro ao verificar a última ordem de VENDA executada para {self.operation_code}: {e}")
            return 0.0

    def getTimestamp(self):
        """
        Retorna o timestamp ajustado com base no desvio de tempo entre o sistema local e o servidor da Binance.
        """
        try:
            # Obtém o tempo do servidor da Binance e calcula o desvio apenas uma vez
            if (
                not hasattr(
                    self,
                    "time_offset",
                )
                or self.time_offset is None
            ):
                server_time = self.client_binance.get_server_time()["serverTime"]
                local_time = int(time.time() * 1000)
                self.time_offset = server_time - local_time

            # Retorna o timestamp ajustado
            adjusted_timestamp = int(time.time() * 1000) + self.time_offset
            return adjusted_timestamp

        except Exception as e:
            print(f"Erro ao ajustar o timestamp: {e}")
            # Retorna o timestamp local em caso de falha, mas não é recomendado para chamadas críticas
            return int(time.time() * 1000)

    # --------------------------------------------------------------
    # SETs

    # Seta o step_size (para quantidade) e tick_size (para preço) do ativo operado, só precisa ser executado 1x
    def setStepSizeAndTickSize(self):
        # Obter informações do símbolo para respeitar os filtros
        symbol_info = self.client_binance.get_symbol_info(self.operation_code)
        price_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "PRICE_FILTER")
        self.tick_size = float(price_filter["tickSize"])

        lot_size_filter = next(f for f in symbol_info["filters"] if f["filterType"] == "LOT_SIZE")
        self.step_size = float(lot_size_filter["stepSize"])

    """
    Ajusta o valor para o múltiplo mais próximo do passo definido, lidando com problemas de precisão
    e garantindo que o resultado não seja retornado em notação científica.

    Parameters:
        value (float): O valor a ser ajustado.
        step (float): O incremento mínimo permitido.
        as_string (bool): Define se o valor ajustado será retornado como string. Padrão é True.

    Returns:
        str|float: O valor ajustado no formato especificado.
    """

    def adjust_to_step(
        self,
        value,
        step,
        as_string=False,
    ):

        if step <= 0:
            raise ValueError("O valor de 'step' deve ser maior que zero.")

        # Descobrir o número de casas decimais do step
        decimal_places = (
            max(
                0,
                abs(int(math.floor(math.log10(step)))),
            )
            if step < 1
            else 0
        )

        # Ajustar o valor ao step usando floor
        adjusted_value = math.floor(value / step) * step

        # Garantir que o resultado tenha a mesma precisão do step
        adjusted_value = round(
            adjusted_value,
            decimal_places,
        )

        # Retornar no formato especificado
        if as_string:
            return f"{adjusted_value:.{decimal_places}f}"
        else:
            return adjusted_value

    # --------------------------------------------------------------
    # PRINTS

    # Printa toda a carteira
    def printWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                print(stock)

    # Printa o ativo definido na classe
    def printStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                print(stock)

    def printBrl(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == "BRL":
                print(stock)

    # Printa todas ordens abertas
    def printOpenOrders(self):
        # Log das ordens abertas
        if self.open_orders:
            print("-------------------------")
            print(f"Ordens abertas para {self.operation_code}:")
            for order in self.open_orders:
                to_print = (
                    f"----"
                    f"\nID {order['orderId']}:"
                    f"\n - Status: {getOrderStatus(order['status'])}"
                    f"\n - Side: {order['side']}"
                    f"\n - Ativo: {order['symbol']}"
                    f"\n - Preço: {order['price']}"
                    f"\n - Quantidade Original: {order['origQty']}"
                    f"\n - Quantidade Executada: {order['executedQty']}"
                    f"\n - Tipo: {order['type']}"
                )
                print(to_print)
            print("-------------------------")

        else:
            print(f"Não há ordens abertas para {self.operation_code}.")

    # --------------------------------------------------------------
    # GETs auxiliares

    # Retorna toda a carteira
    def getWallet(self):
        for stock in self.account_data["balances"]:
            if float(stock["free"]) > 0:
                return stock

    # Retorna todo o ativo definido na classe
    def getStock(self):
        for stock in self.account_data["balances"]:
            if stock["asset"] == self.stock_code:
                return stock

    def getPriceChangePercentage(self, initial_price, close_price):
        if initial_price == 0:
            raise ValueError("O initial_price não pode ser zero.")

        percentual_change = ((close_price - initial_price) / initial_price) * 100
        return percentual_change

    # --------------------------------------------------------------
    # FUNÇÕES DE COMPRA

    # Compra a ação a MERCADO
    def buyMarketOrder(self, quantity=None):
        try:
            if not self.actual_trade_position:  # Se a posição for vendida

                if quantity == None:  # Se não definida, ele vende tudo na carteira
                    quantity = self.adjust_to_step(
                        self.last_stock_account_balance,
                        self.step_size,
                        as_string=True,
                    )
                else:  # Se não, ele ajusta o valor passado
                    quantity = self.adjust_to_step(
                        quantity,
                        self.step_size,
                        as_string=True,
                    )

                order_buy = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_BUY,  # Compra
                    type=ORDER_TYPE_MARKET,  # Ordem de Mercado
                    quantity=quantity,
                )

                self.actual_trade_position = True  # Define posição como comprada
                createLogOrder(order_buy)  # Cria um log
                print(f"\nOrdem de COMPRA a mercado enviada com sucesso:")
                print(order_buy)
                return order_buy  # Retorna a ordem

            else:  # Se a posição já está comprada
                logging.warning("Erro ao comprar: Posição já comprada.")
                print("\nErro ao comprar: Posição já comprada.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de compra a mercado: {e}")
            print(f"\nErro ao executar ordem de compra a mercado: {e}")
            return False

    # Compra por um preço máximo (Ordem Limitada)
    # [NOVA] Define o valor usando RSI e Volume Médio
    def buyLimitedOrder(
        self,
        price=0,
    ):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]  # Volume atual do mercado
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]  # Média de volume
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])  # RSI para ajuste

        if price == 0:
            if rsi < 30:  # Mercado sobrevendido
                limit_price = close_price - (0.002 * close_price)  # Tenta comprar um pouco mais abaixo
            elif volume < avg_volume:  # Volume baixo (mercado lateral)
                limit_price = close_price + (0.002 * close_price)  # Ajuste pequeno acima
            else:  # Volume alto (mercado volátil)
                limit_price = close_price + (0.005 * close_price)  # Ajuste maior acima (caso suba muito rápido)
        else:
            limit_price = price

        # Ajustar o preço limite para o tickSize permitido
        limit_price = self.adjust_to_step(
            limit_price,
            self.tick_size,
            as_string=True,
        )

        # Ajustar a quantidade para o stepSize permitido
        quantity = self.adjust_to_step(
            self.traded_quantity - self.partial_quantity_discount,
            self.step_size,
            as_string=True,
        )

        # Log de informações
        print(f"Enviando ordem limitada de COMPRA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        # Enviar ordem limitada de COMPRA
        try:
            order_buy = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_BUY,  # Compra
                type=ORDER_TYPE_LIMIT,  # Ordem Limitada
                timeInForce="GTC",  # Good 'Til Canceled (Ordem válida até ser cancelada)
                quantity=quantity,
                price=limit_price,
            )
            self.actual_trade_position = True  # Atualiza a posição para comprada
            print(f"\nOrdem COMPRA limitada enviada com sucesso:")
            # print(order_buy)
            if order_buy is not None:
                createLogOrder(order_buy)  # Cria um log

            return order_buy  # Retorna a ordem enviada
        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de COMPRA: {e}")
            print(f"\nErro ao enviar ordem limitada de COMPRA: {e}")
            return False

    # --------------------------------------------------------------
    # FUNÇÕES DE VENDA

    # Vende a ação a MERCADO
    def sellMarketOrder(self, quantity=None):
        try:
            if self.actual_trade_position:  # Se a posição for comprada

                if quantity == None:  # Se não definida, ele vende tudo na carteira
                    quantity = self.adjust_to_step(
                        self.last_stock_account_balance,
                        self.step_size,
                        as_string=True,
                    )
                else:  # Se não, ele ajusta o valor passado
                    quantity = self.adjust_to_step(
                        quantity,
                        self.step_size,
                        as_string=True,
                    )

                order_sell = self.client_binance.create_order(
                    symbol=self.operation_code,
                    side=SIDE_SELL,  # Venda
                    type=ORDER_TYPE_MARKET,  # Ordem de Mercado
                    quantity=quantity,
                )

                self.actual_trade_position = False  # Define posição como vendida
                createLogOrder(order_sell)  # Cria um log
                print(f"\nOrdem de VENDA a mercado enviada com sucesso:")
                # print(order_sell)
                return order_sell  # Retorna a ordem

            else:  # Se a posição já está vendida
                logging.warning("Erro ao vender: Posição já vendida.")
                print("\nErro ao vender: Posição já vendida.")
                return False

        except Exception as e:
            logging.error(f"Erro ao executar ordem de venda a mercado: {e}")
            print(f"\nErro ao executar ordem de venda a mercado: {e}")
            return False

    # Venda por um preço mínimo (Ordem Limitada)
    # [NOVA] Define o valor usando RSI e Volume Médio
    def sellLimitedOrder(
        self,
        price=0,
    ):
        close_price = self.stock_data["close_price"].iloc[-1]
        volume = self.stock_data["volume"].iloc[-1]  # Volume atual do mercado
        avg_volume = self.stock_data["volume"].rolling(window=20).mean().iloc[-1]  # Média de volume
        rsi = Indicators.getRSI(series=self.stock_data["close_price"])

        if price == 0:
            if rsi > 70:  # Mercado sobrecomprado
                limit_price = close_price + (0.002 * close_price)  # Tenta vender um pouco acima
            elif volume < avg_volume:  # Volume baixo (mercado lateral)
                limit_price = close_price - (0.002 * close_price)  # Ajuste pequeno abaixo
            else:  # Volume alto (mercado volátil)
                limit_price = close_price - (0.005 * close_price)  # Ajuste maior abaixo (caso caia muito rápido)

            # Garantir que o preço limite seja maior que o mínimo aceitável
            # limit_price = max(limit_price, self.getMinimumPriceToSell())
            if limit_price < (self.last_buy_price * (1 - self.acceptable_loss_percentage)):
                print(f"\nAjuste de venda aceitável ({self.acceptable_loss_percentage*100}%):")
                print(f" - De: {limit_price:.4f}")
                # limit_price = (self.last_buy_price*(1-self.acceptable_loss_percentage))
                limit_price = self.getMinimumPriceToSell()
                print(f" - Para: {limit_price}")
        else:
            limit_price = price

        # Ajustar o preço limite para o tickSize permitido
        limit_price = self.adjust_to_step(
            limit_price,
            self.tick_size,
            as_string=True,
        )

        # Ajustar a quantidade para o stepSize permitido
        quantity = self.adjust_to_step(
            self.last_stock_account_balance,
            self.step_size,
            as_string=True,
        )

        # Log de informações
        print(f"\nEnviando ordem limitada de VENDA para {self.operation_code}:")
        print(f" - RSI: {rsi}")
        print(f" - Quantidade: {quantity}")
        print(f" - Close Price: {close_price}")
        print(f" - Preço Limite: {limit_price}")

        # Enviar ordem limitada de VENDA
        try:
            # Por algum motivo, fazer direto por aqui resolveu um bug de mudança de preço
            # Depois vou testar novamente.
            order_sell = self.client_binance.create_order(
                symbol=self.operation_code,
                side=SIDE_SELL,  # Venda
                type=ORDER_TYPE_LIMIT,  # Ordem Limitada
                timeInForce="GTC",  # Good 'Til Canceled (Ordem válida até ser cancelada)
                quantity=quantity,
                price=limit_price,
            )

            self.actual_trade_position = False  # Atualiza a posição para vendida
            print(f"\nOrdem VENDA limitada enviada com sucesso:")
            # print(order_sell)
            createLogOrder(order_sell)  # Cria um log
            return order_sell  # Retorna a ordem enviada
        except Exception as e:
            logging.error(f"Erro ao enviar ordem limitada de VENDA: {e}")
            print(f"\nErro ao enviar ordem limitada de VENDA: {e}")
            return False

    # --------------------------------------------------------------
    # ORDENS E SUAS ATUALIZAÇÕES

    # Verifica as ordens ativas do ativo atual configurado
    def getOpenOrders(self):
        open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

        return open_orders

    # Cancela uma ordem a partir do seu ID
    def cancelOrderById(
        self,
        order_id,
    ):
        self.client_binance.cancel_order(
            symbol=self.operation_code,
            orderId=order_id,
        )

    # Cancela todas ordens abertas
    def cancelAllOrders(self):
        if self.open_orders:
            for order in self.open_orders:
                try:
                    self.client_binance.cancel_order(
                        symbol=self.operation_code,
                        orderId=order["orderId"],
                    )
                    print(f"❌ Ordem {order['orderId']} cancelada.")
                except Exception as e:
                    print(f"Erro ao cancelar ordem {order['orderId']}: {e}")

    # Verifica se há alguma ordem de COMPRA aberta
    # Se a ordem foi parcialmente executada, ele salva o valor
    # executado na variável self.partial_quantity_discount, para que
    # este valor seja descontado nas execuções seguintes.
    # Se foi parcialmente executado, ela também salva o valor que foi executado
    # na variável self.last_buy_price
    def hasOpenBuyOrder(self):
        """
        Verifica se há uma ordem de compra aberta para o ativo configurado.
        Se houver:
            - Salva a quantidade já executada em self.partial_quantity_discount.
            - Salva o maior preço parcialmente executado em self.last_buy_price.
        """
        # Inicializa as variáveis de desconto e maior preço como 0
        self.partial_quantity_discount = 0.0
        try:

            # Obtém todas as ordens abertas para o par
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

            # Filtra as ordens de compra (SIDE_BUY)
            buy_orders = [order for order in open_orders if order["side"] == "BUY"]

            if buy_orders:
                self.last_buy_price = 0.0

                print(f"\nOrdens de compra abertas para {self.operation_code}:")
                for order in buy_orders:
                    executed_qty = float(order["executedQty"])  # Quantidade já executada
                    price = float(order["price"])  # Preço da ordem

                    print(
                        f" - ID da Ordem: {order['orderId']}, Preço: {price}, Qnt.: {order['origQty']}, Qnt. Executada: {executed_qty}"
                    )

                    # Atualiza a quantidade parcial executada
                    self.partial_quantity_discount += executed_qty

                    # Atualiza o maior preço parcialmente executado
                    if executed_qty > 0 and price > self.last_buy_price:
                        self.last_buy_price = price

                print(f" - Quantidade parcial executada no total: {self.partial_quantity_discount}")
                print(f" - Maior preço parcialmente executado: {self.last_buy_price}")
                return True
            else:
                print(f" - Não há ordens de compra abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas para {self.operation_code}: {e}")
            return False

    # Verifica se há uma ordem de VENDA aberta para o ativo configurado.
    # Se houver, salva a quantidade já executada na variável self.partial_quantity_discount.
    def hasOpenSellOrder(self):
        # Inicializa a variável de desconto como 0
        self.partial_quantity_discount = 0.0
        try:

            # Obtém todas as ordens abertas para o par
            open_orders = self.client_binance.get_open_orders(symbol=self.operation_code)

            # Filtra as ordens de venda (SIDE_SELL)
            sell_orders = [order for order in open_orders if order["side"] == "SELL"]

            if sell_orders:
                print(f"\nOrdens de venda abertas para {self.operation_code}:")
                for order in sell_orders:
                    executed_qty = float(order["executedQty"])  # Quantidade já executada
                    print(
                        f" - ID da Ordem: {order['orderId']}, Preço: {order['price']}, Qnt.: {order['origQty']}, Qnt. Executada: {executed_qty}"
                    )

                    # Atualiza a quantidade parcial executada
                    self.partial_quantity_discount += executed_qty

                print(f" - Quantidade parcial executada no total: {self.partial_quantity_discount}")
                return True
            else:
                print(f" - Não há ordens de venda abertas para {self.operation_code}.")
                return False

        except Exception as e:
            print(f"Erro ao verificar ordens abertas para {self.operation_code}: {e}")
            return False

    # --------------------------------------------------------------
    # ESTRATÉGIAS DE DECISÃO

    # Função que executa estratégias implementadas e retorna a decisão final
    def getFinalDecisionStrategy(self):

        final_decision = StrategyRunner.execute(
            self,
            stock_data=self.stock_data,
            main_strategy=self.main_strategy,
            main_strategy_args=self.main_strategy_args,
            fallback_strategy=self.fallback_strategy,
            fallback_strategy_args=self.fallback_strategy_args,
        )

        return final_decision

    # Define o valor mínimo para vender, baseado no acceptable_loss_percentage
    def getMinimumPriceToSell(self):
        return self.last_buy_price * (1 - self.acceptable_loss_percentage)

    # Estratégia de venda por "Stop Loss"
    def stopLossTrigger(self):
        close_price = self.stock_data["close_price"].iloc[-1]
        weighted_price = self.stock_data["close_price"].iloc[-2]  # Preço ponderado pelo candle anterior
        stop_loss_price = self.last_buy_price * (1 - self.stop_loss_percentage)

        print(f'\n - Preço atual: {self.stock_data["close_price"].iloc[-1]}')
        print(f" - Preço mínimo para vender: {self.getMinimumPriceToSell()}")
        print(f" - Stop Loss em: {stop_loss_price:.4f} (-{self.stop_loss_percentage*100:.2f}%)\n")

        if close_price < stop_loss_price and weighted_price < stop_loss_price and self.actual_trade_position == True:
            print("🔴 Ativando STOP LOSS...")
            self.cancelAllOrders()
            time.sleep(2)
            self.sellMarketOrder()
            return True
        return False

    # Estratégia de venda por "Take Profit"
    def takeProfitTrigger(self):
        """
        Verifica se o preço atual atingiu uma meta de take profit e, se sim,
        realiza uma venda parcial da carteira de acordo com os percentuais definidos.
        Retorna True se a venda for executada, caso contrário, retorna False.
        """

        try:
            # Obtém o preço de fechamento mais recente
            close_price = self.stock_data["close_price"].iloc[-1]

            # Calcula a variação percentual do preço
            price_percentage_variation = self.getPriceChangePercentage(initial_price=self.last_buy_price, close_price=close_price)

            print(f" - Variação atual: {price_percentage_variation:.2f}%")

            # Verifica se o índice atual está dentro do tamanho da lista de take profit
            if self.take_profit_index < len(self.take_profit_at_percentage):
                tp_percentage = self.take_profit_at_percentage[self.take_profit_index]
                tp_amount = self.take_profit_amount_percentage[self.take_profit_index]

                print(f" - Próxima meta Take Profit: {tp_percentage}% (Venda de: {tp_amount}%)\n")

                # Condição para ativação do take profit
                if (
                    self.actual_trade_position  # Só executa se estiver comprado
                    and tp_percentage > 0  # Apenas se o TP for maior que 0
                    and round(price_percentage_variation, 2) >= round(tp_percentage, 2)  # Se atingiu a meta de lucro
                ):
                    # Define a quantidade a ser vendida proporcionalmente
                    quantity_to_sell = self.last_stock_account_balance * (tp_amount / 100)

                    # Verifica se há uma quantidade válida para vender
                    if quantity_to_sell > 0:
                        log = (
                            f"🎯 Meta de Take Profit atingida! ({tp_percentage}% lucro)\n"
                            f" - Vendendo {tp_amount}% da carteira...\n"
                            f" - Preço atual: {close_price:.4f}\n"
                            f" - Quantidade vendida: {quantity_to_sell:.6f} {self.stock_code}"
                        )

                        print(log)
                        logging.info(log)

                        # Tenta executar a venda
                        order_result = self.sellMarketOrder(quantity=quantity_to_sell)

                        # Verifica se a ordem foi executada com sucesso
                        if order_result and "status" in order_result and order_result["status"] == "FILLED":
                            self.take_profit_index += 1
                            print(f"✅ Take Profit {tp_percentage}% realizado com sucesso! Avançando para a próxima meta.")
                            return True  # 🚀 Retorna True indicando que o take profit foi executado

                        else:
                            print(f"❌ Falha ao executar a ordem de venda. Tentando novamente na próxima rodada.")
                            return False  # Falhou na venda, retorna False

                    else:
                        print("⚠️ Quantidade de venda inválida. Take profit não executado.")
                        return False  # Retorna False pois não conseguiu executar a venda

            else:
                print("ℹ️ Todas as metas de take profit já foram atingidas.")
                return False  # Retorna False se todas as metas já foram atingidas

        except Exception as e:
            logging.error(f"Erro no take profit: {e}")
            print(f"❌ Erro no take profit: {e}")
            return False  # Retorna False se houver erro

    # --------------------------------------------------------------

    # Não usada por enquanto
    def create_order(
        self,
        _symbol,
        _side,
        _type,
        _quantity,
        _timeInForce=None,
        _limit_price=None,
        _stop_price=None,
    ):
        order_buy = TraderOrder.create_order(
            self.client_binance,
            _symbol=_symbol,
            _side=_side,  # Compra
            _type=_type,  # Ordem Limitada
            _timeInForce=_timeInForce,  # Good 'Til Canceled (Ordem válida até ser cancelada)
            _quantity=_quantity,
            _limit_price=_limit_price,
            _stop_price=_stop_price,
        )

        return order_buy

    # --------------------------------------------------------------
    # EXECUTE

    # Função principal e a única que deve ser execuda em loop, quando o
    # robô estiver funcionando normalmente
    def execute(
        self,
    ):
        print("------------------------------------------------")
        print(f'🟢 Executado {datetime.now().strftime("(%H:%M:%S) %d-%m-%Y")}\n')  # Adiciona o horário atual formatado

        # Atualiza todos os dados
        self.updateAllData(verbose=True)

        print("\n-------")
        print("Detalhes:")
        print(f' - Posição atual: {"Comprado" if self.actual_trade_position else "Vendido"}')
        print(f" - Balanço atual: {self.last_stock_account_balance:.4f} ({self.stock_code})")

        # ---------
        # Estratégias sentinelas de saída

        # Stop Loss
        # Se perder mais que o stop loss aceitável, ele sai à mercado, independente.
        if self.stopLossTrigger():
            print("\n🟢 STOP LOSS finalizado.\n")
            return

        # Take Profit
        if self.actual_trade_position == True and self.takeProfitTrigger():
            print("\n🟢 TAKE PROFIT finalizado.\n")
            return

        # ---------
        # Calcula a melhor estratégia para a decisão final
        self.last_trade_decision = self.getFinalDecisionStrategy()

        # ---------
        # Verifica ordens anteriores abertas
        if self.last_trade_decision == True:  # Se a decisão for COMPRA
            # Existem ordens de compra abertas?
            if self.hasOpenBuyOrder():  # Sim e salva possíveis quantidades executadas incompletas.
                self.cancelAllOrders()  # Cancela todas ordens
                time.sleep(2)

        if self.last_trade_decision == False:  # Se a decisão for VENDA
            # Existem ordens de venda abertas?
            if self.hasOpenSellOrder():  # Sim e salva possíveis quantidades executadas incompletas.
                self.cancelAllOrders()  # Cancela todas ordens
                time.sleep(2)

        # ---------
        print("\n--------------")
        print(
            f'🔎 Decisão Final: {"Comprar" if self.last_trade_decision == True else "Vender" if self.last_trade_decision == False else "Inconclusiva"}'
        )

        # ---------
        # Se a posição for vendida (false) e a decisão for de compra (true), compra o ativo
        # Se a posição for comprada (true) e a decisão for de venda (false), vende o ativo
        if self.actual_trade_position == False and self.last_trade_decision == True:
            print("🏁 Ação final: Comprar")
            print("--------------")
            print(f"\nCarteira em {self.stock_code} [ANTES]:")
            self.printStock()
            self.buyLimitedOrder()
            time.sleep(2)
            self.updateAllData()
            print(f"Carteira em {self.stock_code} [DEPOIS]:")
            self.printStock()
            self.time_to_sleep = self.delay_after_order

        elif self.actual_trade_position == True and self.last_trade_decision == False:
            print("🏁 Ação final: Vender")
            print("--------------")
            print(f"\nCarteira em {self.stock_code} [ANTES]:")
            self.printStock()
            self.sellLimitedOrder()
            time.sleep(2)
            self.updateAllData()
            print(f"\nCarteira em {self.stock_code} [DEPOIS]:")
            self.printStock()
            self.time_to_sleep = self.delay_after_order

        else:
            print(f'🏁 Ação final: Manter posição ({"Comprado" if self.actual_trade_position else "Vendido"})')
            print("--------------")
            self.time_to_sleep = self.time_to_trade

        print("------------------------------------------------")
