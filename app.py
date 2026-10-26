@app.route(f'/{TELEGRAM_TOKEN}', methods=['POST'])
def telegram_webhook():
    data = request.get_json()
    if data and 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')
        
        if text == '/start':
            reply_text = (
                "🤖 *Gold Scalper Cruise Control* is online and active!\n\n"
                "Your cloud engine is ready. Open your Web App panel to connect your MT5 account and start trading."
            )
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            requests.post(url, json={
                "chat_id": chat_id, 
                "text": reply_text, 
                "parse_mode": "Markdown"
            })
            
    return jsonify({"status": "ok"})
