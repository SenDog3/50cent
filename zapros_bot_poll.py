import requests
import os
import json
import logging
import time
import threading
import psycopg2
from urllib.parse import urlparse

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токенов
BOT_TOKEN = os.getenv('BOT_TOKEN')
ID_MAIN = os.getenv('ID_MAIN')
GROUP_ID = os.getenv('group_id_main_small')
VOTES_DIR = '/app/data/votes_by_poll/'
ACTUAL_IDS_PATH = '/app/data/pozyvn/dict_id_pozyv.txt'
thread_id = 42

BASE_URL = f'https://api.telegram.org/bot{BOT_TOKEN}'

user_states = {}
STATE_TIMEOUT = 3600

# Файл кто допущен объявлять голосование
with open('/app/data/admins_for_create_poll.txt', 'r') as file:
    user_ids = [int(line.strip()) for line in file if line.strip()]

if not BOT_TOKEN:
    raise ValueError("Установите переменную окружения BOT_TOKEN")


# ============================================================
#  РАБОТА С БАЗОЙ ДАННЫХ
# ============================================================

def get_db_conn():
    """Создаёт подключение к базе."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL не задана")
    return psycopg2.connect(url)


def init_db():
    """Создаёт таблицы в БД, если их ещё нет."""
    conn = get_db_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS polls (
            poll_id        TEXT PRIMARY KEY,
            message_id    BIGINT NOT NULL,
            chat_id       BIGINT NOT NULL,
            question      TEXT,
            duration_days INT,
            created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            closed        BOOLEAN DEFAULT FALSE
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS poll_votes (
            id       SERIAL PRIMARY KEY,
            poll_id  TEXT NOT NULL REFERENCES polls(poll_id) ON DELETE CASCADE,
            user_id  BIGINT NOT NULL,
            UNIQUE (poll_id, user_id)
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS shared_settings (
            key        VARCHAR(255) PRIMARY KEY,
            value      TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    logger.info("✅ Таблицы в БД проверены/созданы")


def db_health_check():
    """Простая проверка доступности БД."""
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        logger.info("✅ База данных доступна")
        return True
    except Exception as e:
        logger.error(f"💥 База недоступна: {e}")
        return False


def save_poll_to_db(poll_id, message_id, chat_id, question, duration_days):
    """Сохраняет опрос в базу."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO polls (poll_id, message_id, chat_id, question, duration_days)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (poll_id) DO NOTHING;
    """, (poll_id, message_id, chat_id, question, duration_days))
    conn.commit()
    cur.close()
    conn.close()


def save_vote_to_db(poll_id, user_id):
    """Сохраняет голос в базу (без дубликатов)."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO poll_votes (poll_id, user_id)
        VALUES (%s, %s)
        ON CONFLICT (poll_id, user_id) DO NOTHING;
    """, (poll_id, user_id))
    conn.commit()
    cur.close()
    conn.close()
    logger.debug(f"Голос сохранён: poll={poll_id}, user={user_id}")


def get_poll_from_db(poll_id):
    """Возвращает данные опроса из базы."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        SELECT message_id, chat_id, question, duration_days, created_at, closed
        FROM polls WHERE poll_id = %s;
    """, (poll_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    return row


def mark_poll_closed(poll_id):
    """Помечает опрос как закрытый."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("UPDATE polls SET closed = TRUE WHERE poll_id = %s;", (poll_id,))
    conn.commit()
    cur.close()
    conn.close()


