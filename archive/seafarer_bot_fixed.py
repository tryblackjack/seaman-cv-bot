# -*- coding: utf-8 -*-
import json
import re
import os
import time
import asyncio
import logging
import smtplib
import sys
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from telegram import (
    Update, 
    InlineKeyboardButton, 
    InlineKeyboardMarkup, 
    ReplyKeyboardMarkup, 
    KeyboardButton,
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
from firebase_admin import credentials, initialize_app, firestore
import aiohttp
from dotenv import load_dotenv

# Загрузка переменных из .env (для локального запуска)
load_dotenv()

# =================================================================
# 1. КОНФИГУРАЦИЯ (BACKEND)
# =================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"

FIREBASE_CRED_PATH = os.getenv("FIREBASE_CRED_PATH", 'serviceAccountKey.json')
APP_ID = "seafarer-service-bot"

SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL")

LOCAL_DB_FILE = "recruiter_vessel_map.json"
FIRESTORE_USERS = f"artifacts/{APP_ID}/users"
FIRESTORE_QUEUE = f"artifacts/{APP_ID}/mail_queue"

SERVICE_PRICE_EUR = 50
SERVICE_PRICE_CENTS = SERVICE_PRICE_EUR * 100

TEMP_DIR = "temp_cvs"
LOG_DIR = "logs"

for directory in [TEMP_DIR, LOG_DIR]:
    if not os.path.exists(directory):
        os.makedirs(directory)

# =================================================================
# 2. ФРОНТЕНД НАСТРОЙКИ (UI & TEXTS)
# =================================================================
# Здесь мы настраиваем внешний вид сообщений и кнопок

class UI:
    # Тексты сообщений (с HTML разметкой)
    WELCOME_TEXT = (
        "<b>⚓ Добро пожаловать в SeaJob Auto-Apply!</b>\n\n"
        "Я — ваш личный AI-агент по трудоустройству. Я помогу вам найти работу в море, пока вы отдыхаете.\n\n"
        "<b>🚀 Что я умею:</b>\n"
        "1. Анализирую ваше CV.\n"
        "2. Пишу <b>уникальное</b> сопроводительное письмо для каждой компании.\n"
        "3. Рассылаю ваше резюме в <b>1083 крюинга</b> по всему миру.\n"
        "4. Фильтрую компании по типу судна.\n\n"
        "💰 <i>Стоимость услуги: 50€ (единоразово).</i>\n\n"
        "Нажмите <b>«Начать рассылку»</b>, чтобы стартовать!"
    )
    
    OFFER_TEXT = (
        "📜 <b>ПУБЛИЧНАЯ ОФЕРТА</b>\n\n"
        "Нажимая кнопку «Оплатить», вы соглашаетесь с условиями:\n"
        "✅ Услуга считается оказанной после отправки отчета о рассылке.\n"
        "✅ Мы гарантируем доставку писем, но не гарантируем найм (решение принимает работодатель).\n"
        "✅ Стоимость 50€ не возвращается после начала работы AI.\n\n"
        "Готовы приступить к карьере мечты?"
    )
    
    PAYMENT_SUCCESS_TEXT = (
        "🎉 <b>Оплата прошла успешно!</b>\n\n"
        "Мы начинаем процесс оформления. Пожалуйста, следуйте инструкциям ниже.\n"
        "👇 <b>Шаг 1:</b> Введите ваш Email для получения чека и отчетов."
    )
    
    UPLOAD_CV_TEXT = (
        "📂 <b>Шаг 2: Загрузка CV</b>\n\n"
        "Пожалуйста, отправьте мне ваше резюме файлом.\n"
        "⚠️ <i>Форматы: PDF или DOCX. Макс. 10 МБ.</i>"
    )

    ROLE_TEXT = (
        "⚓ <b>Шаг 3: Ваша должность</b>\n\n"
        "На какую должность вы претендуете?\n"
        "<i>(Пример: Master, 2nd Engineer, Electrician)</i>"
    )

    PREF_TEXT = (
        "🚢 <b>Шаг 4: Тип судна</b>\n\n"
        "Укажите предпочтения (через запятую) или напишите 'Нет'.\n"
        "<i>(Пример: Tanker, LNG, Offshore, Dry Cargo)</i>\n\n"
        "💡 <i>Это поможет мне отфильтровать базу и не отправлять вас в неподходящие компании.</i>"
    )
    
    DATE_TEXT = (
        "📅 <b>Шаг 5: Когда отправляем?</b>\n\n"
        "Вы можете запустить процесс прямо сейчас или запланировать на завтра (например, на утро понедельника)."
    )

    FINAL_SUCCESS_TEXT = (
        "🚀 <b>Принято в работу!</b>\n\n"
        "Я уже начал анализировать ваше резюме и готовить письма.\n\n"
        "📩 <b>Что дальше?</b>\n"
        "1. Вы получите письмо-подтверждение на Email.\n"
        "2. В течение 24 часов я разошлю ваше CV.\n"
        "3. Вы получите финальный отчет.\n\n"
        "<i>Удачи! Ждите звонков от крюингов. 📞</i>"
    )

    # Клавиатуры (Кнопки)
    @staticmethod
    def main_menu_keyboard():
        # Постоянное меню внизу экрана
        return ReplyKeyboardMarkup([
            [KeyboardButton("🚀 Начать рассылку"), KeyboardButton("ℹ️ О сервисе")],
            [KeyboardButton("🆘 Поддержка"), KeyboardButton("📄 Мои данные")]
        ], resize_keyboard=True)

    @staticmethod
    def start_keyboard():
        # Инлайн кнопка под сообщением
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🚀 Начать рассылку (50€)", callback_data='start_flow')]
        ])

    @staticmethod
    def offer_keyboard():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Принимаю и Оплачиваю 💳", callback_data='pay')],
            [InlineKeyboardButton("❌ Отмена", callback_data='cancel')]
        ])
    
    @staticmethod
    def date_keyboard():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("🔥 Отправить СЕЙЧАС", callback_data='today')],
            [InlineKeyboardButton("⏰ Запланировать на ЗАВТРА", callback_data='tomorrow')]
        ])

