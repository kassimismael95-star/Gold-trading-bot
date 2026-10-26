import os
import asyncio
from flask import Flask, request
from metaapi_cloud_sdk import MetaApi

app = Flask(__name__)

# Load tokens safely from environment variables
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
METAAPI_TOKEN = os.getenv('METAAPI_TOKEN')

@app.route('/')
def home():
    return "Gold Trading Bot is running!"

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def telegram_webhook():
    # Handle Telegram updates here
    return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
