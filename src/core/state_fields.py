class EngineStateField:
    """Descriptor: bot.X reads/writes engine.state so there is one persisted copy."""

    def __init__(self, name: str, default):
        self.name = name
        self.default = default

    def __get__(self, obj, owner):
        if obj is None:
            return self
        engine = getattr(obj, "engine", None)
        if engine is not None:
            return getattr(engine.state, self.name)
        return obj.__dict__.get(self.name, self.default)

    def __set__(self, obj, value):
        engine = getattr(obj, "engine", None)
        if engine is not None:
            setattr(engine.state, self.name, value)
            return
        obj.__dict__[self.name] = value


class PersistedTradeFields:
    last_trade_decision = EngineStateField("last_trade_decision", None)
    last_buy_price = EngineStateField("last_buy_price", 0.0)
    last_sell_price = EngineStateField("last_sell_price", 0.0)
    actual_trade_position = EngineStateField("actual_trade_position", False)
    take_profit_index = EngineStateField("take_profit_index", 0)
