import io
import os
import time
import threading
import subprocess
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TOKEN, MAX_FILE_SIZE
from processing import execute_check, execute_check_short, execute_clean, execute_extract

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# ─── Thread-safe state ─────────────────────────────────────────────
_active:  set[int]        = set()
_pending: dict[int, dict] = {}   # uid → {file_id, file_name, file_size}
_lock = threading.Lock()

def _is_busy(uid: int) -> bool:
    with _lock: return uid in _active

def _set_busy(uid: int):
    with _lock: _active.add(uid)

def _set_free(uid: int):
    with _lock: _active.discard(uid)

def _set_pending(uid: int, file_id: str, file_name: str, file_size: int):
    with _lock:
        _pending[uid] = {'file_id': file_id, 'file_name': file_name, 'file_size': file_size}

def _get_pending(uid: int) -> dict | None:
    with _lock: return _pending.get(uid)

def _clear_pending(uid: int):
    with _lock: _pending.pop(uid, None)

# ─── Keyboards ─────────────────────────────────────────────────────
def _action_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton("⚡ Кратко",   callback_data="do:short"),
        InlineKeyboardButton("📋 Полный",   callback_data="do:full"),
    )
    kb.row(
        InlineKeyboardButton("🛡 C2PA",     callback_data="do:extract"),
        InlineKeyboardButton("🧹 Очистить", callback_data="do:clean"),
    )
    return kb

def _confirm_clean_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("✅ Да, удалить", callback_data="do:clean_yes"),
        InlineKeyboardButton("❌ Отмена",      callback_data="do:cancel"),
    )
    return kb

def _after_extract_kb() -> InlineKeyboardMarkup:
    """Показывается если C2PA найдена — предлагаем очистить."""
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🧹 Удалить AI-маркировку", callback_data="do:clean"),
        InlineKeyboardButton("📋 Полный отчёт",           callback_data="do:full"),
    )
    return kb

# ─── Helpers ───────────────────────────────────────────────────────
def _send_safe(chat_id: int, filepath: str, caption: str = ""):
    """Читает файл в BytesIO → WinError 32 невозможен."""
    with open(filepath, "rb") as f:
        buf = io.BytesIO(f.read())
    buf.name = os.path.basename(filepath)
    bot.send_document(chat_id, buf, caption=caption)

def _typing(uid: int):
    try: bot.send_chat_action(uid, 'upload_document')
    except: pass

def _download(file_id: str, uid: int, file_name: str = "file") -> str | None:
    try:
        info = bot.get_file(file_id)
        data = bot.download_file(info.file_path)
        ext  = os.path.splitext(file_name)[1] or '.bin'   # .mp4 / .png / .jpg ...
        path = f"tmp_{uid}_{int(time.time())}{ext}"
        with open(path, 'wb') as f:
            f.write(data)
        return path
    except Exception as e:
        bot.send_message(uid, f"❌ Не удалось скачать файл: {e}")
        return None

def _c2pa_summary(report_path: str) -> str:
    """Достаёт ключевые строки из C2PA-отчёта для показа прямо в чате."""
    def find(label: str) -> str | None:
        with open(report_path, encoding='utf-8') as f:
            for line in f:
                if label in line and ':' in line:
                    return line.split(':', 1)[-1].strip()
        return None

    parts = []
    if v := find('Инструмент'): parts.append(f"📌 Генератор: `{v}`")
    if v := find('Агент'):      parts.append(f"🤖 Агент: `{v}`")
    if v := find('Спека C2PA'): parts.append(f"📋 Спека: C2PA {v}")
    if v := find('Тип источника'): parts.append(f"🔍 {v}")
    return '\n'.join(parts) or "Подробности в прикреплённом файле."

# ─── Команды ───────────────────────────────────────────────────────
@bot.message_handler(commands=['start', 'help'])
def on_start(message):
    bot.reply_to(message,
        "👋 Отправьте любой файл как *Документ* — я предложу что с ним сделать.\n\n"
        "📌 Доступные операции:\n"
        "  ⚡ *Кратко* — ключевые метаданные\n"
        "  📋 *Полный* — все метаданные\n"
        "  🛡 *C2PA* — проверка AI-маркировки\n"
        "  🧹 *Очистить* — удалить метаданные\n\n"
        "🛑 /cancel — отменить текущую операцию\n\n"
        "_Важно: файлы отправляйте через Файл → Документ, не как фото/видео._",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['cancel'])
def on_cancel(message):
    uid = message.chat.id
    bot.clear_step_handler_by_chat_id(uid)
    _set_free(uid)
    _clear_pending(uid)
    bot.reply_to(message, "🛑 Операция отменена.")

