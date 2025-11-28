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
from datetime import datetime

# Добавляем путь к родительской директории для импорта config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    BotCommand,
    MenuButtonCommands,
    ReplyKeyboardMarkup,
    KeyboardButton
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

def load_offer_agreement():
    """Загружает договор оферты из docx файла и добавляет в translations"""
    global translations
    try:
        from docx import Document
        doc_path = 'Оферта_i18n.docx'

        if not os.path.exists(doc_path):
            logger.warning(f"⚠️ Файл {doc_path} не найден")
            return

        doc = Document(doc_path)
        full_text = []

        for para in doc.paragraphs:
            if para.text.strip():
                full_text.append(para.text)

        complete_text = '\n\n'.join(full_text)

        # Разделяем по языкам
        ru_marker = "🇷🇺 ДОГОВОР ПУБЛИЧНОЙ ОФЕРТЫ"
        en_marker = "🇬🇧 PUBLIC OFFER AGREEMENT"
        uk_marker = "🇺🇦 ДОГОВІР ПУБЛІЧНОЇ ОФЕРТИ"

        ru_start = complete_text.find(ru_marker)
        en_start = complete_text.find(en_marker)
        uk_start = complete_text.find(uk_marker)

        if ru_start != -1 and en_start != -1:
            ru_text = complete_text[ru_start:en_start].strip()
            translations['ru']['offer_agreement_text'] = ru_text

        if en_start != -1 and uk_start != -1:
            en_text = complete_text[en_start:uk_start].strip()
            translations['en']['offer_agreement_text'] = en_text

        if uk_start != -1:
            uk_text = complete_text[uk_start:].strip()
            translations['uk']['offer_agreement_text'] = uk_text

        logger.info("✅ Загружен договор оферты из .docx")

    except ImportError:
        logger.error("❌ python-docx не установлен. Используйте: pip install python-docx")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки договора оферты: {e}")

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
        # Проверка админского доступа
        if user_data.get('is_admin'):
            logger.warning("=" * 60)
            logger.warning("⚠️ АДМИНСКАЯ РАССЫЛКА (БЕЗ ОПЛАТЫ)")
            logger.warning(f"👤 User ID: {user_id}")
            logger.warning("=" * 60)

        # ПРАВИЛЬНЫЙ порядок сообщений
        await context.bot.send_message(user_id, t(context, 'ai_analyzing'))
        await context.bot.send_message(user_id, t(context, 'processing_start'))

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

        # Добавляем контакты соискателя в тело письма как резерв
        email_body_with_contact = f"{email_body}\n\n---\nApplicant Contact: {user_data['email']}"

        for i, email in enumerate(targets):
            logger.info(f"📧 Отправка {i+1}/{len(targets)} на {email}")

            sent = await asyncio.to_thread(
                email_sender.send,
                target_email=email,
                subject=f"CV Application: {user_data.get('job_title', 'Seafarer')}",
                body=email_body_with_contact,
                cv_path=user_data['cv_path'],
                reply_to=user_data['email'],
                applicant_email=user_data['email']  # Для OAuth2 Reply-To
            )

            if sent:
                sent_count += 1
                if settings.TEST_MODE:
                    await context.bot.send_message(
                        user_id,
                        t(context, 'test_email_sent',
                          current=i+1,
                          email=email,
                          body=email_body_with_contact[:100],
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
    """Обработчик команды /start с автоопределением языка и поддержкой deep links"""
    logger.info(f"👤 /start от пользователя {update.message.chat_id}")

    detected_lang = detect_language_from_telegram(update)
    set_user_language(context, detected_lang)

    # Проверяем наличие deep link параметра
    if context.args and len(context.args) > 0:
        deep_link_param = context.args[0]
        logger.info(f"🔗 Deep link параметр: {deep_link_param}")

        # Обработка deep link параметров
        if deep_link_param == 'apply':
            # Запускаем процесс рассылки CV
            return await start_apply(update, context)
        elif deep_link_param == 'vacancies':
            # Показываем вакансии
            return await vacancies_command(update, context)
        elif deep_link_param == 'resume':
            # Показываем резюме пользователя
            return await resume_command(update, context)
        elif deep_link_param == 'pricing':
            # Показываем тарифы
            return await pricing_command(update, context)
        elif deep_link_param == 'help':
            # Показываем помощь
            return await help_command(update, context)
        elif deep_link_param == 'support':
            # Показываем поддержку
            return await support_command(update, context)

    # Обычный запуск без deep link
    await update.message.reply_text(t(context, 'start_welcome'))

    # Показываем главное меню
    await show_main_menu(update.message, context)

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

async def show_main_menu(message, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню с основными функциями бота (ReplyKeyboard кнопки внизу экрана)"""
    keyboard = [
        [KeyboardButton(t(context, 'button_send_cv')), KeyboardButton(t(context, 'button_vacancies'))],
        [KeyboardButton(t(context, 'button_my_resume')), KeyboardButton(t(context, 'button_tariffs'))],
        [KeyboardButton(t(context, 'button_help')), KeyboardButton(t(context, 'button_support'))],
        [KeyboardButton(t(context, 'button_change_language'))]
    ]

    reply_markup = ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True,  # Автоматически подстраивает размер кнопок
        one_time_keyboard=False  # Клавиатура остается после нажатия
    )

    await message.reply_text(
        t(context, 'main_menu'),
        reply_markup=reply_markup,
        parse_mode='HTML'
    )

async def menu_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатий на ReplyKeyboard кнопки главного меню"""
    text = update.message.text
    logger.info(f"📋 Нажата кнопка меню: '{text}' от пользователя {update.message.chat_id}")

    # Получаем тексты кнопок на текущем языке
    button_send_cv = t(context, 'button_send_cv')
    button_vacancies = t(context, 'button_vacancies')
    button_my_resume = t(context, 'button_my_resume')
    button_tariffs = t(context, 'button_tariffs')
    button_help = t(context, 'button_help')
    button_support = t(context, 'button_support')
    button_change_language = t(context, 'button_change_language')

    # Обработка нажатий
    if text == button_send_cv:
        # "🚀 Разослать CV"
        await start_apply(update, context)
    elif text == button_vacancies:
        # "💼 Вакансии"
        await vacancies_command(update, context)
    elif text == button_my_resume:
        # "📝 Мое резюме"
        await resume_command(update, context)
    elif text == button_tariffs:
        # "💰 Тарифы"
        await pricing_command(update, context)
    elif text == button_help:
        # "ℹ️ Помощь"
        await help_command(update, context)
    elif text == button_support:
        # "📞 Поддержка"
        await support_command(update, context)
    elif text == button_change_language:
        # "🌍 Сменить язык"
        await language_command(update, context)

async def main_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик кнопок главного меню (для InlineKeyboard в старых сообщениях)"""
    query = update.callback_query
    await query.answer()
    logger.info(f"📋 Callback: {query.data} от пользователя {query.message.chat_id}")

    if query.data == 'back_to_menu':
        # Кнопка "🔙 Назад в меню" - показываем главное меню
        await show_main_menu(query.message, context)
    elif query.data == 'vacancies':
        # Кнопка "💼 Вакансии" - показываем информацию о канале с вакансиями
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_open_vacancies_channel'), url='https://t.me/OnlyOffshore')]
        ])
        await query.message.reply_text(
            t(context, 'vacancies_message'),
            reply_markup=keyboard
        )
    elif query.data == 'my_resume':
        # Кнопка "📝 Мое резюме" - показываем информацию о CV или предлагаем загрузить
        cv_message_id = context.user_data.get('cv_message_id')

        if cv_message_id:
            # CV загружено - показываем информацию с кнопками
            cv_filename = context.user_data.get('cv_filename', 'unknown.pdf')
            cv_upload_date = context.user_data.get('cv_upload_date', datetime.now())

            # Форматируем дату
            upload_date_str = cv_upload_date.strftime('%d.%m.%Y %H:%M')

            # Формируем ссылку на сообщение с CV
            # Для приватного чата используем abs(chat_id)
            chat_id = abs(query.message.chat_id)
            cv_url = f"https://t.me/c/{chat_id}/{cv_message_id}"

            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(context, 'button_open_cv'), url=cv_url)],
                [InlineKeyboardButton(t(context, 'button_upload_new_cv'), callback_data='start_apply')]
            ])

            await query.message.reply_text(
                t(context, 'my_resume_with_cv', cv_filename=cv_filename, upload_date=upload_date_str),
                reply_markup=keyboard
            )
        else:
            # CV не загружено - предлагаем начать процесс рассылки
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(context, 'button_send_cv'), callback_data='start_apply')]
            ])

            await query.message.reply_text(
                t(context, 'my_resume_no_cv'),
                reply_markup=keyboard
            )
    elif query.data == 'pricing':
        # Кнопка "💰 Тарифы" - показываем подробную информацию о тарифах
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
        ])
        await query.message.reply_text(
            t(context, 'pricing_message'),
            reply_markup=keyboard
        )
    elif query.data == 'help':
        # Кнопка "ℹ️ Помощь" - показываем FAQ с кнопкой "Назад в меню"
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
        ])
        await query.message.reply_text(
            t(context, 'help_faq'),
            reply_markup=keyboard
        )
    elif query.data == 'support':
        # Кнопка "📞 Поддержка" - показываем информацию о поддержке с кнопкой открытия группы
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_open_support'), url='https://t.me/SUPPORT_GROUP')],
            [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
        ])
        await query.message.reply_text(
            t(context, 'support_message'),
            reply_markup=keyboard
        )

async def publish_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикует меню бота в канале (только для админа)"""
    user_id = update.message.chat_id
    logger.info(f"📢 /publish_menu от пользователя {user_id}")
    logger.info(f"🔑 ADMIN_USER_IDS: {settings.ADMIN_USER_IDS}")

    # Проверка прав администратора
    if settings.ADMIN_USER_IDS and user_id not in settings.ADMIN_USER_IDS:
        await update.message.reply_text(f"❌ У вас нет прав для выполнения этой команды\n\nВаш ID: {user_id}\nАдмины: {settings.ADMIN_USER_IDS}")
        logger.warning(f"⚠️ Попытка использования /publish_menu пользователем {user_id} (не админ)")
        return
    elif not settings.ADMIN_USER_IDS:
        logger.warning(f"⚠️ ADMIN_USER_IDS не настроен! Разрешаем /publish_menu для {user_id}")
        await update.message.reply_text("⚠️ ADMIN_USER_IDS не настроен в .env\nДоступ разрешен, но рекомендуется настроить в продакшн")

    # Определяем язык для меню
    lang = get_user_language(context)

    # Создаем клавиатуру с кнопками (2 колонки)
    bot_username = settings.BOT_USERNAME
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(context, 'button_send_cv'), url=f'https://t.me/{bot_username}?start=apply'),
            InlineKeyboardButton(t(context, 'button_vacancies'), url='https://t.me/OnlyOffshore')  # Прямая ссылка на канал
        ],
        [
            InlineKeyboardButton(t(context, 'button_my_resume'), url=f'https://t.me/{bot_username}?start=resume'),
            InlineKeyboardButton(t(context, 'button_tariffs'), url=f'https://t.me/{bot_username}?start=pricing')
        ],
        [
            InlineKeyboardButton(t(context, 'button_help'), url=f'https://t.me/{bot_username}?start=help'),
            InlineKeyboardButton(t(context, 'button_support'), url=f'https://t.me/{bot_username}?start=support')
        ]
    ])

    # Публикуем красивый пост
    sent_message = await update.message.reply_text(
        t(context, 'channel_menu_post'),
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    # Автоматически закрепляем меню
    try:
        await context.bot.pin_chat_message(
            chat_id=update.message.chat_id,
            message_id=sent_message.message_id,
            disable_notification=True
        )
        logger.info("=" * 60)
        logger.info("📌 МЕНЮ АВТОМАТИЧЕСКИ ЗАКРЕПЛЕНО")
        logger.info(f"💬 Chat ID: {update.message.chat_id}")
        logger.info(f"📨 Message ID: {sent_message.message_id}")
        logger.info("=" * 60)
    except Exception as e:
        logger.warning(f"⚠️ Не удалось закрепить меню: {e}")
        logger.warning("Убедитесь что бот - администратор в канале с правами на закрепление сообщений")

    logger.info(f"✅ Меню опубликовано пользователем {user_id} на языке {lang}")

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

        # Показываем главное меню на новом языке
        await show_main_menu(query.message, context)

async def start_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Начало процесса подачи CV - показываем договор оферты"""
    # Определяем откуда пришел запрос - команда или callback
    if update.callback_query:
        query = update.callback_query
        await query.answer()
        user_id = query.message.chat_id
        message = query.message
        logger.info(f"🚀 start_apply (callback) от пользователя {user_id}")
    else:
        user_id = update.message.chat_id
        message = update.message
        logger.info(f"🚀 /start_apply от пользователя {user_id}")

    # Получаем превью договора (первые 500 символов)
    full_offer = t(context, 'offer_agreement_text')
    preview = full_offer[:500] + "...\n\n" + t(context, 'offer_preview')

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_agree_terms'), callback_data='agree_terms')],
        [InlineKeyboardButton(t(context, 'button_read_full'), callback_data='read_full_offer')],
        [InlineKeyboardButton(t(context, 'cancel'), callback_data='cancel_offer')]
    ])

    await message.reply_text(
        f"{t(context, 'offer_title')}\n\n{preview}",
        reply_markup=keyboard,
        parse_mode='HTML'
    )

    logger.info("=" * 60)
    logger.info("📍 start_apply ЗАВЕРШЁН")
    logger.info(f"👤 User ID: {user_id}")
    logger.info("➡️  Переход в состояние: OFFER")
    logger.info("=" * 60)

    return OFFER

async def agree_terms_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик согласия с условиями"""
    query = update.callback_query
    await query.answer()

    logger.info("🔔" * 30)
    logger.info("🔔 CALLBACK ПОЛУЧЕН: agree_terms")
    logger.info(f"👤 User ID: {query.from_user.id}")
    logger.info(f"📋 Callback data: {query.data}")
    logger.info("🔔" * 30)

    user_id = query.from_user.id

    logger.info("=" * 60)
    logger.info("✅ ПОЛЬЗОВАТЕЛЬ СОГЛАСИЛСЯ С ОФЕРТОЙ")
    logger.info(f"👤 User ID: {user_id}")
    logger.info(f"📋 Callback data: {query.data}")
    logger.info(f"➡️  Переход к состоянию: PAYMENT")
    logger.info("=" * 60)

    # Показываем кнопку оплаты
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_pay'), callback_data='pay')]
    ])

    # КРИТИЧНО: используем edit_message_text чтобы редактировать текущее сообщение
    # а не создавать новое (иначе ConversationHandler теряет контекст!)
    await query.edit_message_text(
        text=t(context, 'start_apply_offer'),
        reply_markup=keyboard
    )

    return PAYMENT

