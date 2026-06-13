import json
import os
import time
import subprocess
import telebot

from config import TOKEN, MAX_FILE_SIZE
from processing import execute_check, execute_clean, execute_extract

bot = telebot.TeleBot(TOKEN, threaded=True, num_threads=4)


@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message,
                 "Сервис работы с метаданными.\n\n"
                 "Доступные команды:\n"
                 "🔍 /check — Прочитать все метаданные (TXT-отчет)\n"
                 "🧹 /clean — Безвозвратно удалить метаданные\n"
                 "🛡 /extract — Валидация C2PA (поиск ИИ-маркировки)\n"
                 "🛑 /cancel — Отменить текущую операцию\n\n"
                 "Файлы необходимо отправлять как 'Документ'."
                 )


@bot.message_handler(commands=['cancel'])
def cancel_operation(message):
    bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
    bot.reply_to(message, "Операция отменена. Ожидание новой команды.")


@bot.message_handler(content_types=['photo', 'video'])
def handle_compressed_media(message):
    bot.reply_to(message, "Ошибка: Telegram удалил метаданные при сжатии. Отправьте исходник как 'Документ' (Файл).")


@bot.message_handler(commands=['check'])
def ask_for_check(message):
    msg = bot.reply_to(message, "Режим сканирования. Отправьте документ.")
    bot.register_next_step_handler(msg, process_check_step)


@bot.message_handler(commands=['clean'])
def ask_for_clean(message):
    msg = bot.reply_to(message, "Режим очистки. Отправьте документ.")
    bot.register_next_step_handler(msg, process_clean_step)


@bot.message_handler(commands=['extract'])
def ask_for_extract(message):
    msg = bot.reply_to(message, "Режим верификации C2PA. Отправьте документ.")
    bot.register_next_step_handler(msg, process_extract_step)


def download_document(message) -> str | None:
    if not message.document:
        bot.reply_to(message, "Получен не документ. Операция прервана.")
        bot.clear_step_handler_by_chat_id(chat_id=message.chat.id)
        return None

    if message.document.file_size > MAX_FILE_SIZE:
        bot.reply_to(message, "Размер файла превышает ограничение API Telegram (20 МБ).")
        return None

    file_info = bot.get_file(message.document.file_id)
    downloaded_file = bot.download_file(file_info.file_path)

    # Санитизация имени файла для защиты от Path Traversal
    ext = os.path.splitext(message.document.file_name)[1]
    safe_filename = f"{message.chat.id}_{int(time.time())}{ext}"

    with open(safe_filename, 'wb') as f:
        f.write(downloaded_file)

    return safe_filename


def process_check_step(message):
    filepath = download_document(message)
    if not filepath: return

    # Упрощенное имя отчета без дублирования расширений
    report_name = f"report_{message.chat.id}_{int(time.time())}.txt"
    try:
        bot.send_message(message.chat.id, "Анализ файла...")
        success = execute_check(filepath, report_name)

        if success:
            with open(report_name, "rb") as f:
                bot.send_document(message.chat.id, f, caption="Отчет сканирования.")
        else:
            bot.send_message(message.chat.id, "Не удалось извлечь метаданные.")

    except json.JSONDecodeError:
        bot.reply_to(message, "Ошибка: Не удалось распарсить метаданные (поврежденный или неподдерживаемый формат).")
    except subprocess.TimeoutExpired:
        bot.reply_to(message, "Таймаут: процесс завис на чтении файла.")
    except Exception as e:
        bot.reply_to(message, f"Системная ошибка: {e}")
    finally:
        if os.path.exists(filepath): os.remove(filepath)
        if os.path.exists(report_name): os.remove(report_name)

def process_clean_step(message):
    filepath = download_document(message)
    if not filepath: return

    try:
        bot.send_message(message.chat.id, "Удаление метаданных...")
        execute_clean(filepath)

        with open(filepath, "rb") as f:
            bot.send_document(message.chat.id, f, caption="Файл успешно очищен.")

    except subprocess.TimeoutExpired:
        bot.reply_to(message, "Таймаут: процесс завис.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка при очистке: {e}")
    finally:
        if os.path.exists(filepath): os.remove(filepath)


def process_extract_step(message):
    filepath = download_document(message)
    if not filepath: return

    report_name = f"c2pa_report_{filepath}.txt"
    try:
        bot.send_message(message.chat.id, "Поиск манифеста C2PA...")
        success = execute_extract(filepath, report_name)

        if success:
            with open(report_name, "rb") as f:
                bot.send_document(message.chat.id, f, caption="Манифест C2PA обнаружен. Отчет прикреплен.")
        else:
            bot.send_message(message.chat.id,
                             "Манифест C2PA не найден. Файл не содержит ИИ-маркировки или она удалена.")

    except FileNotFoundError:
        bot.reply_to(message, "Критическая ошибка: утилита c2patool не установлена в системе.")
    except subprocess.TimeoutExpired:
        bot.reply_to(message, "Таймаут: процесс завис.")
    except Exception as e:
        bot.reply_to(message, f"Ошибка верификации: {e}")
    finally:
        if os.path.exists(filepath): os.remove(filepath)
        if os.path.exists(report_name): os.remove(report_name)


if __name__ == '__main__':
    print("Инициализация сервиса...")
    bot.infinity_polling(skip_pending=True)