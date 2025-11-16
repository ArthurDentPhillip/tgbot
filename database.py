# database.py
import sqlite3
from datetime import datetime
import pytz

# Московский часовой пояс
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

def today_moscow() -> str:
    """Возвращает дату в формате YYYY-MM-DD по Московскому времени."""
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")


# ========= ИНИЦИАЛИЗАЦИЯ БД =========
def init_db():
    conn = sqlite3.connect("church.db")
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS volunteers (
            user_id INTEGER PRIMARY KEY,
            first_name TEXT,
            last_name TEXT,
            username TEXT,
            chat_id INTEGER
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS responses (
            user_id INTEGER,
            response_date TEXT,
            can_serve BOOLEAN,
            PRIMARY KEY (user_id, response_date)
        )
    """)

    conn.commit()
    conn.close()


# ========= ФУНКЦИИ ДЛЯ РАБОТЫ С ВОЛОНТЁРАМИ =========
def add_volunteer(user, chat_id):
    conn = sqlite3.connect("church.db")
    c = conn.cursor()

    c.execute("""
        INSERT OR REPLACE INTO volunteers (user_id, first_name, last_name, username, chat_id)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id,
          user.first_name or "",
          user.last_name or "",
          user.username or "",
          chat_id))

    conn.commit()
    conn.close()


def get_volunteers():
    conn = sqlite3.connect("church.db")
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, last_name, username, chat_id FROM volunteers")
    data = c.fetchall()
    conn.close()
    return data


# ========= ФУНКЦИИ ДЛЯ РЕСПОНСОВ =========
def record_response(user_id, can_serve):
    conn = sqlite3.connect("church.db")
    c = conn.cursor()
    d = today_moscow()

    c.execute("""
        INSERT OR REPLACE INTO responses (user_id, response_date, can_serve)
        VALUES (?, ?, ?)
    """, (user_id, d, can_serve))

    conn.commit()
    conn.close()


def get_responses_for_date(d):
    conn = sqlite3.connect("church.db")
    c = conn.cursor()

    c.execute("""
        SELECT v.first_name, v.last_name, v.username, r.can_serve, r.user_id
        FROM responses r
        JOIN volunteers v ON r.user_id = v.user_id
        WHERE r.response_date = ?
    """, (d,))

    data = c.fetchall()
    conn.close()
    return data

def clear_week_data():
    conn = sqlite3.connect("church_bot.db")
    cursor = conn.cursor()

    cursor.execute("DELETE FROM responses")
    cursor.execute("DELETE FROM polls")

    conn.commit()
    conn.close()
