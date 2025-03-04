import pandas as pd
from binance.client import Client
import os

# Replace with your API keys (or use None for public access)
API_KEY = os.getenv("BINANCE_API_KEY")
API_SECRET = os.getenv("BINANCE_SECRET_KEY")

# Initialize Binance Client
client = Client(API_KEY, API_SECRET)

# Get recent trades for BTC/USDT
symbol = "BTCUSDT"
limit = 10  # Number of recent trades to fetch
trades = client.get_recent_trades(symbol=symbol, limit=limit)

# Convert to Pandas DataFrame
df = pd.DataFrame(trades)

# Select relevant columns and convert timestamp
df = df[['id', 'price', 'qty', 'quoteQty', 'time', 'isBuyerMaker']]
df['time'] = pd.to_datetime(df['time'], unit='ms')  # Convert timestamp to readable format

# Display the DataFrame
print(df)
