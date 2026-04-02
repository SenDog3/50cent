import requests
import time

# Замените 'YOUR_TOKEN' на реальный токен от BotFather
#TOKEN = OPROS_BOT
BASE_URL = f'https://api.telegram.org/bot{TOKEN}'

def send_message(chat_id, text):
    """Отправляет сообщение в чат"""
    url = f'{BASE_URL}/sendMessage'
    payload = {
        'chat_id': chat_id,
        'text': text
    }
    response = requests.post(url, json=payload)
    return response.json()

def get_updates(offset=None):
    """Получает обновления от Telegram"""
    url = f'{BASE_URL}/getUpdates'
    params = {'timeout': 30, 'offset': offset}
    response = requests.get(url, params=params)
    return response.json()

def handle_message(message):
    """Обрабатывает входящие сообщения"""
    chat_id = message['chat']['id']
    text = message.get('text', '').strip()

    if text == '/hi':
        send_message(chat_id, 'Привет! Я работаю!')
    else:
        send_message(chat_id, 'Я понимаю только команду /hi')

def main():
    """Основная функция запуска бота"""
    send_message(chat_id, "опрос_бот запущен (long polling)...")
    offset = None

    while True:
        try:
            updates = get_updates(offset)

            if updates.get('ok') and updates.get('result'):
                for update in updates['result']:
                    offset = update['update_id'] + 1
                    if 'message' in update:
                        handle_message(update['message'])

            time.sleep(1)  # Пауза между запросами

        except Exception as e:
            send_message(chat_id, f"Ошибка: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