async def read_full_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик показа полного текста договора"""
    query = update.callback_query
    await query.answer()
    logger.info(f"📄 CALLBACK ПОЛУЧЕН: read_full_offer от {query.from_user.id}")

    # Показываем полный текст договора
    full_offer = t(context, 'offer_agreement_text')

    # Telegram ограничивает длину сообщения 4096 символов
    # Если текст длиннее, разбиваем на части
    max_length = 4000
    if len(full_offer) > max_length:
        # Разбиваем на части
        parts = [full_offer[i:i+max_length] for i in range(0, len(full_offer), max_length)]
        for part in parts:
            await query.message.reply_text(part)
    else:
        await query.message.reply_text(full_offer)

    # Показываем кнопки снова
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_agree_terms'), callback_data='agree_terms')],
        [InlineKeyboardButton(t(context, 'cancel'), callback_data='cancel_offer')]
    ])

    await query.message.reply_text(
        t(context, 'offer_preview'),
        reply_markup=keyboard
    )
    return OFFER

async def cancel_offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик отмены"""
    query = update.callback_query
    await query.answer()
    logger.info(f"❌ Callback: {query.data} от пользователя {query.message.chat_id}")

    # Используем edit_message_text для редактирования текущего сообщения
    await query.edit_message_text(
        text=t(context, 'cancel')
    )
    return ConversationHandler.END

