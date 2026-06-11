import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise ValueError("Токен бота не найден. Проверьте файл .env")

# Ограничение API Telegram для скачивания ботом
MAX_FILE_SIZE = 20 * 1024 * 1024