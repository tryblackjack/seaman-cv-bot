# -*- coding: utf-8 -*-
"""
Настройки бота для рассылки CV моряков
"""
import os
from dotenv import load_dotenv

load_dotenv()

# =================================================================
# TELEGRAM
# =================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8499683122:AAEDPGuQLF2tXd_Cn4LXPXgaRf7mzXoa03o")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "1661751239:TEST:g7PE-C0FV-YcY1-ZgO7")
ADMIN_PASSPHRASE = os.getenv("ADMIN_PASSPHRASE", "CaptainPass123")
BOT_USERNAME = os.getenv("BOT_USERNAME", "OnlyOffshore_bot")

# Список ID пользователей с правами администратора (можно добавить в .env через запятую)
ADMIN_USER_IDS = [int(x.strip()) for x in os.getenv("ADMIN_USER_IDS", "").split(",") if x.strip()]

# =================================================================
# EMAIL НАСТРОЙКИ
# =================================================================
USE_GMAIL = os.getenv("USE_GMAIL", "True").lower() == "true"
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "info@your-company.com")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "your-app-password")

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp-pulse.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "info@your-service.com")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "YOUR_PASSWORD")

# Тестовый режим
TEST_MODE = os.getenv("TEST_MODE", "True").lower() == "true"
TEST_TARGET_EMAIL = os.getenv("TEST_TARGET_EMAIL", "oooglobalserviceint@gmail.com")

# =================================================================
# OLLAMA / AI
# =================================================================
OLLAMA_API_URL = os.getenv("OLLAMA_API_URL", "http://localhost:11435/api/generate")
MODEL_NAME = os.getenv("MODEL_NAME", "llama3")

# =================================================================
# БАЗА ДАННЫХ И ФАЙЛЫ
# =================================================================
LOCAL_DB_FILE = os.getenv("LOCAL_DB_FILE", "data/recruiter_vessel_map.json")
TEMP_DIR = os.getenv("TEMP_DIR", "temp_cvs")

# Создаем директорию для временных CV
if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# =================================================================
# МУЛЬТИЯЗЫЧНОСТЬ
# =================================================================
SUPPORTED_LANGUAGES = ['en', 'ru', 'uk']
DEFAULT_LANGUAGE = 'en'
I18N_DIR = 'i18n'

# =================================================================
# ЛОГИРОВАНИЕ
# =================================================================
LOG_FILE = 'logs/bot.log'
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Создаем директорию для логов
log_dir = os.path.dirname(LOG_FILE)
if log_dir and not os.path.exists(log_dir):
    os.makedirs(log_dir)