# ─── Входящие файлы ────────────────────────────────────────────────
@bot.message_handler(content_types=['document'])
def on_document(message):
    uid = message.chat.id
    doc = message.document

    if _is_busy(uid):
        bot.reply_to(message, "⏳ Дождитесь завершения текущей операции или /cancel.")
        return

    if doc.file_size > MAX_FILE_SIZE:
        bot.reply_to(message, "❌ Файл превышает лимит Telegram API (20 МБ).")
        return

    _set_pending(uid, doc.file_id, doc.file_name or "file", doc.file_size)

    size_str = f"{doc.file_size / (1024 * 1024):.1f} МБ"
    bot.reply_to(
        message,
        f"📎 `{doc.file_name}`  ·  {size_str}\n\nЧто сделать с файлом?",
        reply_markup=_action_kb(),
        parse_mode='Markdown'
    )

@bot.message_handler(content_types=['photo', 'video'])
def on_compressed(message):
    bot.reply_to(message,
        "⚠️ Telegram сжал файл и удалил метаданные.\n"
        "Отправьте его через *Файл → Документ*.",
        parse_mode='Markdown'
    )

# ─── Кнопки ────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("do:"))
def on_action(call):
    uid    = call.message.chat.id
    action = call.data.split(':', 1)[1]

    if action == "cancel":
        bot.answer_callback_query(call.id, "Отменено.")
        bot.delete_message(uid, call.message.message_id)
        return

    if _is_busy(uid):
        bot.answer_callback_query(call.id, "⏳ Уже выполняется операция!")
        return

    meta = _get_pending(uid)
    if not meta:
        bot.answer_callback_query(call.id, "❌ Файл устарел. Отправьте снова.")
        return

    # Очистка — сначала подтверждение
    if action == "clean":
        bot.answer_callback_query(call.id)
        bot.send_message(
            uid,
            f"⚠️ Метаданные файла `{meta['file_name']}` будут удалены *безвозвратно*.\n\nПродолжить?",
            reply_markup=_confirm_clean_kb(),
            parse_mode='Markdown'
        )
        return

    bot.answer_callback_query(call.id)
    _run(uid, action, meta)


def _run(uid: int, action: str, meta: dict):
    _set_busy(uid)
    _typing(uid)

    filepath = _download(meta['file_id'], uid, meta['file_name'])
    if not filepath:
        _set_free(uid)
        return

    report = f"rpt_{uid}_{int(time.time())}.txt"

    try:
        if action == "short":
            _typing(uid)
            if execute_check_short(filepath, report, meta['file_name']):
                _send_safe(uid, report, "⚡ Краткий отчёт по метаданным.")
                bot.send_message(uid, "Ещё что-то сделать с этим файлом?",
                                 reply_markup=_action_kb())
            else:
                bot.send_message(uid, "⚠️ Не удалось извлечь метаданные.")

        elif action == "full":
            _typing(uid)
            if execute_check(filepath, report, meta['file_name']):
                _send_safe(uid, report, "📋 Полный отчёт по метаданным.")
                bot.send_message(uid, "Ещё что-то сделать с этим файлом?",
                                 reply_markup=_action_kb())
            else:
                bot.send_message(uid, "⚠️ Не удалось извлечь метаданные.")

        elif action == "extract":
            _typing(uid)
            if execute_extract(filepath, report):
                summary = _c2pa_summary(report)
                bot.send_message(uid,
                    f"🛡 *C2PA-маркировка обнаружена*\n\n{summary}",
                    parse_mode='Markdown'
                )
                _send_safe(uid, report, "📄 Полный C2PA-отчёт")
                bot.send_message(uid, "Хотите удалить AI-маркировку из файла?",
                                 reply_markup=_after_extract_kb())
            else:
                bot.send_message(uid,
                    "✅ *AI-маркировка не обнаружена*\n\n"
                    "Файл не содержит C2PA-манифеста или он был удалён.",
                    parse_mode='Markdown'
                )


        elif action == "clean_yes":
            _typing(uid)
            rc = execute_clean(filepath)
            if rc == 0:
                caption = "✅ Все метаданные удалены."
            else:
                caption = "✅ Метаданные удалены (часть служебных тегов MP4/видео сохранена — это норма)."
            _send_safe(uid, filepath, caption)
            bot.send_message(uid, "Отправьте файл снова, чтобы убедиться в результате.")

    except subprocess.TimeoutExpired:
        bot.send_message(uid, "⏱ Таймаут. Попробуйте ещё раз.")
    except FileNotFoundError:
        bot.send_message(uid, "❌ exiftool не найден в системе.")
    except Exception as e:
        bot.send_message(uid, f"❌ Ошибка: {e}")
    finally:
        _set_free(uid)
        for f in [filepath, report]:
            if f and os.path.exists(f):
                try: os.remove(f)
                except: pass


if __name__ == '__main__':
    print("Инициализация сервиса...")
    bot.infinity_polling(skip_pending=True)