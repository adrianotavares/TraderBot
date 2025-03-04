from dataclasses import dataclass, field
from typing import Callable, Dict, Optional


@dataclass
class StockStartModel:
    # fmt: off
    stockCode: str
    operationCode: str
    tradedQuantity: float
    candlePeriod: str
    tradedPercentage: float  = 100 # Ainda não implementado

    # Ajustes técnicos    
    fallBackActivated: bool = True          # Define se a estratégia de Fallback será usada (ela pode entrar comprada em mercados subindo)
    
    mainStrategy: Callable = None                                             # Estratégia principal
    mainStrategyArgs: Dict[str, any] = field(default_factory=dict)      # (opcional) Argumentos da estratégia principal
    fallbackStrategy: Optional[Callable] = None                         # (opcional) Estratégia de Fallback
    fallbackStrategyArgs: Dict[str, any] = field(default_factory=dict)  # (opcional) Argumentos da estratégia de fallback

    # Ajustes de Loss Protection
    acceptableLossPercentage: float = 0.5     # (Usar em base 100%) O quando o bot aceita perder de % (se for negativo, o bot só aceita lucro)
    stopLossPercentage: float = 3.5           # (Usar em base 100%) % Máxima de loss que ele aceita, em caso de não vender na ordem limitada

    # Ajustes de Take Profit
    takeProfitAtPercentage: list[float] = field(default_factory=list)        # (Usar em base 100%) Quanto de valorização para pegar lucro. (Array exemplo: [2, 5, 10])
    takeProfitAmountPercentage: list[float] = field(default_factory=list)    # (Usar em base 100%) Quanto da quantidade tira de lucro. (Array exemplo: [25, 25, 40])

    # Ajuste de tempos    
    tempoEntreTrades: int = 30 * 60         # Tempo que o bot espera para verificar o mercado (em segundos)
    delayEntreOrdens: int = 60 * 60         # Tempo que o bot espera depois de realizar uma ordem de compra ou venda (ajuda a diminuir trades de borda)


# fmt: on
