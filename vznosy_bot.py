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

# Получение токенов из переменных окружения
BOT_TOKEN = os.getenv('BOT_TOKEN')
ID_MAIN = os.getenv('ID_MAIN')  # для служебных сообщений

# Путь для хранения данных (изменён с /app/shared/ на /app/data/)
VZNOS_DATA_FILE = '/app/data/vznosy_user_data.json'

# Проверка обязательных переменных окружения
if not BOT_TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")

BASE_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

# Список доступных секторов
SECTORS_LIST = [
    "ЧКЗю", "ОТК", "Ясенево"
]

# Загружаем существующие данные из файла (если есть)
user_data = {}
if os.path.exists(VZNOS_DATA_FILE):
    with open(VZNOS_DATA_FILE, 'r', encoding='utf-8') as f:
        try:
            user_data = json.load(f)
            logger.info(f"Загружено {len(user_data)} записей из {VZNOS_DATA_FILE}")
        except json.JSONDecodeError:
            logger.error("Файл данных повреждён, создаём новый словарь")
            user_data = {}

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
    """Сохраняет словарь user_id: данные в файл"""
    with open(VZNOS_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(user_data, f, ensure_ascii=False, indent=2)
    logger.info(f"Данные сохранены. Всего записей: {len(user_data)}")

def validate_sector(sector):
    """Проверяет, есть ли сектор в списке доступных"""
    return sector in SECTORS_LIST

def validate_callsign(callsign):
    """Проверяет позывной: кириллица, одно слово"""
    return bool(re.fullmatch(r'^[а-яёА-ЯЁ]+$', callsign))

def validate_amount(amount_str):
    """Проверяет, что строка является числом и преобразует в целое (дробная часть отбрасывается)"""
    try:
        float_value = float(amount_str)
        int_value = int(float_value)  # отбрасываем дробную часть
        return True, int_value
    except ValueError:
        return False, None

def validate_telegram_username(username):
    """Проверяет, что никнейм начинается с @"""
    return bool(re.fullmatch(r'^@[a-zA-Z0-9_]{5,}$', username))

def handle_message(message):
    """Обрабатывает входящее сообщение"""
    chat_id = message['chat']['id']
    user_id = str(message['from']['id'])
    text = message.get('text', '').strip()

    logger.info(f"Получено сообщение от user_id {user_id}: '{text}'")

    # Разделяем сообщение на части (сектор, позывной, сумма, никнейм)
    parts = text.split()
    if len(parts) != 4:
        send_message(
            chat_id,
            "❌ Неверный формат данных.\n"
            "Введите в формате:\n"
            "<сектор> <позывной> <сумма> <никнейм_телеграм>\n\n"
            f"Доступные сектора: {', '.join(SECTORS_LIST)}"
        )
        return

    sector, callsign, amount_str, username = parts

    # Валидация всех полей
    errors = []

    if not validate_sector(sector):
        errors.append(f"Неверный сектор. Доступные: {', '.join(SECTORS_LIST)}")
    if not validate_callsign(callsign):
        errors.append("Позывной должен быть одним словом на кириллице")
    is_valid_amount, amount = validate_amount(amount_str)
    if not is_valid_amount:
        errors.append("Сумма должна быть числом")
    if not validate_telegram_username(username):
        errors.append("Никнейм должен начинаться с @ и содержать только латинские буквы, цифры и _")

    if errors:
        error_text = "❌ Ошибки в данных:\n" + "\n".join(f"• {err}" for err in errors)
        send_message(chat_id, error_text)
        return

    # Сохраняем данные (сумма — целое число)
    user_data[user_id] = {
        'sector': sector,
        'callsign': callsign.lower(),
        'amount': amount,
        'telegram_username': username
    }
    save_data()

    # Отправляем подтверждение пользователю
    send_message(
        chat_id,
        f"✅ Данные успешно сохранены!\n\n"
        f"Сектор: {sector}\n"
        f"Позывной: {callsign.lower()}\n"
        f"Сумма: {amount}\n"
        f"Никнейм: {username}"
    )

    # Отправляем служебное сообщение администратору с количеством строк
    if ID_MAIN:
        send_message(
            ID_MAIN,
            f"📝 Новые данные добавлены:\n"
            f"User ID: {user_id}\n"
            f"Сектор: {sector}\n"
            f"Позывной: {callsign.lower()}\n"
            f"Сумма: {amount}\n"
            f"Никнейм: {username}\n\n"
            f"Всего записей в базе: {len(user_data)}"
        )
    logger.info(f"Сохранены данные для user_id {user_id}")


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
    logger.info("Запуск бота для сбора данных...")

    # Отправляем служебное сообщение администратору о запуске
    if ID_MAIN:
        send_message(ID_MAIN, "Бот сбора данных запущен!")

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
