# -*- coding: utf-8 -*-
import json
import os
import asyncio
import logging
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

# SendGrid
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment, FileContent, FileName, FileType, Disposition
    import base64
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    LabeledPrice
)
from telegram.ext import (
    Application, 
    CommandHandler, 
    MessageHandler, 
    CallbackQueryHandler, 
    filters, 
    ContextTypes, 
    ConversationHandler,
    PreCheckoutQueryHandler
)
import aiohttp

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================

TELEGRAM_BOT_TOKEN = "8499683122:AAEDPGuQLF2tXd_Cn4LXPXgaRf7mzXoa03o"
PAYMENT_PROVIDER_TOKEN = "1661751239:TEST:g7PE-C0FV-YcY1-ZgO7" 
ADMIN_PASSPHRASE = "CaptainPass123"

USE_GMAIL = True
GMAIL_ADDRESS = "info@your-company.com"
GMAIL_APP_PASSWORD = "your-app-password"

SMTP_SERVER = "smtp-pulse.com"
SMTP_PORT = 465 
SMTP_USERNAME = "info@your-service.com" 
SMTP_PASSWORD = "YOUR_PASSWORD" 

TEST_MODE = True 
TEST_TARGET_EMAIL = "oooglobalserviceint@gmail.com"

OLLAMA_API_URL = "http://localhost:11435/api/generate"
MODEL_NAME = "llama3"

LOCAL_DB_FILE = "recruiter_vessel_map.json"
TEMP_DIR = "temp_cvs"

if not os.path.exists(TEMP_DIR):
    os.makedirs(TEMP_DIR)

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =================================================================
# 🌍 МУЛЬТИЯЗЫЧНОСТЬ (i18n)
# =================================================================

SUPPORTED_LANGUAGES = ['en', 'ru', 'uk']
DEFAULT_LANGUAGE = 'en'

# Хранилище переводов
translations = {}

def load_translations():
    """Загружает все файлы переводов"""
    global translations
    for lang in SUPPORTED_LANGUAGES:
        file_path = f"i18n_{lang}.json"
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                translations[lang] = json.load(f)
            logger.info(f"✅ Загружен язык: {lang}")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {lang}: {e}")
            translations[lang] = {}