async def check_admin_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка админ кода для пропуска оплаты"""
    text = update.message.text.strip()
    user_id = update.effective_user.id

    if text == settings.ADMIN_PASSPHRASE:
        # Админ код верный - пропускаем оплату
        context.user_data['payment_status'] = 'admin_bypass'
        context.user_data['is_admin'] = True

        logger.warning("=" * 60)
        logger.warning("🔑 АДМИН КОД ИСПОЛЬЗОВАН")
        logger.warning(f"👤 User ID: {user_id}")
        logger.warning(f"🔐 Passphrase: {text}")
        logger.warning("⚠️ ОПЛАТА ПРОПУЩЕНА")
        logger.warning("=" * 60)

        await update.message.reply_text(
            "✅ Админ доступ подтверждён\n"
            "⚠️ Оплата пропущена\n\n"
            "📧 Введите Email соискателя:"
        )

        return EMAIL
    else:
        # Неверный код - показываем сообщение об оплате снова
        await update.message.reply_text(
            "❓ Для продолжения нажмите кнопку оплаты.\n\n"
            "Если у вас есть админ код, введите его."
        )
        return PAYMENT


async def pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик оплаты"""
    query = update.callback_query
    await query.answer()
    logger.info(f"💳 Callback: {query.data} от пользователя {query.message.chat_id}")

    # Показываем инструкцию в зависимости от режима
    if settings.TEST_MODE:
        test_payment_instruction = """🧪 <b>ТЕСТОВЫЙ РЕЖИМ</b>

Для продолжения:
• Оплатите тестовой картой
• Или введите админ код

<b>Тестовая карта:</b>
💳 <b>Номер:</b> <code>4444 3333 2222 1111</code>
📅 <b>Срок:</b> <code>01/29</code>
🔐 <b>CVV:</b> <code>111</code>

⚠️ Деньги НЕ будут списаны!

Сейчас откроется форма оплаты Telegram."""
        await query.message.reply_text(test_payment_instruction, parse_mode='HTML')
    else:
        await query.message.reply_text(
            "💳 Сейчас откроется форма оплаты.\n\n"
            "Стоимость: 50 EUR"
        )

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
        logger.error(f"❌ Ошибка send_invoice: {e}")
        await query.message.reply_text(
            f"❌ Ошибка создания платежа\n\n"
            f"Возможные причины:\n"
            f"• Проблемы с платежным провайдером\n"
            f"• Неверный PAYMENT_PROVIDER_TOKEN\n\n"
            f"Технические детали: {str(e)[:100]}"
        )
        # Не пропускаем оплату при ошибке создания invoice
        return PAYMENT

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик pre-checkout query (перед оплатой)"""
    query = update.pre_checkout_query
    user_id = query.from_user.id

    # Telegram требует ответ на pre-checkout query
    # Всегда подтверждаем (ok=True)
    await query.answer(ok=True)

    logger.info(f"✅ Pre-checkout OK для пользователя {user_id}")
    logger.info(f"💰 Сумма: {query.total_amount} {query.currency}")
    logger.info(f"📦 Invoice payload: {query.invoice_payload}")


async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик успешной оплаты"""
    payment = update.message.successful_payment
    user_id = update.effective_user.id

    # Сохраняем данные об оплате
    context.user_data['payment_status'] = 'paid'
    context.user_data['payment_id'] = payment.telegram_payment_charge_id
    context.user_data['payment_amount'] = payment.total_amount
    context.user_data['payment_currency'] = payment.currency

    logger.info("=" * 60)
    logger.info("💰 УСПЕШНАЯ ОПЛАТА")
    logger.info(f"👤 User ID: {user_id}")
    logger.info(f"💵 Сумма: {payment.total_amount} {payment.currency}")
    logger.info(f"🔖 Payment ID: {payment.telegram_payment_charge_id}")
    logger.info(f"🆔 Provider Charge ID: {payment.provider_payment_charge_id}")
    logger.info("=" * 60)

    await update.message.reply_text(
        "✅ Оплата успешна!\n\n"
        "📧 Введите ваш Email (на него крюинги будут отвечать):"
    )

    return EMAIL

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

    # Сохраняем дополнительные данные для кнопки "Мое резюме"
    context.user_data['cv_message_id'] = update.message.message_id
    context.user_data['cv_filename'] = doc.file_name
    context.user_data['cv_upload_date'] = datetime.now()

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

    # Сообщения о процессе теперь внутри perform_mass_apply
    await perform_mass_apply(update.message.chat_id, context, context.user_data)

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Отмена операции"""
    logger.info(f"🛑 Отмена от {update.message.chat_id}")
    await update.message.reply_text(t(context, 'cancel'))
    return ConversationHandler.END

async def unknown_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик неизвестных callback'ов для отладки"""
    query = update.callback_query
    await query.answer()
    logger.warning("⚠️" * 30)
    logger.warning(f"⚠️ НЕИЗВЕСТНЫЙ CALLBACK: {query.data}")
    logger.warning(f"👤 User ID: {query.from_user.id}")
    logger.warning(f"📨 Message ID: {query.message.message_id if query.message else 'N/A'}")
    logger.warning("⚠️" * 30)

