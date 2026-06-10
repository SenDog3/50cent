import requests
import os
import json
import logging
import time
import threading

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Получение токенов
BOT_TOKEN = os.getenv('BOT_TOKEN')
ID_MAIN = os.getenv('ID_MAIN')  # использовать для служебных сообщений
GROUP_ID = os.getenv('group_id_main_small') # group_id_маленькая_моя
VOTES_DIR = '/app/data/votes_by_poll/'  # папка для файлов по опросам
ACTUAL_IDS_PATH = '/app/data/pozyvn/dict_id_pozyv.txt'

# Глобальное хранилище соответствий
poll_id_to_message_id = {}

# файл кто допущен голосовать, переименовать на более понятное
with open('/app/data/my_folder/users_for_poll.txt', 'r') as file:
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
        # убрать такой chat_id
        'question': question,
        'options': options,
        'is_anonymous': False
    }
    
    try:
        response = requests.post(url, json=payload, timeout=10)  # Используем json= вместо data=
        poll_result = response.json()

        if poll_result.get('ok'):
            poll_message_id = poll_result['result']['message_id']
             # Сохраняем poll_id из ответа API
            poll_id = poll_result['result']['poll']['id']
            
            # Запоминаем соответствие
            poll_id_to_message_id[poll_id] = poll_message_id

            
            logger.info(f"Опрос отправлен, message_id: {poll_message_id}, poll_id: {poll_id}")
            close_poll_after_week(poll_id, GROUP_ID)  # Передаём poll_id вместо message_id убрать такой id
            return poll_result
        else:
            logger.error(f"API Telegram вернул ошибку: {poll_result}")
            return {'ok': False, 'error': f'Telegram API error: {poll_result}'}
    except Exception as e:
        logger.error(f"Неожиданная ошибка при отправке опроса: {e}")
        return {'ok': False, 'error': str(e)}
        
def close_poll_after_week(poll_id, chat_id):
    """Запускает таймер для закрытия опроса через неделю в отдельном потоке"""
    def _close_poll():
        logger.info(f"Таймер закрытия опроса {poll_id} запущен на 1 неделю")
        time.sleep(300)  # 5 минут временно для отладки, потом перепишу

        # Получаем message_id по poll_id
        if poll_id not in poll_id_to_message_id:
            logger.error(f"Не найден message_id для poll_id {poll_id}")
            return

        poll_message_id = poll_id_to_message_id[poll_id]

        url = f'{BASE_URL}/stopPoll'
        payload = {
            'chat_id': chat_id,
            'message_id': poll_message_id
        }

        try:
            response = requests.post(url, json=payload)
            response.raise_for_status()
            result = response.json()

            if result.get('ok'):
                logger.info(f"Опрос {poll_id} (message_id: {poll_message_id}) успешно закрыт")
                send_poll_results_file(poll_id)  # отправка результатов
                send_post_closure_notifications(poll_id)  # уведомления после закрытия
            else:
                logger.error(f"Ошибка закрытия опроса: {result.get('description', 'Unknown error')}")
        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP ошибка при закрытии опроса {poll_id}: {e}")
        except json.JSONDecodeError as e:
            logger.error(f"Ошибка декодирования JSON ответа: {e}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при закрытии опроса {poll_id}: {e}")

    timer_thread = threading.Thread(target=_close_poll, daemon=True)
    timer_thread.start()
     
def send_poll_results_file(poll_id):
    """Отправляет файл с результатами опроса в указанный чат"""
    json_file_path = os.path.join(VOTES_DIR, f'poll_{poll_id}.json')

    if not os.path.exists(json_file_path):
        logger.warning(f"Файл с результатами опроса {poll_id} не найден: {json_file_path}")
        return

    # Отправляем JSON‑файл с голосами
    url = f'{BASE_URL}/sendDocument'
    try:
        with open(json_file_path, 'rb') as file:
            files = {'document': file}
            data = {'chat_id': ID_MAIN}
            response = requests.post(url, files=files, data=data)
            response.raise_for_status()
            logger.info(f"JSON с результатами опроса {poll_id} отправлен в чат {ID_MAIN}")
    except Exception as e:
        logger.error(f"Ошибка отправки JSON‑файла опроса {poll_id}: {e}")
        return

    # Создаём и отправляем TXT со списком не проголосовавших
    txt_output_path = f'/app/data/txt_results/progul_{poll_id}.txt'
    os.makedirs('/app/data/txt_results', exist_ok=True)
    if generate_missing_voters_txt(poll_id, txt_output_path):
        try:
            with open(txt_output_path, 'rb') as txt_file:
                files = {'document': txt_file}
                data = {'chat_id': ID_MAIN, 'caption': 'Список не проголосовавших (TXT)'}
                response = requests.post(url, files=files, data=data)
                response.raise_for_status()
                logger.info(f"TXT со списком не проголосовавших отправлен для опроса {poll_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки TXT для опроса {poll_id}: {e}")
            
