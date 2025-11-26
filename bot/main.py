# -*- coding: utf-8 -*-
"""
Telegram бот для автоматической рассылки CV моряков в крюинговые компании
Модульная версия с использованием отдельных компонентов
"""
import json
import os
import sys
import asyncio
import logging
import aiohttp

# Добавляем путь к родительской директории для импорта config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

# Импорт наших модулей
from config import settings
from bot.database_manager import DatabaseManager
from bot.email_sender import EmailSender

# =================================================================
# ЛОГИРОВАНИЕ
# =================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=getattr(logging, settings.LOG_LEVEL),
    handlers=[
        logging.FileHandler(settings.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =================================================================
# ГЛОБАЛЬНЫЕ ОБЪЕКТЫ
# =================================================================
db_manager = DatabaseManager(settings.LOCAL_DB_FILE)
email_sender = EmailSender(
    use_gmail=settings.USE_GMAIL,
    gmail_address=settings.GMAIL_ADDRESS,
    gmail_app_password=settings.GMAIL_APP_PASSWORD,
    smtp_server=settings.SMTP_SERVER,
    smtp_port=settings.SMTP_PORT,
    smtp_username=settings.SMTP_USERNAME,
    smtp_password=settings.SMTP_PASSWORD
)

# =================================================================
# МУЛЬТИЯЗЫЧНОСТЬ (i18n)
# =================================================================
translations = {}

def load_translations():
    """Загружает все файлы переводов"""
    global translations
    for lang in settings.SUPPORTED_LANGUAGES:
        file_path = os.path.join(settings.I18N_DIR, f"{lang}.json")
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                translations[lang] = json.load(f)
            logger.info(f"✅ Загружен язык: {lang}")
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки {lang}: {e}")
            translations[lang] = {}

def get_user_language(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Получает язык пользователя из context.user_data"""
    return context.user_data.get('language', settings.DEFAULT_LANGUAGE)

def set_user_language(context: ContextTypes.DEFAULT_TYPE, lang_code: str):
    """Устанавливает язык пользователя"""
    if lang_code in settings.SUPPORTED_LANGUAGES:
        context.user_data['language'] = lang_code
        logger.info(f"🌍 Язык установлен: {lang_code}")

def detect_language_from_telegram(update: Update) -> str:
    """Определяет язык пользователя из Telegram"""
    try:
        user = update.effective_user
        if user and user.language_code:
            lang = user.language_code.lower()[:2]
            if lang in settings.SUPPORTED_LANGUAGES:
                logger.info(f"🌍 Определен язык из Telegram: {lang}")
                return lang
    except Exception as e:
        logger.error(f"Ошибка определения языка: {e}")

    return settings.DEFAULT_LANGUAGE

def t(context: ContextTypes.DEFAULT_TYPE, key: str, **kwargs) -> str:
    """
    Получает переведенный текст для пользователя

    Args:
        context: Telegram context
        key: ключ перевода
        **kwargs: параметры для форматирования строки

    Returns:
        Переведенный и отформатированный текст
    """
    lang = get_user_language(context)
    text = translations.get(lang, {}).get(
        key,
        translations.get(settings.DEFAULT_LANGUAGE, {}).get(key, f"[{key}]")
    )

    try:
        return text.format(**kwargs)
    except KeyError:
        return text

# =================================================================
# AI АНАЛИЗ
# =================================================================

def extract_text_from_pdf(file_path):
    """Извлекает текст из PDF файла"""
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
    """Анализирует CV с помощью Ollama AI"""
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
        "model": settings.MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1}
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(settings.OLLAMA_API_URL, json=payload, timeout=45) as resp:
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
# МАССОВАЯ РАССЫЛКА
# =================================================================

async def perform_mass_apply(user_id, context, user_data):
    """Выполняет массовую рассылку CV"""
    try:
        await context.bot.send_message(user_id, t(context, 'ai_analyzing'))

        cv_text = extract_text_from_pdf(user_data.get('cv_path'))
        email_body, exclude_company = await analyze_cv_and_preferences(
            cv_text,
            user_data.get('preferences', 'ANY')
        )

        if not email_body or len(email_body) < 10:
            email_body = t(
                context,
                'ai_default_email_body',
                preferences=user_data.get('preferences', 'ANY')
            )

        # Получаем целевые email'ы
        if settings.TEST_MODE:
            targets = [settings.TEST_TARGET_EMAIL] * 3
            await context.bot.send_message(
                user_id,
                t(context, 'test_mode_info', email=settings.TEST_TARGET_EMAIL)
            )
        else:
            targets = db_manager.find_matching_emails(
                user_data.get('preferences', 'ANY'),
                exclude_company
            )

        await context.bot.send_message(
            user_id,
            t(context, 'targets_ready', count=len(targets))
        )
        logger.info(f"📊 Целей для рассылки: {len(targets)}")

        sent_count = 0

        for i, email in enumerate(targets):
            logger.info(f"📧 Отправка {i+1}/{len(targets)} на {email}")

            sent = await asyncio.to_thread(
                email_sender.send,
                target_email=email,
                subject=f"CV Application: {user_data.get('job_title', 'Seafarer')}",
                body=email_body,
                cv_path=user_data['cv_path'],
                reply_to=user_data['email']
            )

            if sent:
                sent_count += 1
                if settings.TEST_MODE:
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

    detected_lang = detect_language_from_telegram(update)
    set_user_language(context, detected_lang)

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
    """Начало процесса подачи CV"""
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
    """Обработчик оплаты"""
    query = update.callback_query
    await query.answer()
    logger.info(f"💳 Попытка оплаты от {query.message.chat_id}")

    try:
        await context.bot.send_invoice(
            query.message.chat_id,
            t(context, 'payment_invoice_title'),
            t(context, 'payment_invoice_description'),
            "payload",
            settings.PAYMENT_PROVIDER_TOKEN,
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
    """Обработчик успешной оплаты"""
    logger.info(f"✅ Успешная оплата от {update.message.chat_id}")
    await update.message.reply_text(t(context, 'payment_success'))
    await update.message.reply_text(t(context, 'enter_email'), parse_mode='Markdown')
    return EMAIL

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик админ доступа"""
    query = update.callback_query
    await query.answer()
    logger.info(f"🔐 Запрос админ доступа от {query.message.chat_id}")
    await query.message.reply_text(t(context, 'enter_password'))
    return PAYMENT

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка админ пароля"""
    if update.message.text == settings.ADMIN_PASSPHRASE:
        logger.info(f"✅ Админ доступ предоставлен {update.message.chat_id}")
        await update.message.reply_text(t(context, 'password_correct'))
        await update.message.reply_text(t(context, 'enter_email'), parse_mode='Markdown')
        return EMAIL
    else:
        logger.warning(f"❌ Неверный пароль от {update.message.chat_id}")
        await update.message.reply_text(t(context, 'password_incorrect'))
        return PAYMENT

async def save_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение email пользователя"""
    email = update.message.text.strip()
    context.user_data['email'] = email
    logger.info(f"📧 Email сохранен: {email}")
    await update.message.reply_text(t(context, 'upload_cv'))
    return UPLOAD

async def save_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение CV"""
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text(t(context, 'upload_cv_error'))
        return UPLOAD

    logger.info(f"📄 Получен CV: {doc.file_name}")
    f = await doc.get_file()
    path = os.path.join(settings.TEMP_DIR, f"{update.message.chat_id}_{doc.file_name}")
    await f.download_to_drive(path)
    context.user_data['cv_path'] = path
    logger.info(f"💾 CV сохранен: {path}")

    await update.message.reply_text(t(context, 'enter_job_title'))
    return ROLE

async def save_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение должности"""
    role = update.message.text.strip()
    context.user_data['job_title'] = role
    logger.info(f"⚓ Должность: {role}")
    await update.message.reply_text(t(context, 'enter_preferences'))
    return PREF

async def save_pref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение предпочтений и запуск рассылки"""
    pref = update.message.text.strip()
    context.user_data['preferences'] = pref
    logger.info(f"🚢 Предпочтения: {pref}")

    await update.message.reply_text(t(context, 'processing_start'))
    await perform_mass_apply(update.message.chat_id, context, context.user_data)

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    logger.info(f"🛑 Отмена от {update.message.chat_id}")
    await update.message.reply_text(t(context, 'cancel'))
    return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout"""
    await update.pre_checkout_query.answer(ok=True)

# =================================================================
# MAIN
# =================================================================

def main():
    """Главная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("🤖 ЗАПУСК БОТА (МОДУЛЬНАЯ ВЕРСИЯ)")
    logger.info("=" * 50)

    # Загружаем переводы
    load_translations()

    logger.info(f"📊 База данных: {db_manager.count()} компаний")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).build()

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
    logger.info(f"🧪 Режим: {'TEST' if settings.TEST_MODE else 'PRODUCTION'}")
    app.run_polling()

if __name__ == '__main__':
    main()
