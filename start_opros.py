#!/usr/bin/env python3
# coding: utf-8

import requests
import json
import os
#from dotenv import load_dotenv

#load_dotenv()  # Загружаем переменные из .env
bot_token = os.getenv("BOT_TOKEN")  # Получаем токен

#chat_id = "5169274483" # мой чат
#group_id = "-1003425228475" # маленькая группа

base_url = "https://api.telegram.org/bot{}/".format(bot_token)  # Исправлено: https://
OFFSET_FILE = 'last_update_id.json'
STATE_FILE = 'user_dialog_state.json'  # Файл для сохранения состояния диалога

def load_last_offset():
    """Загружает последний обработанный update_id из файла"""
    if os.path.exists(OFFSET_FILE):
        try:
            with open(OFFSET_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('last_update_id', 0)
        except (json.JSONDecodeError, IOError):
            return 0
    return 0

def save_last_offset(update_id):
    """Сохраняет последний обработанный update_id в файл"""
    try:
        with open(OFFSET_FILE, 'w', encoding='utf-8') as f:
            json.dump({'last_update_id': update_id}, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Ошибка сохранения offset: {e}")

def load_user_state():
    """Загружает состояние диалога из файла"""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}
    return {}

def save_user_state(state):
    """Сохраняет состояние диалога в файл"""
    try:
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Ошибка сохранения состояния диалога: {e}")

def send_poll(question, options, chat_id):
    """Отправляет опрос в чат и возвращает полный ответ API"""
    url = f"{base_url}sendPoll"
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

def send_message(text, chat_id):
    """Отправляет сообщение в чат"""
    url = f"{base_url}sendMessage"
    params = {'chat_id': chat_id, 'text': text}
    try:
        response = requests.post(url, data=params, timeout=10)
        if response.status_code == 200:
            return True
        else:
            print(f"Ошибка отправки сообщения: {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети: {e}")
        return False

def get_new_updates(offset):
    """Получает обновления с указанным offset"""
    url = f"{base_url}getUpdates"
    params = {'offset': offset, 'limit': 100}
    try:
        response = requests.get(url, params=params, timeout=10)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"Ошибка API: {response.status_code} - {response.text}")
            return None
    except requests.exceptions.RequestException as e:
        print(f"Ошибка сети: {e}")
        return None

def process_message(message, user_id, user_state):
    text = message['text']
    chat_id = message['chat']['id']
    current_state = user_state.get(str(user_id), {})

    if text.startswith('/send'):
        user_state[str(user_id)] = {'state': 'awaiting_poll_question'}
        save_user_state(user_state)
        send_message("Привет! Давайте создадим опрос. Введите вопрос для опроса:", chat_id)

    elif current_state:
        state_name = current_state['state']

        if state_name == 'awaiting_poll_question':
            user_state[str(user_id)] = {
                'state': 'awaiting_poll_options',
                'question': text
            }
            save_user_state(user_state)
            send_message("Теперь введите варианты ответов через запятую (например: Буду, Не буду):", chat_id)

        elif state_name == 'awaiting_poll_options':
            options = [opt.strip() for opt in text.split(',')]
            if len(options) < 2:
                send_message("Пожалуйста, введите минимум 2 варианта ответа через запятую:", chat_id)
                return

            # Отправляем опрос
            poll_response = send_poll(current_state['question'], options, group_id)
            if poll_response and poll_response.get('ok'):
                try:
                    message_id = poll_response['result']['message_id']
                    poll_id = poll_response['result']['poll']['id']
                    print(f"message_id: {message_id}")
                    print(f"poll_id: {poll_id}")
                except KeyError as e:
                    print(f"Ошибка извлечения данных из ответа API: отсутствует поле {e}")
                    send_message("Не удалось создать опрос. Попробуйте ещё раз.", chat_id)
                    return
            else:
                print("Не удалось получить данные опроса из ответа API")
                send_message("Не удалось создать опрос. Попробуйте ещё раз.", chat_id)
                return

            send_message("Опрос успешно создан!", chat_id)

            # Сбрасываем состояние пользователя
            del user_state[str(user_id)]
            save_user_state(user_state)
    else:
        print(f'Обычное сообщение: {text}')

def main():
    # Загружаем состояние диалога
    user_state = load_user_state()

    # Загружаем последний обработанный update_id
    last_update_id = load_last_offset()
    print(f"Проверяем обновления после update_id: {last_update_id}")

    # Получаем новые обновления
    data = get_new_updates(last_update_id + 1)

    if data and data.get('ok'):
        updates = data.get('result', [])

        if updates:
            # Находим максимальный update_id среди полученных
            max_update_id = max(update['update_id'] for update in updates)

            # Обрабатываем каждое сообщение
            for update in updates:
                message = update.get('message')
                if message and 'text' in message:
                    user_id = message['from']['id']
                    process_message(message, user_id, user_state)

            # Сохраняем максимальный update_id как последний обработанный
            save_last_offset(max_update_id)
            print(f"Обработано {len(updates)} сообщений. Последний update_id: {max_update_id}")
        else:
            print("Новых сообщений нет")
    else:
        print("Не удалось получить обновления")

if __name__ == '__main__':
    main()