def get_voted_user_ids(poll_id):
    """Возвращает множество ID проголосовавших."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM poll_votes WHERE poll_id = %s;", (poll_id,))
    rows = cur.fetchall()
    cur.close()
    conn.close()
    return {row[0] for row in rows}


def restore_pending_polls():
    """При старте бота восстанавливает незакрытые опросы."""
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("SELECT poll_id, message_id, chat_id, question, duration_days, created_at FROM polls WHERE closed = FALSE;")
    rows = cur.fetchall()
    cur.close()
    conn.close()

    if not rows:
        logger.info("Нет незакрытых опросов для восстановления")
        return

    logger.info(f"Найдено {len(rows)} незакрытых опросов, восстанавливаем...")

    for row in rows:
        poll_id, message_id, chat_id, question, duration_days, created_at = row

        elapsed = (time.time() - created_at.timestamp())
        total_duration = duration_days * 24 * 60 * 60
        remaining = total_duration - elapsed

        if remaining <= 0:
            logger.info(f"Опрос {poll_id} уже просрочен, закрываем немедленно")
            _do_close_poll(poll_id, chat_id, message_id)
        else:
            logger.info(f"Опрос {poll_id}: осталось {remaining / 3600:.1f} часов, запускаем таймер")
            timer_thread = threading.Thread(
                target=_close_poll_timer,
                args=(poll_id, chat_id, message_id, remaining),
                daemon=True
            )
            timer_thread.start()


# ============================================================
#  ОТПРАВКА СООБЩЕНИЙ И ОПРОСОВ
# ============================================================

def send_message(chat_id, text):
    """Отправляет сообщение в чат."""
    url = f'{BASE_URL}/sendMessage'
    payload = {'chat_id': chat_id, 'text': text}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки сообщения: {e}")
        return None
    
def send_document(chat_id, file_path, caption=None):
    """Отправляет файл в чат."""
    url = f'{BASE_URL}/sendDocument'
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': chat_id}
            if caption:
                data['caption'] = caption
            response = requests.post(url, data=data, files=files, timeout=10)
            return response.json()
    except Exception as e:
        logger.error(f"Ошибка отправки файла: {e}")
        return None

def send_poll(question, options, duration_days):
    
    url = f'{BASE_URL}/sendPoll'
    payload = {
        'chat_id': GROUP_ID,
        'question': question,
        'options': options,
        'is_anonymous': False,
        'message_thread_id': thread_id
    }

    try:
        response = requests.post(url, json=payload, timeout=10)
        poll_result = response.json()

        if poll_result.get('ok'):
            poll_message_id = poll_result['result']['message_id']
            poll_id = poll_result['result']['poll']['id']

            # Сохраняем в базу (duration_days уже перезаписан)
            #save_poll_to_db(poll_id, poll_message_id, GROUP_ID, question, duration_days)
            
            # Было (где-то в send_poll):
            #save_poll_to_db(poll_id, poll_message_id, GROUP_ID, question, duration_days)

            # Стало (временно для теста):
            test_minutes = 10
            save_poll_to_db(poll_id, poll_message_id, GROUP_ID, question, test_minutes / 1440)
            
            

            logger.info(f"Опрос отправлен, message_id: {poll_message_id}, poll_id: {poll_id}, срок: {duration_days:.4f} дней")

            # Запускаем таймер закрытия
            timer_thread = threading.Thread(
                target=_close_poll_timer,
                #args=(poll_id, GROUP_ID, poll_message_id, duration_days * 24 * 60 * 60),
                
                # Было:
                #args=(poll_id, GROUP_ID, poll_message_id, duration_days * 24 * 60 * 60),

                # Стало:
                args=(poll_id, GROUP_ID, poll_message_id, test_minutes * 60),

                
                
                daemon=True
            )
            timer_thread.start()
            return poll_result
        else:
            logger.error(f"API Telegram вернул ошибку: {poll_result}")
            return {'ok': False, 'error': f'Telegram API error: {poll_result}'}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при отправке опроса: {e}")
        return {'ok': False, 'error': str(e)}

# ============================================================
#  ЗАКРЫТИЕ ОПРОСОВ
# ============================================================

def _close_poll_timer(poll_id, chat_id, message_id, remaining_seconds):
    """Ждёт оставшееся время, затем закрывает опрос."""
    if remaining_seconds > 0:
        logger.info(f"Таймер опроса {poll_id}: ждём {remaining_seconds / 3600:.1f} часов")
        time.sleep(remaining_seconds)
    _do_close_poll(poll_id, chat_id, message_id)


def _do_close_poll(poll_id, chat_id, message_id):
    """Закрывает опрос через Telegram API и запускает постобработку."""
    # Проверяем, не закрыт ли уже
    poll_data = get_poll_from_db(poll_id)
    if poll_data and poll_data[5]:  # closed == True
        logger.info(f"Опрос {poll_id} уже закрыт, пропускаем")
        return

    url = f'{BASE_URL}/stopPoll'
    payload = {
        'chat_id': chat_id,
        'message_id': message_id,
        'message_thread_id': thread_id
    }

    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        result = response.json()

        if result.get('ok'):
            mark_poll_closed(poll_id)
            logger.info(f"Опрос {poll_id} (message_id: {message_id}) закрыт")
            send_post_closure_notifications(poll_id)
        else:
            logger.error(f"Ошибка закрытия опроса {poll_id}: {result.get('description')}")
    except Exception as e:
        logger.error(f"Ошибка при закрытии опроса {poll_id}: {e}")


# ============================================================
#  УВЕДОМЛЕНИЯ И СПИСКИ
# ============================================================

def get_missing_voters_list(poll_id):
    """Возвращает список ID пользователей, не проголосовавших в опросе."""
    try:
        with open(ACTUAL_IDS_PATH, 'r', encoding='utf-8') as file:
            dict_pozyvn = json.load(file)
        all_user_ids = set(int(key) for key in dict_pozyvn.keys())

        voted_ids = get_voted_user_ids(poll_id)
        missing_ids = all_user_ids - voted_ids
        return list(missing_ids)
    except Exception as e:
        logger.error(f"Ошибка получения списка не проголосовавших для опроса {poll_id}: {e}")
        return []


def send_post_closure_notifications(poll_id):
    """Отправляет уведомления не проголосовавшим после закрытия опроса."""
    logger.info(f"Отправка уведомлений для опроса {poll_id}")

    try:
        missing_users = get_missing_voters_list(poll_id)

        if not missing_users:
            logger.info(f"Все проголосовали в опросе {poll_id}, уведомления не нужны")
            return

        logger.info(f"Отправляем уведомления {len(missing_users)} пользователям")

        message_text = (
            "📣 Опрос завершён!\n\n"
            "К сожалению, вы не приняли участие в голосовании в moto.\n\n"
            "Это нарушение правил.\n"
            "Напишите админу Седому!"
        )

        sent_count = 0
        failed_count = 0

        for user_id in missing_users:
            try:
                send_message(user_id, message_text)
                sent_count += 1
                time.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                failed_count += 1

        logger.info(f"Уведомления: отправлено {sent_count}, ошибок {failed_count} (опрос {poll_id})")

        # --- НОВОЕ: создаём TXT и отправляем админу ---
        output_path = f'/app/data/txt_results/missing_{poll_id}.txt'
        if generate_missing_voters_txt(poll_id, output_path):
            send_document(ID_MAIN, output_path, caption=f"📋 Не проголосовавшие (опрос {poll_id})")
            logger.info(f"TXT отправлен админу: {output_path}")

    except Exception as e:
        logger.error(f"Критическая ошибка при отправке уведомлений для опроса {poll_id}: {e}")

def generate_missing_voters_txt(poll_id, output_txt_path):
    """Создаёт TXT-файл со списком не проголосовавших."""
    try:
        missing_ids = get_missing_voters_list(poll_id)
        if not missing_ids:
            logger.info(f"Все проголосовали в опросе {poll_id}, TXT не создаётся")
            return False

        with open(ACTUAL_IDS_PATH, 'r', encoding='utf-8') as file:
            dict_pozyvn = json.load(file)
        dict_keys_as_int = {int(key): value for key, value in dict_pozyvn.items()}
        missing_values = [dict_keys_as_int[key] for key in missing_ids]

        lines = [
            f"Список не проголосовавших (опрос {poll_id})",
            f"Всего не проголосовало: {len(missing_values)} человек",
            "=" * 40,
            *missing_values
        ]

        os.makedirs('/app/data/txt_results', exist_ok=True)

        with open(output_txt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"TXT создан: {output_txt_path}, не проголосовало: {len(missing_values)}")
        return True
    except Exception as e:
        logger.error(f"Ошибка при создании TXT для опроса {poll_id}: {e}")
        return False


# ============================================================
#  ПОЛУЧЕНИЕ ОБНОВЛЕНИЙ И ДИАЛОГ
# ============================================================

def get_updates(offset=None):
    """Получает обновления от Telegram."""
    url = f'{BASE_URL}/getUpdates'
    params = {'timeout': 30, 'offset': offset}
    try:
        response = requests.get(url, params=params, timeout=35)
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения обновлений: {e}")
        return None


def start_poll_creation(chat_id):
    """Начинает процесс создания опроса."""
    user_states[chat_id] = {
        'state': 'waiting_question',
        'created_at': time.time(),
        'question': None,
        'options': [],
        'duration_days': None
    }
    send_message(chat_id, "📝 Давайте создадим опрос!\n\nВведите вопрос для опроса:")


def handle_poll_dialog(chat_id, text):
    """Обрабатывает диалог создания опроса."""
    if chat_id not in user_states:
        return

    if time.time() - user_states[chat_id]['created_at'] > STATE_TIMEOUT:
        del user_states[chat_id]
        send_message(chat_id, "⏰ Время ожидания истекло. Начните заново /create_poll")
        return

    state = user_states[chat_id]['state']

    if state == 'waiting_question':
        user_states[chat_id]['question'] = text
        user_states[chat_id]['state'] = 'waiting_options'
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
                send_message(chat_id, "❌ Нужно минимум 2 варианта ответа!\nНачните заново /create_poll")
                del user_states[chat_id]
            else:
                user_states[chat_id]['state'] = 'waiting_duration'
                send_message(
                    chat_id,
                    f"Опрос содержит {len(options)} вариантов.\n\n"
                    "Укажите срок действия опроса в днях (например: 7):"
                )
        else:
            user_states[chat_id]['options'].append(text)
            send_message(
                chat_id,
                f"✅ Добавлен вариант: \"{text}\"\n"
                f"Текущие варианты ({len(user_states[chat_id]['options'])}):\n" +
                "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(user_states[chat_id]['options'])]) +
                "\n\nПродолжайте вводить варианты или напишите \"готово\""
            )

    elif state == 'waiting_duration':
        try:
            duration_days = int(text.strip())
            if duration_days <= 0:
                raise ValueError()

            user_states[chat_id]['duration_days'] = duration_days

            result = send_poll(
                question=user_states[chat_id]['question'],
                options=user_states[chat_id]['options'],
                duration_days=duration_days
            )
            if result.get('ok'):
                send_message(chat_id, f"✅ Опрос создан! Срок: {duration_days} дней")
                send_message(ID_MAIN, f"✅ Опрос создан (срок: {duration_days} дней)")
            else:
                send_message(chat_id, f"❌ Ошибка: {result.get('error', 'Unknown')}")

            del user_states[chat_id]

        except ValueError:
            send_message(chat_id, "❌ Введите корректное число дней (положительное целое):")


def handle_message(message):
    """Обрабатывает входящие сообщения."""
    chat_id = message['chat']['id']
    text = message.get('text', '').strip()

    logger.info(f"Сообщение от {chat_id}: {text}")

    if text == '/start':
        send_message(chat_id, "👋 Привет! Я бот для создания опросов.\nИспользуйте /create_poll для создания опроса")
    elif text == '/create_poll':
        start_poll_creation(chat_id)
    elif chat_id in user_states:
        handle_poll_dialog(chat_id, text)
    else:
        send_message(chat_id, "Я понимаю команды:\n/start — начать работу\n/create_poll — создать опрос")


def handle_polling(update):
    """Обработка голосов в опросах."""
    if 'poll_answer' in update:
        poll_answer = update['poll_answer']
        user_id = poll_answer['user']['id']
        poll_id = poll_answer['poll_id']

        logger.info(f"Голосование: опрос {poll_id}, пользователь {user_id}")
        save_vote_to_db(poll_id, user_id)


# ============================================================
#  MAIN
# ============================================================

def main():
    # Инициализация БД
    init_db()
    db_health_check()

    # Восстановление незакрытых опросов
    restore_pending_polls()

    # Запуск бота
    logger.info("Запуск бота для создания опросов...")
    send_message(ID_MAIN, "опрос_бот запущен (long polling)...")
    offset = None

    while True:
        try:
            updates = get_updates(offset)
            if updates is None:
                time.sleep(5)
                continue

            if updates and updates.get('ok') and updates.get('result'):
                for update in updates['result']:
                    offset = update['update_id'] + 1

                    if 'message' in update:
                        message = update['message']
                        chat = message['chat']
                        chat_id = chat['id']
                        chat_type = chat['type']

                        if chat_type == 'private' and chat_id in user_ids:
                            handle_message(message)

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