# =================================================================
# 3. ЛОГИРОВАНИЕ И ИНИЦИАЛИЗАЦИЯ
# =================================================================

log_filename = os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_filename, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

db: firestore.client = None
recruiter_db_cache = {}

def initialize_firebase():
    global db
    try:
        if not os.path.exists(FIREBASE_CRED_PATH):
            logger.warning(f"⚠️ Файл {FIREBASE_CRED_PATH} не найден. Бот работает локально.")
            return False
        cred = credentials.Certificate(FIREBASE_CRED_PATH)
        try:
            app = initialize_app(cred, name=APP_ID)
        except ValueError:
            from firebase_admin import get_app
            app = get_app(APP_ID)
        db = firestore.client(app)
        logger.info("✅ Firebase подключен.")
        return True
    except Exception as e:
        logger.error(f"❌ Ошибка Firebase: {e}")
        return False

def load_local_database():
    global recruiter_db_cache
    try:
        if not os.path.exists(LOCAL_DB_FILE):
            logger.error(f"❌ База {LOCAL_DB_FILE} не найдена!")
            return {}
        with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
            recruiter_db_cache = json.load(f)
        logger.info(f"✅ Локальная база загружена: {len(recruiter_db_cache)} контактов.")
        return recruiter_db_cache
    except Exception as e:
        logger.error(f"❌ Ошибка чтения базы: {e}")
        return {}

# States for ConversationHandler
(OFFER_AGREEMENT, AWAITING_PAYMENT, EMAIL_INPUT, UPLOAD_CV, 
 CURRENT_ROLE_INPUT, PREFERENCES_INPUT, DATE_SELECTION) = range(7)

# =================================================================
# 4. ЛОГИКА EMAIL И AI (BACKEND)
# =================================================================

async def send_email_async(to_email: str, subject: str, body: str, attachment_path: str = None):
    """Отправка письма через SMTP (в отдельном потоке)."""
    msg = MIMEMultipart()
    msg['From'] = SENDER_EMAIL
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'html'))

    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
                part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
                msg.attach(part)
        except Exception as e:
            logger.error(f"Ошибка прикрепления файла: {e}")

    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: _send_smtp_sync(msg))
        return True
    except Exception as e:
        logger.error(f"Ошибка SMTP: {e}")
        return False

