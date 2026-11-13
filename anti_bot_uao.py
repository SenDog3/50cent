import os
import time
import requests

TOKEN = os.getenv('BOT_TOKEN')
ADMIN_ID = os.getenv('ID_MAIN')
API = f'https://api.telegram.org/bot{TOKEN}'

offset = 0


def send_admin(payload: dict) -> None:
    """Отправка админу с обработкой лимитов (429)."""
    resp = requests.post(f'{API}/sendMessage', json=payload, timeout=30)
    if resp.status_code == 429:
        wait = resp.json().get('parameters', {}).get('retry_after', 5)
        time.sleep(wait + 1)
        requests.post(f'{API}/sendMessage', json=payload, timeout=30)


while True:
    try:
        r = requests.get(f'{API}/getUpdates',
                         params={'timeout': 30, 'offset': offset},
                         timeout=40)
        data = r.json()
        if not data.get('ok'):
            time.sleep(5)
            continue

        for upd in data.get('result', []):
            offset = upd['update_id'] + 1
            msg = upd.get('message') or upd.get('edited_message') or {}
            new_members = msg.get('new_chat_members')
            if not new_members:
                continue

            bots = [m for m in new_members if m.get('is_bot')]
            if not bots:
                continue

            lines = [f"🤖 @{m.get('username', '—')} "
                     f"({m.get('first_name', '—')}) — ID {m['id']}"
                     for m in bots]
            send_admin({
                'chat_id': ADMIN_ID,
                'text': f"⚠️ В чат зашли боты: {len(bots)} шт.\n\n"
                        + '\n'.join(lines)
            })
    except Exception as e:
        print('Ошибка:', e)
        time.sleep(5)