# =================================================================
# COMMAND HANDLERS (для работы в десктопе и через slash commands)
# =================================================================

async def vacancies_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /vacancies"""
    logger.info(f"💼 /vacancies от пользователя {update.message.chat_id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_open_vacancies_channel'), url='https://t.me/OnlyOffshore')]
    ])
    await update.message.reply_text(
        t(context, 'vacancies_message'),
        reply_markup=keyboard
    )

async def resume_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /resume"""
    logger.info(f"📝 /resume от пользователя {update.message.chat_id}")
    cv_message_id = context.user_data.get('cv_message_id')

    if cv_message_id:
        cv_filename = context.user_data.get('cv_filename', 'unknown.pdf')
        cv_upload_date = context.user_data.get('cv_upload_date', datetime.now())
        upload_date_str = cv_upload_date.strftime('%d.%m.%Y %H:%M')

        chat_id = abs(update.message.chat_id)
        cv_url = f"https://t.me/c/{chat_id}/{cv_message_id}"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_open_cv'), url=cv_url)],
            [InlineKeyboardButton(t(context, 'button_upload_new_cv'), callback_data='start_apply')]
        ])

        await update.message.reply_text(
            t(context, 'my_resume_with_cv', cv_filename=cv_filename, upload_date=upload_date_str),
            reply_markup=keyboard
        )
    else:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(context, 'button_send_cv'), callback_data='start_apply')]
        ])

        await update.message.reply_text(
            t(context, 'my_resume_no_cv'),
            reply_markup=keyboard
        )