def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получает язык пользователя из context.user_data"""
    return context.user_data.get('language', DEFAULT_LANGUAGE)

def set_user_language(context: ContextTypes.DEFAULT_TYPE, lang_code: str):
    """Устанавливает язык пользователя"""
    if lang_code in SUPPORTED_LANGUAGES:
        context.user_data['language'] = lang_code
        logger.info(f"🌍 Язык установлен: {lang_code}")

def detect_language_from_telegram(update: Update) -> str:
    """Определяет язык пользователя из Telegram"""
    try:
        user = update.effective_user
        if user and user.language_code:
            # Telegram отдает 'ru', 'uk', 'en' и т.д.
            lang = user.language_code.lower()[:2]
            if lang in SUPPORTED_LANGUAGES:
                logger.info(f"🌍 Определен язык из Telegram: {lang}")
                return lang
    except Exception as e:
        logger.error(f"Ошибка определения языка: {e}")
    
    return DEFAULT_LANGUAGE

def t(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs) -> str:
    """
    Получает переведенный текст для пользователя.
    
    Args:
        context: Telegram context
        key: ключ перевода
        **kwargs: параметры для форматирования строки
    
    Returns:
        Переведенный и отформатированный текст
    """
    lang = get_user_language(context)
    text = translations.get(lang, {}).get(key, translations.get(DEFAULT_LANGUAGE, {}).get(key, f"[{key}]"))
    
    # Форматирование параметров
    try:
        return text.format(**kwargs)
    except KeyError:
        return text

# =================================================================
# БАЗА ДАННЫХ
# =================================================================

recruiter_db_cache = {}

def load_database():
    global recruiter_db_cache
    try:
        if os.path.exists(LOCAL_DB_FILE):
            with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
                recruiter_db_cache = json.load(f)
            logger.info(f"✅ База загружена: {len(recruiter_db_cache)} записей")
        else:
            recruiter_db_cache = {
                "crew@maersk.com": ["CONTAINER"],
                "hr@bourbon-offshore.com": ["OFFSHORE", "AHTS"],
                "manning@osm.no": ["OFFSHORE"],
                "test@crewing.com": ["TANKER"]
            }
            logger.warning("⚠️ Файл базы не найден. Используем тестовую.")
    except Exception as e:
        logger.error(f"Ошибка базы: {e}")

# =================================================================
# AI АНАЛИЗ
# =================================================================

def extract_text_from_pdf(file_path):
    text = ""
    if not PdfReader:
        logger.warning("⚠️ pypdf не установлена")
        return ""
    try:
        reader = PdfReader(file_path)
        for page in reader.pages:
            text += page.extract_text() + "\n"
    except Exception as e:
        logger.error(f"Ошибка чтения PDF: {e}")
    return text[:3000]

async def analyze_cv_and_preferences(cv_text, user_preferences):
    if not cv_text:
        return f"Dear Sirs, I am looking for {user_preferences}. CV attached.", ""

    prompt = f"""
    Analyze this seafarer's CV text and preferences.
    
    User Preferences: "{user_preferences}"
    CV Text snippet: "{cv_text[:1500]}..."

    Task 1: Identify the CURRENT or LAST company name to avoid sending CV to them. If not found, return "NONE".
    Task 2: Write a short, professional email body (max 60 words).

    Output format:
    COMPANY_TO_EXCLUDE: [Company Name]
    EMAIL_BODY: [Email Text]
    """
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload, timeout=45) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    response = data.get('response', '').strip()
                    
                    exclude_company = "NONE"
                    email_body = "Dear Sir/Madam, please find attached my CV."
                    
                    if "COMPANY_TO_EXCLUDE:" in response:
                        parts = response.split("EMAIL_BODY:")
                        if len(parts) > 1:
                            exclude_line = parts[0].replace("COMPANY_TO_EXCLUDE:", "").strip()
                            exclude_company = exclude_line
                            email_body = parts[1].strip()
                    
                    logger.info(f"✅ AI анализ завершен. Exclude: {exclude_company}")
                    return email_body, exclude_company
    except Exception as e:
        logger.error(f"Ollama Error: {e}")
    
    return f"Dear Sir/Madam,\n\nI am applying for a position. CV attached.\n\nPreferences: {user_preferences}", ""

# =================================================================
# ОТПРАВКА EMAIL
# =================================================================

def send_email_sync(target_email, subject, body, cv_path, user_reply_to):
    """
    Отправка через Gmail SMTP или SendPulse.
    """
    try:
        msg = MIMEMultipart()
        
        if USE_GMAIL:
            msg['From'] = GMAIL_ADDRESS
            msg['Reply-To'] = user_reply_to
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            smtp_user = GMAIL_ADDRESS
            smtp_pass = GMAIL_APP_PASSWORD
        else:
            msg['From'] = SMTP_USERNAME
            msg['Reply-To'] = user_reply_to
            smtp_server = SMTP_SERVER
            smtp_port = SMTP_PORT
            smtp_user = SMTP_USERNAME
            smtp_pass = SMTP_PASSWORD
        
        msg['To'] = target_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        if cv_path and os.path.exists(cv_path):
            with open(cv_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename=os.path.basename(cv_path))
                msg.attach(attach)
        
        if USE_GMAIL:
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port)
        
        server.login(smtp_user, smtp_pass)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"✅ Email отправлен на {target_email}")
        return True
        
    except Exception as e:
        logger.error(f"❌ Ошибка отправки на {target_email}: {e}")
        return False

# =================================================================
# МАССОВАЯ РАССЫЛКА
# =================================================================

async def perform_mass_apply(user_id, context, user_data):
    try:
        await context.bot.send_message(user_id, t(context, 'ai_analyzing'))
        
        cv_text = extract_text_from_pdf(user_data.get('cv_path'))
        email_body, exclude_company = await analyze_cv_and_preferences(
            cv_text, 
            user_data.get('preferences', 'ANY')
        )
        
        if not email_body or len(email_body) < 10:
            email_body = t(context, 'ai_default_email_body', preferences=user_data.get('preferences', 'ANY'))
        
        targets = []
        
        if TEST_MODE:
            targets = [TEST_TARGET_EMAIL] * 3
            await context.bot.send_message(
                user_id, 
                t(context, 'test_mode_info', email=TEST_TARGET_EMAIL)
            )
        else:
            pref = user_data.get('preferences', '').upper()
            for email, tags in recruiter_db_cache.items():
                if exclude_company != "NONE" and exclude_company.lower() in email.lower():
                    logger.info(t(context, 'excluded_company', email=email))
                    continue
                
                if not pref or 'ANY' in pref or any(p.strip().upper() in str(tags).upper() for p in pref.split(',')):
                    targets.append(email)
        
        await context.bot.send_message(user_id, t(context, 'targets_ready', count=len(targets)))
        logger.info(f"📊 Целей для рассылки: {len(targets)}")
        
        sent_count = 0
        
        for i, email in enumerate(targets):
            logger.info(f"📧 Отправка {i+1}/{len(targets)} на {email}")
            
            sent = await asyncio.to_thread(
                send_email_sync,
                target_email=email,
                subject=f"CV Application: {user_data.get('job_title', 'Seafarer')}",
                body=email_body,
                cv_path=user_data['cv_path'],
                user_reply_to=user_data['email']
            )
            
            if sent:
                sent_count += 1
                if TEST_MODE:
                    await context.bot.send_message(
                        user_id, 
                        t(context, 'test_email_sent', 
                          current=i+1,
                          email=email,
                          body=email_body[:80],
                          reply_to=user_data['email']),
                        parse_mode='HTML'
                    )
            
            await asyncio.sleep(1)

        await context.bot.send_message(
            user_id, 
            t(context, 'distribution_complete', sent_count=sent_count),
            parse_mode='HTML'
        )
        logger.info(f"✅ Рассылка завершена. Успешно: {sent_count}/{len(targets)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в perform_mass_apply: {e}", exc_info=True)
        await context.bot.send_message(
            user_id, 
            t(context, 'distribution_error', error=str(e))
        )

# =================================================================
# HANDLERS
# =================================================================

(OFFER, PAYMENT, EMAIL, UPLOAD, ROLE, PREF, LANGUAGE_SELECT) = range(7)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start с автоопределением языка"""
    logger.info(f"👤 /start от пользователя {update.message.chat_id}")
    
    # Определяем язык пользователя
    detected_lang = detect_language_from_telegram(update)
    set_user_language(context, detected_lang)
    
    # Отправляем приветствие на языке пользователя
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_change_language'), callback_data='change_language')]
    ])
    
    await update.message.reply_text(
        t(context, 'start_welcome'),
        reply_markup=keyboard
    )

