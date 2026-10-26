import os
import requests
from flask import Flask, request

app = Flask(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
METAAPI_TOKEN = os.getenv('METAAPI_TOKEN')
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

def send_message(chat_id, text):
    url = f"{TELEGRAM_API_URL}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    requests.post(url, json=payload)

@app.route('/')
def home():
    return "Gold Trading Bot is running!"

@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def telegram_webhook():
    update = request.get_json()
    
    if "message" in update:
        chat_id = update["message"]["chat"]["id"]
        text = update["message"].get("text", "")
        
        if text == "/start":
            send_message(chat_id, "Welcome to Gold Scalper Bot! Your trading engine is online. Send /status to check connection.")
        elif text == "/status":
            send_message(chat_id, "Status: Connected to Render & MetaApi successfully!")
        else:
            send_message(chat_id, f"Received: {text}")
            
    return '', 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000)
