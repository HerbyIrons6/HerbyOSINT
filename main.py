import io
import os
import time
import json
import threading
import subprocess
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv

from texts import TEXTS
from processing import execute_check, execute_check_short, execute_clean, execute_extract

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Токен бота не знайдено. Перевірте файл .env")

MAX_FILE_SIZE = 20 * 1024 * 1024
bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)

# ─── Thread-safe state ─────────────────────────────────────────────
_active: set[int] = set()
_pending: dict[int, dict] = {}
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


# ─── Language state ────────────────────────────────────────────────
LANG_FILE = "langs.json"


def load_langs() -> dict:
    if os.path.exists(LANG_FILE):
        try:
            with open(LANG_FILE, 'r') as f:
                return json.load(f)
        except:
            pass
    return {}


def save_langs(data: dict):
    with open(LANG_FILE, 'w') as f:
        json.dump(data, f)


user_langs = load_langs()


def get_lang(uid: int) -> str:
    """Отримує мову користувача (за замовчуванням 'en')"""
    return user_langs.get(str(uid), 'en')


# ─── Keyboards ─────────────────────────────────────────────────────
def _action_kb(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    kb = InlineKeyboardMarkup(row_width=2)
    kb.row(
        InlineKeyboardButton(t['btn_short'], callback_data="do:short"),
        InlineKeyboardButton(t['btn_full'], callback_data="do:full"),
    )
    kb.row(
        InlineKeyboardButton(t['btn_c2pa'], callback_data="do:extract"),
        InlineKeyboardButton(t['btn_clean'], callback_data="do:clean"),
    )
    return kb


def _confirm_clean_kb(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(t['btn_yes'], callback_data="do:clean_yes"),
        InlineKeyboardButton(t['btn_no'], callback_data="do:cancel"),
    )
    return kb


def _after_extract_kb(lang: str) -> InlineKeyboardMarkup:
    t = TEXTS[lang]
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton(t['btn_clean_ai'], callback_data="do:clean"),
        InlineKeyboardButton(t['btn_full'], callback_data="do:full"),
    )
    return kb


# ─── Helpers ───────────────────────────────────────────────────────
def _send_safe(chat_id: int, filepath: str, caption: str = ""):
    with open(filepath, "rb") as f:
        buf = io.BytesIO(f.read())
    buf.name = os.path.basename(filepath)
    bot.send_document(chat_id, buf, caption=caption)


def _typing(uid: int):
    try:
        bot.send_chat_action(uid, 'upload_document')
    except:
        pass


def _download(file_id: str, uid: int, file_name: str = "file") -> str | None:
    try:
        info = bot.get_file(file_id)
        data = bot.download_file(info.file_path)
        ext = os.path.splitext(file_name)[1] or '.bin'
        ext = ext[:10]  # Санітизація розширення
        path = f"tmp_{uid}_{int(time.time())}{ext}"
        with open(path, 'wb') as f:
            f.write(data)
        return path
    except Exception as e:
        lang = get_lang(uid)
        bot.send_message(uid, TEXTS[lang]['error'].format(error=e))
        return None


def _c2pa_summary(report_path: str) -> str:
    def find(label: str) -> str | None:
        with open(report_path, encoding='utf-8') as f:
            for line in f:
                if label in line and ':' in line:
                    return line.split(':', 1)[-1].strip()
        return None

    parts = []
    if v := find('Tool'):  parts.append(f"📌 Generator: `{v}`")
    if v := find('Agent'): parts.append(f"🤖 Agent: `{v}`")
    if v := find('Spec'):  parts.append(f"📋 Spec: {v}")
    return '\n'.join(parts) or "Details in the attached file."


# ─── Команди ───────────────────────────────────────────────────────
@bot.message_handler(commands=['start', 'help', 'lang'])
def on_start(message):
    kb = InlineKeyboardMarkup()
    kb.row(
        InlineKeyboardButton("🇺🇦 Українська", callback_data="lang:ua"),
        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en")
    )
    bot.reply_to(message, TEXTS['en']['choose_lang'], reply_markup=kb)


@bot.message_handler(commands=['cancel'])
def on_cancel(message):
    uid = message.chat.id
    lang = get_lang(uid)
    bot.clear_step_handler_by_chat_id(uid)
    _set_free(uid)
    _clear_pending(uid)
    bot.reply_to(message, TEXTS[lang]['cancelled'])