async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /language для смены языка"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')],
        [InlineKeyboardButton("🇷🇺 Русский", callback_data='lang_ru')],
        [InlineKeyboardButton("🇺🇦 Українська", callback_data='lang_uk')]
    ])
    
    current_lang = get_user_language(context)
    lang_name = translations[current_lang]['language_name']
    
    await update.message.reply_text(
        t(context, 'language_select', current=lang_name),
        reply_markup=keyboard,
        parse_mode='HTML'
    )

async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик выбора языка"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'change_language':
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🇬🇧 English", callback_data='lang_en')],
            [InlineKeyboardButton("🇷🇺 Русский", callback_data='lang_ru')],
            [InlineKeyboardButton("🇺🇦 Українська", callback_data='lang_uk')]
        ])
        
        current_lang = get_user_language(context)
        lang_name = translations[current_lang]['language_name']
        
        await query.message.reply_text(
            t(context, 'language_select', current=lang_name),
            reply_markup=keyboard,
            parse_mode='HTML'
        )
    elif query.data.startswith('lang_'):
        new_lang = query.data.split('_')[1]
        set_user_language(context, new_lang)
        
        lang_name = translations[new_lang]['language_name']
        await query.message.reply_text(
            t(context, 'language_changed', language=lang_name),
            parse_mode='HTML'
        )

async def start_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🚀 /start_apply от пользователя {update.message.chat_id}")
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_pay'), callback_data='pay')],
        [InlineKeyboardButton(t(context, 'button_admin'), callback_data='admin')]
    ])
    
    await update.message.reply_text(
        t(context, 'start_apply_offer'),
        reply_markup=keyboard
    )
    return PAYMENT

