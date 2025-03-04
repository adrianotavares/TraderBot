class StrategyRunner:

    @staticmethod
    def execute(
        self, main_strategy, fallback_strategy, stock_data, main_strategy_args=None, fallback_strategy_args=None, verbose=True
    ):
        """
        Executa a estratégia principal e, se necessário, a estratégia de fallback.

        :param main_strategy: Função da estratégia principal.
        :param fallback_strategy: Função da estratégia secundária (fallback).
        :param stock_data: Dados do ativo.
        :param main_strategy_args: Dicionário com argumentos extras para a estratégia principal.
        :param fallback_strategy_args: Dicionário com argumentos extras para a estratégia de fallback.
        :return: Decisão final da estratégia.
        """
        # Define argumentos básicos para a estratégia principal
        main_strategy_args = main_strategy_args or {}  # Se não for passado, usa um dicionário vazio
        main_strategy_args["stock_data"] = stock_data  # stock_data sempre será passado
        main_strategy_args["verbose"] = verbose

        # Executa a estratégia principal
        final_decision = main_strategy(**main_strategy_args)

        # Se a estratégia principal for inconclusiva e a fallback estiver ativada
        if final_decision is None and self.fallback_activated:
            print("Estratégia principal inconclusiva\nExecutando estratégia de fallback...")

            # Define argumentos básicos para a fallback
            fallback_strategy_args = fallback_strategy_args or {}  # Se não for passado, usa um dicionário vazio
            fallback_strategy_args["stock_data"] = stock_data  # stock_data sempre será passado
            fallback_strategy_args["verbose"] = verbose

            final_decision = fallback_strategy(**fallback_strategy_args)

        return final_decision