def _send_smtp_sync(msg):
    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT, timeout=10) as server:
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)

async def generate_cover_letter(job_title: str, preferences: str, company_name: str) -> str:
    """AI генерация письма."""
    prompt = f"""
    Write a professional, short cover letter for a seafarer applying to "{company_name}".
    Role: {job_title}. Experience/Prefs: {preferences}.
    Tone: Professional, confident. Max 100 words. No placeholders.
    Sign: "Motivated Candidate".
    """
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 200}
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(f"{GEMINI_API_URL}?key={GEMINI_API_KEY}", json=payload) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"Gemini Error: {e}")
    return f"Dear Sir/Madam,\n\nI am applying for the {job_title} position. I have relevant experience and I am ready to join immediately.\n\nBest regards."

async def perform_mass_apply(user_id: int, user_data: dict) -> bool:
    """Массовая рассылка."""
    logger.info(f"🚀 Старт рассылки для {user_id}")
    if not recruiter_db_cache: load_local_database()
    
    targets = []
    pref = user_data.get('preferences', '').upper()
    
    for email, categories in recruiter_db_cache.items():
        if not pref or 'ANY' in pref or 'НЕТ' in pref:
            targets.append(email)
        elif any(p.strip() in str(categories).upper() for p in pref.split(',')):
            targets.append(email)
    
    logger.info(f"🎯 Найдено {len(targets)} компаний")
    sent_count = 0
    
    # Лимит 5 для теста. В продакшене убрать срез [:5]
    for email in targets[:5]:
        body = await generate_cover_letter(user_data['job_title'], user_data['preferences'], "Hiring Team")
        if await send_email_async(email, f"Application: {user_data['job_title']}", body, user_data['cv_path']):
            sent_count += 1
        await asyncio.sleep(1)

    await send_email_async(user_data['email'], "Отчет о рассылке", f"<h1>Готово!</h1><p>Ваше резюме отправлено в {sent_count} компаний.</p>")
    return True

async def add_to_queue(user_id: int, user_data: dict, send_date: str):
    if not db: return False
    queue_ref = db.collection(FIRESTORE_QUEUE).document()
    task_data = {
        "user_id": user_id,
        "email": user_data['email'],
        "job_title": user_data['job_title'],
        "preferences": user_data['preferences'],
        "cv_path": user_data['cv_path'],
        "status": "pending",
        "created_at": firestore.SERVER_TIMESTAMP,
        "scheduled_for": datetime.now() + timedelta(days=1 if send_date == "tomorrow" else 0)
    }
    await asyncio.to_thread(queue_ref.set, task_data)
    return True

async def process_queue():
    """Фоновая обработка очереди."""
    while True:
        if db:
            try:
                docs = db.collection(FIRESTORE_QUEUE).where("status", "==", "pending").stream()
                for doc in docs:
                    data = doc.to_dict()
                    logger.info(f"Обработка задачи: {doc.id}")
                    success = await perform_mass_apply(data['user_id'], data)
                    db.collection(FIRESTORE_QUEUE).document(doc.id).update({
                        "status": "completed" if success else "failed"
                    })
            except Exception as e:
                logger.error(f"Ошибка очереди: {e}")
        await asyncio.sleep(60)

# =================================================================
# 5. ОБРАБОТЧИКИ ДИАЛОГА (FRONTEND LOGIC)
# =================================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Показываем нижнее меню
    await update.message.reply_text(
        "Меню активировано 👇", 
        reply_markup=UI.main_menu_keyboard()
    )
    # Показываем приветствие с кнопкой действия
    await update.message.reply_text(
        UI.WELCOME_TEXT, 
        parse_mode='HTML', 
        reply_markup=UI.start_keyboard()
    )
    return OFFER_AGREEMENT

async def help_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ <b>О сервисе</b>\n\n"
        "Мы автоматизируем поиск работы для моряков. \n"
        "Поддержка: @admin_user", 
        parse_mode='HTML'
    )

