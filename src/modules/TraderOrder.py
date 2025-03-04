import logging


class TraderOrder:

    def create_order(
        client_binance,
        _symbol,
        _side,
        _type,
        _quantity,
        _timeInForce=None,
        _limit_price=None,
        _stop_price=None,
    ):
        ordemExecute = 0

        try:
            print(
                f"[create_order] _symbol: '{_symbol}',_side: '{_side}',_type: '{_type}',_quantity: '{_quantity}',_timeInForce: '{_timeInForce}',_limit_price: '{_limit_price}',_stop_price: '{_stop_price}'"
            )

            if _limit_price is None and _stop_price is None:
                ordemExecute = 1
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,
                    type=_type,
                    quantity=_quantity,
                )
            elif _limit_price is not None and _stop_price is None:
                ordemExecute = 2
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,  # Compra
                    type=_type,  # Ordem Limitada
                    timeInForce=_timeInForce,  # Good 'Til Canceled (Ordem válida até ser cancelada)
                    quantity=_quantity,
                    price=round(_limit_price, 2),
                )
            elif _limit_price is not None and _stop_price is None:
                ordemExecute = 3
                order_buy = client_binance.create_order(
                    symbol=_symbol,
                    side=_side,
                    type=_type,
                    timeInForce=_timeInForce,
                    quantity=_quantity,
                    price=round(_limit_price, 2),  # Preço limite ajustado
                    stopPrice=round(_stop_price, 2),  # Preço de disparo ajustado
                )
        except Exception as e:
            print(
                f"[create_order][ERROR]({ordemExecute}) _symbol: '{_symbol}',_side: '{_side}',_type: '{_type}',_quantity: '{_quantity}',_timeInForce: '{_timeInForce}',_limit_price: '{_limit_price}',_stop_price: '{_stop_price}'"
            )
            logging.error(
                f"[create_order][ERROR]({ordemExecute}) Erro ao enviar ordem ({ordemExecute}): {e}"
            )
            print(
                f"[create_order][ERROR]({ordemExecute}) Erro ao enviar ordem STOP_LOSS_LIMIT de venda ({ordemExecute}): {e}"
            )

        return order_buy
