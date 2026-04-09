import requests
import time
import os

# Чтение отдельной переменной
TOKEN = os.getenv('BOT_TOKEN') #opros
chat_id = os.getenv('CHAT_ID') #opros, ниже значение меняется на полученное id

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

def send_poll(question, options, chat_id):
    """Отправляет опрос в чат и возвращает полный ответ API"""
    url = f'{BASE_URL}/sendPoll'
    params = {
        'chat_id': chat_id,
        'question': question,
        'options': json.dumps(options),
        'is_anonymous': False
    }
    try:
        response = requests.post(url, data=params, timeout=10)
        if response.status_code == 200:
            print("Опрос успешно отправлен")
            return response.json()  # Возвращаем полный JSON-ответ API
        else:
            print(f"Ошибка отправки опроса: {response.status_code}")
            return {'ok': False, 'error': f'HTTP {response.status_code}'}
    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети при отправке опроса: {e}")
        return {'ok': False, 'error': str(e)}

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
        send_message(chat_id, 'Привет!')
        
    elif text == '/send_poll':
        send_message(chat_id, 'it`ll send poll here!')
        send_poll(question="it will?", options=['yes', 'no'], chat_id)
        
    else:
        send_message(chat_id, 'Я понимаю только команду /hi or /send_poll')
        
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
