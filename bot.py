import logging
import sqlite3
from datetime import datetime
from database import clear_week_data
import pytz
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from config import TOKEN, CHAT_ID

# ========= Настройки =========
MOSCOW_TZ = pytz.timezone("Europe/Moscow")

def today_moscow() -> str:
    """Возвращает дату в формате YYYY-MM-DD по Московскому времени."""
    return datetime.now(MOSCOW_TZ).strftime("%Y-%m-%d")

# ========= Логирование =========
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ========= Инициализация БД =========
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
            response_date DATE,
            can_serve BOOLEAN,
            PRIMARY KEY (user_id, response_date)
        )
    """)
    conn.commit()
    conn.close()

init_db()

# ========= Функции работы с БД =========
def get_volunteers():
    conn = sqlite3.connect("church.db")
    c = conn.cursor()
    c.execute("SELECT user_id, first_name, last_name, username FROM volunteers")
    data = c.fetchall()
    conn.close()
    return data

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

# ========= Хендлеры =========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id

    conn = sqlite3.connect("church.db")
    c = conn.cursor()
    c.execute("""
        INSERT OR REPLACE INTO volunteers (user_id, first_name, last_name, username, chat_id)
        VALUES (?, ?, ?, ?, ?)
    """, (user.id, user.first_name or "", user.last_name or "", user.username or "", chat_id))
    conn.commit()
    conn.close()

    await update.message.reply_text("🙏 Вы записаны. Спасибо за служение!")
    logger.info(f"Новый волонтёр: {user.id} | {user.full_name} | chat_id={chat_id}")

# ---------------------------------------
async def send_poll(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    test_mode = job.data.get("test", False) if job and hasattr(job, 'data') else False

    volunteers = get_volunteers()
    if not volunteers:
        logger.info("Нет волонтёров в базе")
        return

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Да", callback_data="serve_yes"),
         InlineKeyboardButton("❌ Нет", callback_data="serve_no")]
    ])

    sent_count = 0
    for user_id, fn, ln, uname in volunteers:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="🔔 Сможете ли вы служить в воскресенье?",
                reply_markup=keyboard
            )
            sent_count += 1
        except Exception as e:
            logger.warning(f"Не удалось отправить опрос {user_id} ({fn} @{uname}): {e}")

    logger.info(f"Опрос отправлен {sent_count}/{len(volunteers)} волонтёрам" + (" [ТЕСТ]" if test_mode else ""))

# ---------------------------------------
async def handle_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = update.effective_user

    can_serve = query.data == "serve_yes"
    record_response(user.id, can_serve)

    await query.edit_message_text(
        text=f"🙏 Спасибо! Ваш ответ: {'✅ Да' if can_serve else '❌ Нет'}"
    )
    logger.info(f"Ответ от {user.id}: {'Да' if can_serve else 'Нет'}")

# ---------------------------------------
async def send_reminder(context: ContextTypes.DEFAULT_TYPE):
    d = today_moscow()
    volunteers = get_volunteers()
    responses = get_responses_for_date(d)
    responded_ids = {r[4] for r in responses}

    not_answered = [v for v in volunteers if v[0] not in responded_ids]
    sent = 0

    for user_id, fn, ln, uname in not_answered:
        try:
            await context.bot.send_message(
                chat_id=user_id,
                text="⏰ Напоминание! Пожалуйста, ответьте, сможете ли вы служить в воскресенье 🙏"
            )
            sent += 1
        except Exception as e:
            logger.warning(f"Не отправлено напоминание {user_id}: {e}")

    logger.info(f"Напоминание отправлено {sent}/{len(not_answered)} неответившим")

# ---------------------------------------
async def publish_summary(context: ContextTypes.DEFAULT_TYPE):
    d = today_moscow()
    volunteers = get_volunteers()
    responses = get_responses_for_date(d)

    yes = []
    no = []
    responded_ids = set()

    for fn, ln, uname, can_serve, uid in responses:
        name = fn.strip() or uname or f"ID{uid}"
        responded_ids.add(uid)
        (yes if can_serve else no).append(name)

    not_answered = [
        (fn.strip() or uname or f"ID{uid}")
        for uid, fn, ln, uname in volunteers
        if uid not in responded_ids
    ]

    msg = "📋 <b>Итоги опроса</b>\n\n"
    msg += "✅ <b>Смогут:</b>\n" + ("\n".join(f"• {x}" for x in yes) if yes else "• —")
    msg += "\n\n❌ <b>Не смогут:</b>\n" + ("\n".join(f"• {x}" for x in no) if no else "• —")
    msg += "\n\n📭 <b>Не ответили:</b>\n" + ("\n".join(f"• {x}" for x in not_answered) if not_answered else "• —")

    # Отправка в целевой чат с логированием ошибок
    try:
        await context.bot.send_message(
            chat_id=CHAT_ID,
            text=msg,
            parse_mode="HTML"
        )
        logger.info(f"Итоги опубликованы в CHAT_ID={CHAT_ID} (ответов: {len(responses)})")
    except Exception as e:
        logger.error(f"❌ ОШИБКА отправки итогов в CHAT_ID={CHAT_ID}: {e}")

# ---------------------------------------
async def yes_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_response(update.effective_user.id, True)
    await update.message.reply_text("✅ Ответ записан: Да")

async def no_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    record_response(update.effective_user.id, False)
    await update.message.reply_text("❌ Ответ записан: Нет")

async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    d = today_moscow()
    volunteers = get_volunteers()
    responses = get_responses_for_date(d)

    yes = []
    no = []
    responded_ids = set()

    for fn, ln, uname, can_serve, uid in responses:
        name = fn.strip() or uname or f"ID{uid}"
        responded_ids.add(uid)
        (yes if can_serve else no).append(name)

    not_answered = [
        fn.strip() or uname or f"ID{uid}"
        for uid, fn, ln, uname in volunteers
        if uid not in responded_ids
    ]

    msg = f"📋 Статус на {d}\n\n"
    msg += f"✅ Да ({len(yes)}):\n" + ("\n".join(yes) if yes else "—")
    msg += f"\n\n❌ Нет ({len(no)}):\n" + ("\n".join(no) if no else "—")
    msg += f"\n\n📭 Не ответили ({len(not_answered)}):\n" + ("\n".join(not_answered) if not_answered else "—")

    await update.message.reply_text(msg)

async def test_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧪 Тест запущен!\n⏱ Опрос → через 2 мин\n🔔 Напоминание → через 3 мин\n📊 Итоги → через 4 мин")

    j = context.job_queue
    # Правильно: data= — отдельный параметр, НЕ внутри job_kwargs!
    j.run_once(send_poll, when=120, data={"test": True})
    j.run_once(send_reminder, when=180, data={"test": True})
    j.run_once(publish_summary, when=240, data={"test": True})

    logger.info("Тестовые задачи запланированы")

# ---------------------------------------
async def db_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vols = get_volunteers()
    d = today_moscow()
    resp = get_responses_for_date(d)
    lines = [
        f"Волонтёров: {len(vols)}",
        f"Ответов сегодня ({d}): {len(resp)}",
        "",
        "Список волонтёров:"
    ]
    for uid, fn, ln, un in vols:
        lines.append(f"• {fn or '-'} {ln or ''} (@{un or '-'}) [ID{uid}]")
    await update.message.reply_text("\n".join(lines))

# ========= Планировщик =========
def schedule_jobs(app):
    jq = app.job_queue

    # Пятница 19:00 — опрос
    jq.run_custom(
        callback=send_poll,
        job_kwargs={
            "trigger": "cron",
            "day_of_week": "fri",
            "hour": 19,
            "minute": 0,
            "timezone": MOSCOW_TZ,
        },
        data={"test": False}  # ← ← ← ВНЕ job_kwargs!
    )

    # Пятница 21:00 — напоминание
    jq.run_custom(
        callback=send_reminder,
        job_kwargs={
            "trigger": "cron",
            "day_of_week": "fri",
            "hour": 21,
            "minute": 0,
            "timezone": MOSCOW_TZ,
        }
    )

    # Суббота 08:00 — итоги
    jq.run_custom(
        callback=publish_summary,
        job_kwargs={
            "trigger": "cron",
            "day_of_week": "sat",
            "hour": 8,
            "minute": 0,
            "timezone": MOSCOW_TZ,
        }
    )

    logger.info("✅ CRON-задачи настроены: Пт 19:00, 21:00; Сб 08:00 (МСК)")

    # Воскресенье 03:00 — очистка базы (МСК)
    jq.run_custom(
        callback=clear_week_data,
        job_kwargs={
            "trigger": "cron",
            "day_of_week": "sun",
            "hour": 3,
            "minute": 0,
            "timezone": MOSCOW_TZ,
        }
    )
    logger.info("🧹 Очистка базы запланирована: Вс 03:00 (МСК)")


# ========= Запуск =========
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_response))
    app.add_handler(CommandHandler("yes", yes_cmd))
    app.add_handler(CommandHandler("no", no_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("test", test_cmd))
    app.add_handler(CommandHandler("db", db_info))

    schedule_jobs(app)

    logger.info("🚀 Бот запущен. Ожидание команд...")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()