async def pricing_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /pricing"""
    logger.info(f"💰 /pricing от пользователя {update.message.chat_id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
    ])
    await update.message.reply_text(
        t(context, 'pricing_message'),
        reply_markup=keyboard
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /help"""
    logger.info(f"ℹ️ /help от пользователя {update.message.chat_id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
    ])
    await update.message.reply_text(
        t(context, 'help_faq'),
        reply_markup=keyboard
    )

async def support_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /support"""
    logger.info(f"📞 /support от пользователя {update.message.chat_id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(context, 'button_open_support'), url='https://t.me/SUPPORT_GROUP')],
        [InlineKeyboardButton(t(context, 'button_back_to_menu'), callback_data='back_to_menu')]
    ])
    await update.message.reply_text(
        t(context, 'support_message'),
        reply_markup=keyboard
    )

# =================================================================
# MENU BUTTON & COMMANDS SETUP
# =================================================================

async def post_init(application: Application):
    """Настройка Menu Button и команд бота после инициализации"""
    try:
        logger.info("=" * 60)
        logger.info("🎛️  НАСТРОЙКА BOT MENU BUTTON И КОМАНД")
        logger.info("=" * 60)

        # Устанавливаем команды бота
        commands = [
            BotCommand("start", "🏠 Главное меню"),
            BotCommand("apply", "🚀 Разослать CV"),
            BotCommand("vacancies", "💼 Вакансии"),
            BotCommand("resume", "📝 Мое резюме"),
            BotCommand("pricing", "💰 Тарифы"),
            BotCommand("help", "ℹ️ Помощь"),
            BotCommand("support", "📞 Поддержка"),
            BotCommand("language", "🌍 Сменить язык"),
        ]

        await application.bot.set_my_commands(commands)
        logger.info(f"✅ Установлено {len(commands)} команд бота")
        for cmd in commands:
            logger.info(f"   /{cmd.command} - {cmd.description}")

        # Устанавливаем Menu Button (кнопка "Меню" слева внизу)
        await application.bot.set_chat_menu_button(
            menu_button=MenuButtonCommands()
        )
        logger.info("✅ Menu Button установлен (кнопка слева внизу)")
        logger.info("=" * 60)

    except Exception as e:
        logger.warning(f"⚠️ Ошибка настройки Menu Button/Commands: {e}")

# =================================================================
# MAIN
# =================================================================

def main():
    """Главная функция запуска бота"""
    logger.info("=" * 50)
    logger.info("🤖 ЗАПУСК БОТА (МОДУЛЬНАЯ ВЕРСИЯ)")
    logger.info("=" * 50)

    # Проверка критических переменных окружения
    if not settings.TELEGRAM_BOT_TOKEN or settings.TELEGRAM_BOT_TOKEN == "your_bot_token_here":
        logger.error("❌ ОШИБКА: TELEGRAM_BOT_TOKEN не установлен в .env файле!")
        logger.error("Создайте .env файл и добавьте: TELEGRAM_BOT_TOKEN=ваш_токен")
        sys.exit(1)

    if not settings.GMAIL_APP_PASSWORD or settings.GMAIL_APP_PASSWORD == "your_app_password_here":
        logger.warning("⚠️ WARNING: GMAIL_APP_PASSWORD не установлен в .env файле!")
        logger.warning("Email рассылка не будет работать. Добавьте в .env: GMAIL_APP_PASSWORD=ваш_пароль")

    # Загружаем переводы
    load_translations()

    # Загружаем договор оферты из docx
    load_offer_agreement()

    logger.info(f"📊 База данных: {db_manager.count()} компаний")

    app = Application.builder().token(settings.TELEGRAM_BOT_TOKEN).post_init(post_init).build()

    # Conversation Handler
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start_apply', start_apply),
            CallbackQueryHandler(start_apply, pattern='^start_apply$')
        ],
        states={
            OFFER: [
                CallbackQueryHandler(agree_terms_handler, pattern='^agree_terms$'),
                CallbackQueryHandler(read_full_offer_handler, pattern='^read_full_offer$'),
                CallbackQueryHandler(cancel_offer_handler, pattern='^cancel_offer$')
            ],
            PAYMENT: [
                CallbackQueryHandler(pay_handler, pattern='^pay$'),
                MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment),
                MessageHandler(filters.TEXT & ~filters.COMMAND, check_admin_code)  # Проверка админ кода
            ],
            EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_email)],
            UPLOAD: [MessageHandler(filters.Document.ALL, save_cv)],
            ROLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_role)],
            PREF: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_pref)],
        },
        fallbacks=[
            CommandHandler('cancel', cancel),
            CallbackQueryHandler(unknown_callback_handler)  # Ловит все неизвестные callbacks для отладки
        ]
    )

    # Handlers
    app.add_handler(CommandHandler('start', start))
    app.add_handler(CommandHandler('language', language_command))
    app.add_handler(CommandHandler('publish_menu', publish_menu))

    # Command handlers для работы в десктопе и через меню команд
    app.add_handler(CommandHandler('apply', start_apply))
    app.add_handler(CommandHandler('vacancies', vacancies_command))
    app.add_handler(CommandHandler('resume', resume_command))
    app.add_handler(CommandHandler('pricing', pricing_command))
    app.add_handler(CommandHandler('help', help_command))
    app.add_handler(CommandHandler('support', support_command))

    app.add_handler(CallbackQueryHandler(language_callback, pattern='^(change_language|lang_)'))
    app.add_handler(CallbackQueryHandler(main_menu_callback, pattern='^(vacancies|my_resume|pricing|help|support|back_to_menu)$'))
    app.add_handler(conv)
    app.add_handler(PreCheckoutQueryHandler(precheckout))

    # MessageHandler для ReplyKeyboard кнопок меню (должен быть ПОСЛЕ conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, menu_button_handler))

    logger.info("✅ Бот запущен с поддержкой языков: EN, RU, UK")
    logger.info(f"🧪 Режим: {'TEST' if settings.TEST_MODE else 'PRODUCTION'}")
    app.run_polling()

if __name__ == '__main__':
    main()
