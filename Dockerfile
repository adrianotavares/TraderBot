FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PYTHONPATH=/app/src
ENV TRADING_CONFIG=/app/config/trading.yaml

CMD ["python", "src/main.py"]
