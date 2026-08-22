import logging
from datetime import datetime, timezone

from modules.logging_setup import log_event


def getOrderStatus(order_status):
    status_translation = {
        "NEW": "ABERTA",
        "PARTIALLY_FILLED": "PARCIALMENTE EXECUTADA",
        "FILLED": "EXECUTADA",
        "CANCELED": "CANCELADA",
        "EXPIRED": "EXPIRADA",
    }
    return status_translation.get(order_status, "ERRO")


# Printa e cria um log de ordem de compra ou venda.
# a partir do objeto retornado pela API da Binance
def createLogOrder(order):
    side = order["side"]
    type = order["type"]
    quantity = order["executedQty"]
    asset = order["symbol"]
    total_value = order["cummulativeQuoteQty"]
    timestamp = order["transactTime"]
    status = order["status"]
    price = order["price"]

    fills = order.get("fills") or [{}]
    price_per_unit = fills[0].get("price", "-")
    currency = fills[0].get("commissionAsset", "-")

    datetime_transact = datetime.fromtimestamp(
        timestamp / 1000, tz=timezone.utc
    ).strftime("(%H:%M:%S) %Y-%m-%d")

    log_message = (
        "\n--------------------\n"
        "ORDEM ENVIADA: \n"
        f"Status: {getOrderStatus(status)}\n"
        f"Side: {side}\n"
        f"Ativo: {asset}\n"
        f"Quantidade: {quantity}\n"
        f"Preço enviado: {price}\n"
        f"Valor na {'compra' if side == 'BUY' else 'venda'}: {price_per_unit}\n"
        f"Moeda: {currency}\n"
        f"Total em {currency}: {total_value}\n"
        f"Type: {type}\n"
        f"Data/Hora: {datetime_transact}\n"
        "\n"
        "Complete_order:\n"
        f"{order}"
        "\n-----------------------------------------\n"
    )

    print_message = (
        "\n--------------------\n"
        "ORDEM ENVIADA: \n"
        f"Status: {getOrderStatus(status)}\n"
        f"Side: {side}\n"
        f"Ativo: {asset}\n"
        f"Quantidade: {quantity}\n"
        f"Preço enviado: {price}\n"
        f"Valor na {'compra' if side == 'BUY' else 'venda'}: {price_per_unit}\n"
        f"Moeda: {currency}\n"
        f"Valor em {currency}: {total_value}\n"
        f"Type: {type}\n"
        f"Data/Hora: {datetime_transact}\n"
        "\n-----------------------------------------\n"
    )

    print(print_message)
    logging.info(log_message)

    fill_price = None
    try:
        fill_price = float(price_per_unit)
    except (TypeError, ValueError):
        pass

    log_event(
        logging.INFO,
        f"Ordem {getOrderStatus(status)}: {side} {asset}",
        event="order_executed",
        operation_code=asset,
        side=side,
        order_type=type,
        status=status,
        status_label=getOrderStatus(status),
        quantity=float(quantity or 0),
        price_sent=float(price or 0),
        fill_price=fill_price,
        total_quote=float(total_value or 0),
        commission_asset=currency,
        order_id=order.get("orderId"),
        transact_time=datetime_transact,
    )

# # Exemplo de uso
# if __name__ == "__main__":
#     order_sell = {
#         'symbol': 'SOLBRL',
#         'orderId': 180636560,
#         'orderListId': -1,
#         'clientOrderId': 'x-asdasd',
#         'transactTime': 1733438637638,
#         'price': '0.00000000',
#         'origQty': '0.19900000',
#         'executedQty': '0.19900000',
#         'cummulativeQuoteQty': '279.21690000',
#         'status': 'FILLED',
#         'timeInForce': 'GTC',
#         'type': 'MARKET',
#         'side': 'SELL',
#         'workingTime': 1733438637638,
#         'fills': [
#             {
#                 'price': '1403.10000000',
#                 'qty': '0.19900000',
#                 'commission': '0.27921690',
#                 'commissionAsset': 'BRL',
#                 'tradeId': 4293074
#             }
#         ],
#         'selfTradePreventionMode': 'EXPIRE_MAKER'
#     }

#     createLogOrder(order_sell)
