import requests
import os
import json
import logging
import time

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токенов
BOT_TOKEN = os.getenv('BOT_TOKEN')
ID_MAIN = os.getenv('ID_MAIN')  # использовать для служебных сообщений
GROUP_ID = os.getenv('group_id_main_small') # group_id_main_small  = "-1003425228475" 

with open('/app/my_folder/users.txt', 'r') as file:
    user_ids = [int(line.strip()) for line in file if line.strip()]

if not BOT_TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")

BASE_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# Хранилище данных пользователей (в реальном проекте используйте БД)
user_states = {}
STATE_TIMEOUT = 3600  # 1 час в секундах

def send_message(chat_id, text):
    """Отправляет сообщение в чат"""
    url = f'{BASE_URL}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None

def send_poll(question, options):
    """Отправляет опрос в чат"""
    url = f'{BASE_URL}/sendPoll'
    payload = {
        'chat_id': GROUP_ID,
        'question': question,
        'options': json.dumps(options),
        'is_anonymous': False
    }
    try:
        response = requests.post(url, data=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки опроса: {e}")
        return {'ok': False, 'error': str(e)}

def get_updates(offset=None):
    """Получает обновления от Telegram"""
    url = f'{BASE_URL}/getUpdates'
    params = {'timeout': 30, 'offset': offset}
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return None

def start_poll_creation(chat_id):
    """Начинает процесс создания опроса"""
    user_states[chat_id] = {
        'state': 'waiting_question',
        'created_at': time.time()
    }
    send_message(chat_id, "📝 Давайте создадим опрос!\n\nВведите вопрос для опроса:")

def handle_poll_dialog(chat_id, text):
    """ Проверка таймаута """
    if chat_id in user_states:
        if time.time() - user_states[chat_id]['created_at'] > STATE_TIMEOUT:
            del user_states[chat_id]
            send_message(chat_id, "⏰ Время ожидания истекло. Начните заново /create_poll")
            return
    
    """Обрабатывает диалог создания опроса"""
    state = user_states[chat_id]['state']

    if state == 'waiting_question':
        user_states[chat_id].update({
            'question': text,
            'options': [],
            'state': 'waiting_options'
        })
        send_message(
            chat_id,
            f"Отлично! Вопрос: \"{text}\"\n\n"
            "Теперь введите варианты ответов (по одному).\n"
            "Когда закончите, напишите \"готово\":"
        )

    elif state == 'waiting_options':
        if text.lower() in ['готово', 'done', 'finish']:
            options = user_states[chat_id]['options']
            if len(options) < 2:
                send_message(
                    chat_id,
                    "❌ Нужно минимум 2 варианта ответа!\n"
                    "начните заново /create_poll"
                )
                del user_states[chat_id]
            else:
                # Отправляем опрос
                result = send_poll(
                    question=user_states[chat_id]['question'],
                    options=options
                )
                if result.get('ok'):
                    # Отправляем уведомление заказчику опроса
                    send_message(chat_id, "✅ Опрос успешно создан!")
                    # Отправляем служебное уведомление администратору
                    send_message(ID_MAIN, "✅ Опрос успешно создан (уведомление администратору)")
                else:
                    send_message(chat_id, f"❌ Ошибка создания опроса: {result.get('error', 'Unknown')}")
                del user_states[chat_id]  # Очищаем состояние
        else:
            # Добавляем новый вариант ответа
            user_states[chat_id]['options'].append(text)
            send_message(
                chat_id,
                f"✅ Добавлен вариант: \"{text}\"\n"
                f"Текущие варианты ({len(user_states[chat_id]['options'])}):\n" +
                "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(user_states[chat_id]['options'])]) +
                "\n\nПродолжайте вводить варианты или напишите \"готово\""
            )

def handle_message(message):
    """Обрабатывает входящие сообщения"""
    chat_id = message['chat']['id']
    text = message.get('text', '').strip()

    logger.info(f"Сообщение от {chat_id}: {text}")

    if text == '/start':
        send_message(
            chat_id,
            "👋 Привет! Я бот для создания опросов.\n"
            "Используйте /create_poll для начала создания опроса"
        )
    elif text == '/create_poll':
        start_poll_creation(chat_id)
    elif chat_id in user_states:
        # Если пользователь в процессе создания опроса
        handle_poll_dialog(chat_id, text)
    else:
        send_message(
            chat_id,
            "Я понимаю команды:\n"
            "/start — начать работу\n"
            "/create_poll — создать опрос"
        )

def handle_polling(update):
    """Обработка событий опросов: получение ID проголосовавших и сохранение в файл"""
    if 'poll_answer' in update:
        poll_answer = update['poll_answer']
        user_id = poll_answer['user']['id']
        poll_id = poll_answer['poll_id']
        option_ids = poll_answer.get('option_ids', [])

        logger.info(f"Голосование: опрос {poll_id}, пользователь {user_id}, варианты {option_ids}")

        
def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота для создания опросов...")
    send_message(ID_MAIN, "опрос_бот запущен (long polling)...")
    offset = None

    while True:
        try:
            updates = get_updates(offset)

            if updates and updates.get('ok') and updates.get('result'):
                for update in updates['result']:
                    offset = update['update_id'] + 1

                    # Получаем chat_id и type из обновления, если возможно
                    chat_id = None
                    chat_type = None

                    if 'message' in update:
                        message = update['message']
                        chat = message['chat']
                        chat_id = chat['id']
                        chat_type = chat['type']

                        # Обрабатываем только приватные чаты
                        if chat_type == 'private' and chat_id in user_ids:
                            handle_message(message)
                        else:     
                            send_message(chat_id, f"У вас нет доступа к боту. ваш id {chat_id} и {user_ids} и {type(user_ids[0])} и {type(chat_id)}")

                    # Обрабатываем ответы на опросы
                    elif 'poll_answer' in update:
                        handle_polling(update)

            time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            logger.error(f"Критическая ошибка: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