def send_post_closure_notifications(poll_id: str):
    """
    Отправляет уведомления пользователям, которые не проголосовали после закрытия опроса.
    """
    logger.info(f"Отправка уведомлений о непроголосовавших для опроса {poll_id}")

    try:
        missing_users = get_missing_voters_list(poll_id)

        if not missing_users:
            logger.info(f"Все пользователи проголосовали в опросе {poll_id}, уведомления не требуются")
            return

        logger.info(f"Отправляем уведомления {len(missing_users)} пользователям для опроса {poll_id}")

        message_text = (
            f"📣 Опрос #{poll_id} завершён!\n\n"
            f"К сожалению, вы не приняли участие в голосовании.\n\n"
            "Результаты опроса будут опубликованы позже.\n"
            "В следующий раз не пропустите возможность высказать своё мнение!"
        )

        sent_count = 0
        failed_count = 0

        for user_id in missing_users:
            try:
                send_message(user_id, message_text)
                sent_count += 1
                time.sleep(0.1)  # задержка между сообщениями
            except Exception as e:
                logger.error(f"Ошибка отправки уведомления пользователю {user_id}: {e}")
                failed_count += 1

        logger.info(
            f"Уведомления отправлены: успешно {sent_count}, "
            f"ошибок {failed_count} для опроса {poll_id}"
        )
    except Exception as e:
        logger.error(f"Критическая ошибка при отправке уведомлений для опроса {poll_id}: {e}")

def get_missing_voters_list(poll_id: str) -> list:
    """
    Получает список ID пользователей, которые не проголосовали в указанном опросе.
    Returns:
        list: список ID пользователей.
    """
    votes_file_path = os.path.join(VOTES_DIR, f'poll_{poll_id}.json')
    actual_ids_path = ACTUAL_IDS_PATH

    try:
        with open(actual_ids_path, 'r', encoding='utf-8') as file:
            dict_pozyvn = json.load(file)
        dict_keys_as_int = {int(key): value for key, value in dict_pozyvn.items()}

        if not os.path.exists(votes_file_path):
            return list(dict_keys_as_int.keys())

        with open(votes_file_path, 'r', encoding='utf-8') as file:
            votes_data = json.load(file)
        voted_user_ids = [item['user_id'] for item in votes_data]

        all_user_ids = set(dict_keys_as_int.keys())
        voted_ids_set = set(voted_user_ids)
        missing_ids = all_user_ids - voted_ids_set
        return list(missing_ids)
    except Exception as e:
        logger.error(f"Ошибка получения списка не проголосовавших для опроса {poll_id}: {e}")
        return []
        
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
        
        logger.info(f"Голосование: опрос {poll_id}, пользователь {user_id}")

        # Сохраняем данные в отдельный файл для этого опроса
        save_vote_to_file(poll_id, user_id)


def save_vote_to_file(poll_id, user_id):
    """Сохраняет данные о голосовании в отдельный файл для каждого опроса"""
    # Формируем путь к файлу для конкретного опроса
    file_path = os.path.join(VOTES_DIR, f'poll_{poll_id}.json')

    # Структура данных для записи
    vote_data = {
        'user_id': user_id
    }

    # Проверяем, существует ли файл для этого опроса
    if os.path.exists(file_path):
        # Читаем существующие данные
        with open(file_path, 'r', encoding='utf-8') as f:
            try:
                votes = json.load(f)
            except json.JSONDecodeError:
                # Если файл пустой или повреждён, начинаем с пустого списка
                votes = []
    else:
        # Создаём новый список для нового опроса
        votes = []

    # Добавляем новые данные
    votes.append(vote_data)

    # Записываем обратно в файл
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(votes, f, ensure_ascii=False, indent=2)

    logger.debug(f"Данные о голосовании сохранены: опрос {poll_id}, пользователь {user_id} в файл {file_path}")

def generate_missing_voters_txt(poll_id: str, output_txt_path: str) -> bool:
    """Создаёт TXT‑файл со списком пользователей, которые не проголосовали в опросе."""
    try:
        missing_ids = get_missing_voters_list(poll_id)
        if not missing_ids:
            logger.info(f"Все проголосовали в опросе {poll_id}, TXT не создаётся")
            return False

        # Читаем позывные для ID
        actual_ids_path = ACTUAL_IDS_PATH
        with open(actual_ids_path, 'r', encoding='utf-8') as file:
            dict_pozyvn = json.load(file)
        dict_keys_as_int = {int(key): value for key, value in dict_pozyvn.items()}
        missing_values = [dict_keys_as_int[key] for key in missing_ids]

        lines = [
            f"Список не проголосовавших (опрос {poll_id})",
            f"Всего не проголосовало: {len(missing_values)} человек",
            "=" * 40,
            *missing_values
        ]

        with open(output_txt_path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        logger.info(f"TXT успешно создан: {output_txt_path}, не проголосовало: {len(missing_values)} человек")
        return True
    except Exception as e:
        logger.error(f"Ошибка при создании TXT для опроса {poll_id}: {e}")
        return False

    
    
def main():
    """Основная функция запуска бота"""
    logger.info("Запуск бота для создания опросов...")
    send_message(ID_MAIN, "опрос_бот запущен (long polling)...")
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

                    # Получаем chat_id и type из обновления, если возможно
                    chat_id = None
                    chat_type = None

                    if 'message' in update:
                        message = update['message']
                        chat = message['chat']
                        chat_id = chat['id']
                        chat_type = chat['type']

                        # Обрабатываем только приватные чаты и допущенные id
                        if chat_type == 'private' and chat_id in user_ids:
                            handle_message(message)
                        
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