# ─── Обробка мови ──────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("lang:"))
def on_language_select(call):
    uid = call.message.chat.id
    lang = call.data.split(':')[1]

    user_langs[str(uid)] = lang
    save_langs(user_langs)

    bot.answer_callback_query(call.id, TEXTS[lang]['lang_set'])
    bot.edit_message_text(
        TEXTS[lang]['welcome'],
        uid,
        call.message.message_id,
        parse_mode='Markdown'
    )


# ─── Вхідні файли ──────────────────────────────────────────────────
@bot.message_handler(content_types=['document'])
def on_document(message):
    uid = message.chat.id
    lang = get_lang(uid)
    doc = message.document

    if _is_busy(uid):
        bot.reply_to(message, TEXTS[lang]['wait'])
        return

    if doc.file_size > MAX_FILE_SIZE:
        bot.reply_to(message, TEXTS[lang]['file_too_big'])
        return

    _set_pending(uid, doc.file_id, doc.file_name or "file", doc.file_size)

    size_str = f"{doc.file_size / (1024 * 1024):.1f} MB"
    msg_text = TEXTS[lang]['what_to_do'].format(name=doc.file_name, size=size_str)

    bot.reply_to(
        message, msg_text,
        reply_markup=_action_kb(lang),
        parse_mode='Markdown'
    )


@bot.message_handler(content_types=['photo', 'video'])
def on_compressed(message):
    uid = message.chat.id
    lang = get_lang(uid)
    bot.reply_to(message, TEXTS[lang]['compressed'], parse_mode='Markdown')


# ─── Кнопки дій ────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("do:"))
def on_action(call):
    uid = call.message.chat.id
    lang = get_lang(uid)
    action = call.data.split(':', 1)[1]

    if action == "cancel":
        bot.answer_callback_query(call.id, TEXTS[lang]['cancelled'])
        bot.delete_message(uid, call.message.message_id)
        return

    if _is_busy(uid):
        bot.answer_callback_query(call.id, TEXTS[lang]['already_running'])
        return

    meta = _get_pending(uid)
    if not meta:
        bot.answer_callback_query(call.id, TEXTS[lang]['file_old'])
        return

    if action == "clean":
        bot.answer_callback_query(call.id)
        msg = TEXTS[lang]['confirm_clean'].format(name=meta['file_name'])
        bot.send_message(uid, msg, reply_markup=_confirm_clean_kb(lang), parse_mode='Markdown')
        return

    bot.answer_callback_query(call.id)
    _run(uid, action, meta, lang)


def _run(uid: int, action: str, meta: dict, lang: str):
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
                _send_safe(uid, report, TEXTS[lang]['short_report'])
                bot.send_message(uid, TEXTS[lang]['more_actions'], reply_markup=_action_kb(lang))
            else:
                bot.send_message(uid, TEXTS[lang]['extract_failed'])

        elif action == "full":
            _typing(uid)
            if execute_check(filepath, report, meta['file_name']):
                _send_safe(uid, report, TEXTS[lang]['full_report'])
                bot.send_message(uid, TEXTS[lang]['more_actions'], reply_markup=_action_kb(lang))
            else:
                bot.send_message(uid, TEXTS[lang]['extract_failed'])

        elif action == "extract":
            _typing(uid)
            if execute_extract(filepath, report):
                summary = _c2pa_summary(report)
                bot.send_message(uid, TEXTS[lang]['c2pa_found'].format(summary=summary), parse_mode='Markdown')
                _send_safe(uid, report, TEXTS[lang]['c2pa_report'])
                bot.send_message(uid, TEXTS[lang]['c2pa_clean_ask'], reply_markup=_after_extract_kb(lang))
            else:
                bot.send_message(uid, TEXTS[lang]['c2pa_not_found'], parse_mode='Markdown')

        elif action == "clean_yes":
            _typing(uid)
            rc = execute_clean(filepath)
            caption = TEXTS[lang]['clean_success'] if rc == 0 else TEXTS[lang]['clean_partial']
            _send_safe(uid, filepath, caption)
            bot.send_message(uid, TEXTS[lang]['send_again'])

    except subprocess.TimeoutExpired:
        bot.send_message(uid, TEXTS[lang]['timeout'])
    except FileNotFoundError:
        bot.send_message(uid, TEXTS[lang]['no_exiftool'])
    except Exception as e:
        bot.send_message(uid, TEXTS[lang]['error'].format(error=e))
    finally:
        _set_free(uid)
        for f in [filepath, report]:
            if f and os.path.exists(f):
                try:
                    os.remove(f)
                except:
                    pass


if __name__ == '__main__':
    print("Ініціалізація сервісу...")
    bot.infinity_polling(skip_pending=True)