class StrategyRunner:

    @staticmethod
    def execute(
        bot,
        main_strategy,
        fallback_strategy,
        stock_data,
        main_strategy_args=None,
        fallback_strategy_args=None,
        verbose=True,
    ):
        """
        Executa a estratégia principal e, se necessário, a estratégia de fallback.

        :param bot: Instância de BinanceTraderBot (usa fallback_activated).
        :param main_strategy: Função da estratégia principal.
        :param fallback_strategy: Função da estratégia secundária (fallback).
        :param stock_data: Dados do ativo.
        :param main_strategy_args: Dicionário com argumentos extras para a estratégia principal.
        :param fallback_strategy_args: Dicionário com argumentos extras para a estratégia de fallback.
        :return: Decisão final da estratégia.
        """
        main_args = {**(main_strategy_args or {})}
        main_args["stock_data"] = stock_data
        main_args["verbose"] = verbose

        final_decision = main_strategy(**main_args)

        if final_decision is None and bot.fallback_activated:
            print("Estratégia principal inconclusiva\nExecutando estratégia de fallback...")

            fallback_args = {**(fallback_strategy_args or {})}
            fallback_args["stock_data"] = stock_data
            fallback_args["verbose"] = verbose

            final_decision = fallback_strategy(**fallback_args)

        return final_decision
