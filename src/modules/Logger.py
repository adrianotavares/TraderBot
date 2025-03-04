import logging
from datetime import datetime

# Configurar o logger
logging.basicConfig(
    filename='src/logs/trading_bot.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Printa e cria um log de ordem de compra ou venda.
# a partir do objeto retornado pela API da Binance
def createLogOrder(order):
    # Extraindo as informações necessárias
    side = order['side']
    type = order['type']
    quantity = order['executedQty']
    asset = order['symbol']
    total_value = order['cummulativeQuoteQty']
    timestamp = order['transactTime']
    status = order['status']
    price = order['price']

    price_per_unit = order.get('fills', [{}])[0].get('price', '-') if order.get('fills') else '-'
    currency = order.get('fills', [{}])[0].get('commissionAsset', '-') if order.get('fills') else '-'


    # Convertendo timestamp para data/hora legível
    datetime_transact = datetime.utcfromtimestamp(timestamp / 1000).strftime('(%H:%M:%S) %Y-%m-%d')

    # Criando as mensagens para log
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

    # Criando as mensagens para print
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
        # "\n"
        # "Complete_order:\n"
        # f"{order}"
        "\n-----------------------------------------\n"
    )

    # Exibindo no console
    print(print_message)

    # Registrando no log
    logging.info(log_message)

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


def getOrderStatus(order_status):
    status_translation = {
        "NEW": "ABERTA",
        "PARTIALLY_FILLED": "PARCIALMENTE EXECUTADA",
        "FILLED": "EXECUTADA",
        "CANCELED": "CANCELADA",
        "EXPIRED": "EXPIRADA"
    }

    return status_translation.get(order_status, "ERRO")
    