async def pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"💳 Попытка оплаты от {query.message.chat_id}")
    
    try:
        await context.bot.send_invoice(
            query.message.chat_id, 
            t(context, 'payment_invoice_title'),
            t(context, 'payment_invoice_description'),
            "payload", 
            PAYMENT_PROVIDER_TOKEN, 
            "EUR", 
            [LabeledPrice("Service", 5000)]
        )
        return PAYMENT
    except Exception as e:
        logger.warning(f"⚠️ Ошибка тестовой оплаты: {e}. Пропускаем шаг оплаты.")
        await query.message.reply_text(t(context, 'payment_test_mode_skip'))
        await query.message.reply_text(t(context, 'enter_email'), parse_mode='Markdown')
        return EMAIL

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ Успешная оплата от {update.message.chat_id}")
    await update.message.reply_text(t(context, 'payment_success'))
    await update.message.reply_text(t(context, 'enter_email'), parse_mode='Markdown')
    return EMAIL

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"🔐 Запрос админ доступа от {query.message.chat_id}")
    await query.message.reply_text(t(context, 'enter_password'))
    return PAYMENT

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == ADMIN_PASSPHRASE:
        logger.info(f"✅ Админ доступ предоставлен {update.message.chat_id}")
        await update.message.reply_text(t(context, 'password_correct'))
        await update.message.reply_text(t(context, 'enter_email'), parse_mode='Markdown')
        return EMAIL
    else:
        logger.warning(f"❌ Неверный пароль от {update.message.chat_id}")
        await update.message.reply_text(t(context, 'password_incorrect'))
        return PAYMENT

async def save_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    context.user_data['email'] = email
    logger.info(f"📧 Email сохранен: {email}")
    await update.message.reply_text(t(context, 'upload_cv'))
    return UPLOAD

async def save_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text(t(context, 'upload_cv_error'))
        return UPLOAD
    
    logger.info(f"📄 Получен CV: {doc.file_name}")
    f = await doc.get_file()
    path = os.path.join(TEMP_DIR, f"{update.message.chat_id}_{doc.file_name}")
    await f.download_to_drive(path)
    context.user_data['cv_path'] = path
    logger.info(f"💾 CV сохранен: {path}")
    
    await update.message.reply_text(t(context, 'enter_job_title'))
    return ROLE

async def save_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text.strip()
    context.user_data['job_title'] = role
    logger.info(f"⚓ Должность: {role}")
    await update.message.reply_text(t(context, 'enter_preferences'))
    return PREF

async def save_pref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pref = update.message.text.strip()
    context.user_data['preferences'] = pref
    logger.info(f"🚢 Предпочтения: {pref}")
    
    await update.message.reply_text(t(context, 'processing_start'))
    await perform_mass_apply(update.message.chat_id, context, context.user_data)
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🛑 Отмена от {update.message.chat_id}")
    await update.message.reply_text(t(context, 'cancel'))
    return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

# =================================================================
# MAIN
# =================================================================

def main():
    logger.info("=" * 50)
    logger.info("🤖 ЗАПУСК БОТА С МУЛЬТИЯЗЫЧНОСТЬЮ")
    logger.info("=" * 50)
    
    # Загружаем переводы
    load_translations()
    
    # Загружаем базу данных
    load_database()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Conversation Handler
    conv = ConversationHandler(
        entry_points=[CommandHandler('start_apply', start_apply)],
        states={
            PAYMENT: [
                CallbackQueryHandler(pay_handler, pattern='^pay$'),
                CallbackQueryHandler(admin_handler, pattern='^admin$'),
                MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment),
                MessageHandler(filters.TEXT & ~filters.COMMAND, check_passcode)
            ],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_email)],
            UPLOAD: [MessageHandler(filters.Document.ALL, save_cv)],
            ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_role)],
            PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_pref)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('language', language_command))
    app.add_handler(CallbackQueryHandler(language_callback, pattern='^(change_language|lang_)'))
    app.add_handler(conv)
    app.add_handler(PreCheckoutQueryHandler(precheckout))

    logger.info("✅ Бот запущен с поддержкой языков: EN, RU, UK")
    app.run_polling()

if __name__ == '__main__':
    main()