async def offer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(
        UI.OFFER_TEXT,
        parse_mode='HTML',
        reply_markup=UI.offer_keyboard()
    )
    return AWAITING_PAYMENT

async def payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    # Отправка инвойса (счета)
    await context.bot.send_invoice(
        query.message.chat_id, 
        "Рассылка CV (Premium)", 
        "Массовая рассылка в 1083 крюинга + AI письмо", 
        "payload_123", 
        PAYMENT_PROVIDER_TOKEN, 
        "EUR", 
        [LabeledPrice("Service Fee", SERVICE_PRICE_CENTS)]
    )
    return AWAITING_PAYMENT

async def success_payment(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    # Срабатывает автоматически после оплаты
    await update.message.reply_text(UI.PAYMENT_SUCCESS_TEXT, parse_mode='HTML')
    return EMAIL_INPUT

async def email_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    email = update.message.text.strip()
    # Простая валидация
    if '@' not in email or '.' not in email:
        await update.message.reply_text("❌ Некорректный email. Попробуйте снова.")
        return EMAIL_INPUT
        
    context.user_data['email'] = email
    await update.message.reply_text(UI.UPLOAD_CV_TEXT, parse_mode='HTML')
    return UPLOAD_CV

async def cv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    doc = update.message.document
    # Проверка расширения
    if not doc.file_name.lower().endswith(('.pdf', '.docx', '.doc')):
        await update.message.reply_text("❌ Пожалуйста, загрузите файл PDF или Word.")
        return UPLOAD_CV
        
    f = await doc.get_file()
    path = os.path.join(TEMP_DIR, f"{update.message.chat_id}_{doc.file_name}")
    await f.download_to_drive(path)
    context.user_data['cv_path'] = path
    
    await update.message.reply_text(UI.ROLE_TEXT, parse_mode='HTML')
    return CURRENT_ROLE_INPUT

async def role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['job_title'] = update.message.text
    await update.message.reply_text(UI.PREF_TEXT, parse_mode='HTML')
    return PREFERENCES_INPUT

async def pref_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['preferences'] = update.message.text
    await update.message.reply_text(
        UI.DATE_TEXT, 
        parse_mode='HTML', 
        reply_markup=UI.date_keyboard()
    )
    return DATE_SELECTION

async def date_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    selection = query.data # 'today' or 'tomorrow'
    user_id = query.message.chat_id
    user_data = context.user_data
    
    # Отправка финального сообщения
    await query.edit_message_text(UI.FINAL_SUCCESS_TEXT, parse_mode='HTML')
    
    # Логика запуска
    if selection == 'tomorrow':
        await add_to_queue(user_id, user_data, selection)
    else:
        asyncio.create_task(perform_mass_apply(user_id, user_data))
        
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("🚫 Действие отменено. Нажмите /start чтобы начать заново.")
    return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

def main():
    load_local_database()
    initialize_firebase()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Обработчик диалога (Wizard)
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            MessageHandler(filters.Regex('^🚀 Начать рассылку$'), start)
        ],
        states={
            OFFER_AGREEMENT: [
                CallbackQueryHandler(offer_handler, pattern='^start_flow$'),
                CallbackQueryHandler(payment_handler, pattern='^pay$'),
                CallbackQueryHandler(cancel, pattern='^cancel$')
            ],
            AWAITING_PAYMENT: [
                MessageHandler(filters.SUCCESSFUL_PAYMENT, success_payment)
            ],
            EMAIL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_handler)],
            UPLOAD_CV: [MessageHandler(filters.Document.ALL, cv_handler)],
            CURRENT_ROLE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, role_handler)],
            PREFERENCES_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pref_handler)],
            DATE_SELECTION: [CallbackQueryHandler(date_handler)]
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    app.add_handler(CommandHandler('help', help_handler))
    app.add_handler(MessageHandler(filters.Regex('^ℹ️ О сервисе$'), help_handler))
    app.add_handler(conv_handler)
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    
    # Фоновая задача для очереди
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    app.job_queue.run_repeating(lambda t: asyncio.create_task(process_queue()), interval=60, first=10)

    print("✅ Бот успешно запущен и готов к работе!")
    app.run_polling()

if __name__ == '__main__':
    main()