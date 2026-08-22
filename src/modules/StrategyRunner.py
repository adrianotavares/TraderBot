from strategies.decision import StrategyDecision


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
    ) -> StrategyDecision:
        main_args = {**(main_strategy_args or {})}
        main_args["stock_data"] = stock_data
        main_args["verbose"] = verbose

        decision = StrategyDecision.from_raw(
            main_strategy(**main_args),
            source="main",
        )

        if decision.side is None and bot.fallback_activated:
            print(
                "Estratégia principal inconclusiva\n"
                "Executando estratégia de fallback..."
            )
            fallback_args = {**(fallback_strategy_args or {})}
            fallback_args["stock_data"] = stock_data
            fallback_args["verbose"] = verbose
            decision = StrategyDecision.from_raw(
                fallback_strategy(**fallback_args),
                source="fallback",
                reason="main inconclusive",
            )

        return decision
