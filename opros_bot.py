import requests
import json
import os
import re
import logging
import time

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Получение токенов и настроек из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ID_MAIN = os.getenv('ID_MAIN')  # для служебных сообщений
GROUP_ID = os.getenv('group_id_main_small')  # group_id_маленькая_моя

# Путь для хранения данных (user_id: позывной)
DATA_FILE = '/app/data/pozyvn/user_callsigns.json'

# Проверка обязательных переменных окружения
if not BOT_TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")

BASE_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# Загружаем существующие данные из файла (если есть)
user_callsigns = {}
if os.path.exists(DATA_FILE):
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        try:
            user_callsigns = json.load(f)
            logger.info(f"Загружено {len(user_callsigns)} записей из {DATA_FILE}")
        except json.JSONDecodeError:
            logger.error("Файл данных повреждён, создаём новый словарь")
            user_callsigns = {}

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

def save_data():
    """Сохраняет словарь user_id: позывной в файл"""
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_callsigns, f, ensure_ascii=False, indent=2)
    logger.info(f"Данные сохранены. Всего записей: {len(user_callsigns)}")

def handle_message(message):
    """Обрабатывает входящее сообщение (только private)"""
    chat = message['chat']

    # Игнорируем не приватные чаты
    if chat['type'] != 'private':
        return

    chat_id = chat['id']
    user_id = str(message['from']['id'])
    text = message.get('text', '').strip()

    logger.info(f"Получено сообщение от user_id {user_id}: '{text}'")

    # Проверяем, что сообщение содержит только одно слово из кириллических букв
    if re.fullmatch(r'^[а-яёА-ЯЁ]+$', text):
        # Переводим в строчные буквы
        callsign = text.lower()

        # Проверяем, есть ли уже такой user_id в словаре
        if user_id in user_callsigns:
            existing_callsign = user_callsigns[user_id]
            send_message(
                chat_id,
                f"⚠️ У вас уже зарегистрирован позывной: '{existing_callsign}'.\n"
                "Обратись к админу."
            )
            logger.info(f"Пользователь {user_id} попытался отправить новый позывной, но уже зарегистрирован")
        else:
            # Сохраняем новый позывной
            user_callsigns[user_id] = callsign
            save_data()
            send_message(
                chat_id,
                f"✅ Позывной '{callsign}' успешно сохранён!"
            )
            logger.info(f"Сохранён новый позывной для user_id {user_id}: '{callsign}'")

            # Отправляем служебное сообщение администратору о внесении в файл позывного
            if ID_MAIN:
                send_message(
                    ID_MAIN,
            f"📝 Новый позывной добавлен:\n"
            f"User ID: {user_id}\n"
            f"Позывной: {callsign}"
        )
    else:
        # Если сообщение не соответствует формату позывного
        send_message(
            chat_id,
            "❌ Неверный формат позывного.\n"
            "Позывной должен:\n"
            "• состоять из одного слова\n"
            "• содержать только кириллические буквы"
        )
        logger.info(f"Некорректный позывной от user_id {user_id}: '{text}'")

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

def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота для сбора позывных...")

    # Отправляем служебное сообщение администратору о запуске
    if ID_MAIN:
        send_message(ID_MAIN, "Бот позывных запущен!")

    offset = None

    while True:
        try:
            updates = get_updates(offset)
            if updates is None:
                time.sleep(5)  # пауза при ошибке получения обновлений
                continue

            if updates and updates.get('ok') and updates.get('result'):
                for update in updates['result']:
                    offset = update['update_id'] + 1

                    if 'message' in update:
                        message = update['message']
                        handle_message(message)

            time.sleep(1)

        except KeyboardInterrupt:
            logger.info("Бот остановлен пользователем")
            break
        except Exception as e:
            logger.critical(f"Критическая ошибка: {e}")
            time.sleep(5)

if __name__ == '__main__':
    main()
