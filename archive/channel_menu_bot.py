# -*- coding: utf-8 -*-
import json
import re
import os
import asyncio
import logging
import sys
from datetime import datetime

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
import aiohttp
from dotenv import load_dotenv

load_dotenv()

# =================================================================
# КОНФИГУРАЦИЯ
# =================================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8499683122:AAEDPGuQLF2tXd_Cn4LXPXgaRf7mzXoa03o")
PAYMENT_PROVIDER_TOKEN = os.getenv("PAYMENT_PROVIDER_TOKEN", "1661751239:TEST:g7PE-C0FV-YcY1-ZgO7")
CHANNEL_USERNAME = "@Only_Offshore_test"

# OLLAMA (исправлен порт на 11435)
OLLAMA_API_URL = "http://localhost:11435/api/generate"
MODEL_NAME = "llama3"

LOCAL_DB_FILE = "recruiter_vessel_map.json"
TEMP_DIR = "temp_cvs"
LOG_DIR = "logs"

for directory in [TEMP_DIR, LOG_DIR]:
    os.makedirs(directory, exist_ok=True)

# =================================================================
# ЛОГИРОВАНИЕ
# =================================================================

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, f"bot_{datetime.now().strftime('%Y%m%d')}.log"), encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# =================================================================
# ПОСТОЯННОЕ МЕНЮ
# =================================================================

def get_main_menu_keyboard():
    """Постоянное меню внизу экрана в личке с ботом."""
    return ReplyKeyboardMarkup([
        [KeyboardButton("🚀 Разослать CV"), KeyboardButton("💼 Вакансии")],
        [KeyboardButton("📝 Мое резюме"), KeyboardButton("💰 Тарифы")],
        [KeyboardButton("ℹ️ Помощь"), KeyboardButton("📞 Поддержка")]
    ], resize_keyboard=True)

# =================================================================
# БАЗА ДАННЫХ
# =================================================================

recruiter_db_cache = {}

def load_local_database():
    global recruiter_db_cache
    try:
        if os.path.exists(LOCAL_DB_FILE):
            with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
                recruiter_db_cache = json.load(f)
            logger.info(f"✅ База загружена: {len(recruiter_db_cache)} контактов")
        else:
            recruiter_db_cache = {
                "test1@shipping.com": ["TANKER", "BULK"],
                "test2@maritime.com": ["CONTAINER"],
                "test3@offshore.com": ["OFFSHORE", "DP"]
            }
            logger.warning("⚠️ Используется тестовая база")
    except Exception as e:
        logger.error(f"❌ Ошибка загрузки базы: {e}")

# =================================================================
# AI ГЕНЕРАЦИЯ
# =================================================================

async def generate_cover_letter_ollama(job_title: str, preferences: str, company: str) -> str:
    """Генерация письма через Ollama."""
    prompt = f"""Write a short (60 words) professional maritime cover letter for {job_title} position at {company}. 
Vessel preference: {preferences or 'Any type'}. 
Mention immediate availability. 
Sign as 'Candidate'. 
Output ONLY the letter body, no subject."""
    
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_predict": 150}
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(OLLAMA_API_URL, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get('response', '').strip()
    except Exception as e:
        logger.error(f"❌ Ollama error: {e}")
    
    return f"Dear Sir/Madam,\n\nI am interested in {job_title} position. CV attached.\n\nBest regards,\nCandidate"

# =================================================================
# РАССЫЛКА
# =================================================================

async def perform_mass_apply(user_id: int, user_data: dict, context: ContextTypes.DEFAULT_TYPE):
    """Симуляция рассылки."""
    await context.bot.send_message(user_id, "⚙️ Начинаю обработку...")
    
    targets = []
    pref = user_data.get('preferences', '').upper()
    
    for email, categories in recruiter_db_cache.items():
        if not pref or any(p.strip() in str(categories).upper() for p in pref.split(',')):
            targets.append(email)
    
    test_targets = targets[:3]
    await context.bot.send_message(user_id, f"🎯 Найдено {len(targets)} компаний. Тест: {len(test_targets)}")

    for email in test_targets:
        body = await generate_cover_letter_ollama(
            user_data['job_title'], 
            user_data['preferences'], 
            email.split('@')[1]
        )
        
        await context.bot.send_message(
            user_id, 
            f"📤 <b>{email}</b>\n\n📝 <pre>{body}</pre>",
            parse_mode='HTML'
        )
        await asyncio.sleep(2)

    await context.bot.send_message(user_id, "✅ <b>Тест завершен!</b>", parse_mode='HTML')

# =================================================================
# HANDLERS
# =================================================================

(AWAITING_PAYMENT, EMAIL_INPUT, UPLOAD_CV, ROLE_INPUT, PREF_INPUT, DATE_INPUT) = range(6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обработка /start с параметрами."""
    args = context.args
    
    if args and len(args) > 0:
        action = args[0]
        
        if action == "apply":
            text = "🚀 <b>Рассылка CV</b>\n\nЯ отправлю ваше резюме в 1583 крюинга!"
        elif action == "vacancies":
            text = f"💼 <b>Актуальные вакансии</b>\n\nСмотрите свежие вакансии в нашем канале:\n{CHANNEL_USERNAME}"
        elif action == "help":
            text = "ℹ️ <b>Справка</b>\n\n/start - Главное меню\n/apply - Начать рассылку\n/ollama - Проверить AI"
        else:
            text = "👋 Добро пожаловать!"
    else:
        text = (
            "👋 <b>Привет!</b>\n\n"
            "Я помогу разослать ваше CV в крюинговые компании.\n\n"
            "📊 <b>База:</b> 1583 компании\n"
            "🤖 <b>AI:</b> Персональные cover letters\n"
            "💰 <b>Цена:</b> 50 EUR (тестовый режим)\n\n"
            "Выберите действие из меню ниже:"
        )
    
    await update.message.reply_text(
        text,
        parse_mode='HTML',
        reply_markup=get_main_menu_keyboard()
    )
    return ConversationHandler.END

async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработка кнопок постоянного меню."""
    text = update.message.text
    
    if text == "🚀 Разослать CV":
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("💳 Оплатить 50€ (TEST)", callback_data='start_payment')
        ]])
        await update.message.reply_text(
            "🚀 <b>Начинаем рассылку!</b>\n\n"
            "💰 Стоимость: 50 EUR (тестовый режим)\n"
            "📊 База: 1583 компании\n"
            "🤖 AI cover letter включен\n\n"
            "Нажмите кнопку для оплаты:",
            parse_mode='HTML',
            reply_markup=keyboard
        )
    
    elif text == "💼 Вакансии":
        await update.message.reply_text(
            f"💼 <b>Актуальные вакансии</b>\n\n"
            f"Смотрите свежие вакансии для моряков в нашем канале:\n{CHANNEL_USERNAME}\n\n"
            f"Подписывайтесь чтобы не пропустить новые предложения!",
            parse_mode='HTML'
        )
    
    elif text == "📝 Мое резюме":
        await update.message.reply_text(
            "📝 <b>Управление резюме</b>\n\n"
            "Функция в разработке...\n"
            "Скоро вы сможете:\n"
            "• Просмотреть статус рассылки\n"
            "• Обновить CV\n"
            "• Посмотреть историю откликов",
            parse_mode='HTML'
        )
    
    elif text == "💰 Тарифы":
        await update.message.reply_text(
            "💰 <b>Тарифы на услуги</b>\n\n"
            "🚀 <b>Разовая рассылка:</b> 50 EUR\n"
            "   • 1583 крюинговые компании\n"
            "   • AI генерация cover letter\n"
            "   • Фильтрация по типу судна\n"
            "   • Отчет на email\n\n"
            "📧 <b>Что входит:</b>\n"
            "   ✅ Персональное сопроводительное письмо\n"
            "   ✅ Рассылка в течение 24 часов\n"
            "   ✅ Полный отчет о рассылке\n"
            "   ✅ Техническая поддержка",
            parse_mode='HTML'
        )
    
    elif text == "ℹ️ Помощь":
        await update.message.reply_text(
            "ℹ️ <b>Справка по боту</b>\n\n"
            "<b>Команды:</b>\n"
            "/start - Главное меню\n"
            "/ollama - Проверить AI сервер\n"
            "/publish_menu - Опубликовать меню в канале\n\n"
            "<b>Как пользоваться:</b>\n"
            "1. Нажмите '🚀 Разослать CV'\n"
            "2. Оплатите услугу (TEST режим)\n"
            "3. Загрузите ваше резюме\n"
            "4. Укажите должность и предпочтения\n"
            "5. Получите отчет на email\n\n"
            "<b>Тестовый режим:</b>\n"
            "Используйте тестовую карту Telegram для оплаты.",
            parse_mode='HTML'
        )
    
    elif text == "📞 Поддержка":
        await update.message.reply_text(
            "📞 <b>Техническая поддержка</b>\n\n"
            "По всем вопросам обращайтесь:\n"
            "📧 Email: support@seafarer-jobs.com\n"
            "💬 Telegram: @your_support\n\n"
            "⏰ Время работы: 24/7\n"
            "⚡ Обычно отвечаем в течение 1 часа",
            parse_mode='HTML'
        )

async def start_payment_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Запуск оплаты."""
    query = update.callback_query
    await query.answer()
    
    await context.bot.send_invoice(
        query.message.chat_id,
        title="Рассылка CV в крюинги",
        description="Отправка резюме в 1583 крюинга + AI cover letter",
        payload="test_cv_service",
        provider_token=PAYMENT_PROVIDER_TOKEN,
        currency="EUR",
        prices=[LabeledPrice("Услуга рассылки", 5000)]
    )

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """После успешной оплаты."""
    await update.message.reply_text(
        "🎉 <b>Оплата прошла!</b>\n\n📧 Введите ваш Email:",
        parse_mode='HTML'
    )
    return EMAIL_INPUT

async def email_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение email."""
    email = update.message.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await update.message.reply_text("❌ Некорректный email. Попробуйте снова:")
        return EMAIL_INPUT
    
    context.user_data['email'] = email
    await update.message.reply_text("📂 Загрузите ваш CV (PDF/DOCX):")
    return UPLOAD_CV

async def cv_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Загрузка CV."""
    doc = update.message.document
    if not doc:
        await update.message.reply_text("⚠️ Отправьте файл.")
        return UPLOAD_CV
    
    f = await doc.get_file()
    path = os.path.join(TEMP_DIR, f"{update.message.chat_id}_{doc.file_name}")
    await f.download_to_drive(path)
    context.user_data['cv_path'] = path
    
    await update.message.reply_text("⚓ Ваша должность? (Например: Chief Officer)")
    return ROLE_INPUT

async def role_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение должности."""
    context.user_data['job_title'] = update.message.text
    await update.message.reply_text("🚢 Тип судна? (Tanker, Container или 'Нет')")
    return PREF_INPUT

async def pref_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сохранение предпочтений."""
    text = update.message.text.strip()
    context.user_data['preferences'] = "" if text.lower() in ['нет', 'no'] else text
    
    await update.message.reply_text("🚀 Запускаю рассылку...")
    asyncio.create_task(perform_mass_apply(update.message.from_user.id, context.user_data, context))
    return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Подтверждение оплаты."""
    await update.pre_checkout_query.answer(ok=True)

async def check_ollama(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Проверка Ollama."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:11435/api/tags", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    models = [m['name'] for m in data.get('models', [])]
                    await update.message.reply_text(
                        f"✅ <b>Ollama работает!</b>\n\n"
                        f"Установленные модели:\n{', '.join(models) if models else 'Нет моделей'}",
                        parse_mode='HTML'
                    )
                else:
                    await update.message.reply_text(f"⚠️ Ollama код: {resp.status}")
    except Exception as e:
        await update.message.reply_text(
            f"❌ <b>Ollama недоступна:</b> {e}\n\n"
            f"<b>Проверьте:</b>\n"
            f"1. Запущен ли <code>ollama serve</code>\n"
            f"2. Порт 11435 открыт\n"
            f"3. Модель установлена: <code>ollama pull llama3</code>",
            parse_mode='HTML'
        )

async def publish_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Публикует меню в канал."""
    menu_text = (
        "📌 <b>МЕНЮ СЕРВИСА</b>\n\n"
        "🌊 Автоматическая рассылка CV для моряков\n"
        "📊 База: 1583 крюинговых компании\n"
        "🤖 AI генерация cover letter\n"
        "💰 Цена: 50 EUR\n\n"
        "👇 Выберите действие:"
    )
    
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🚀 Разослать CV", url="https://t.me/OnlyOffshore_bot?start=apply"),
            InlineKeyboardButton("💼 Вакансии", url="https://t.me/OnlyOffshore_bot?start=vacancies")
        ],
        [
            InlineKeyboardButton("📝 Мое резюме", url="https://t.me/OnlyOffshore_bot?start=my_cv"),
            InlineKeyboardButton("💰 Тарифы", url="https://t.me/OnlyOffshore_bot?start=pricing")
        ],
        [
            InlineKeyboardButton("ℹ️ Помощь", url="https://t.me/OnlyOffshore_bot?start=help"),
            InlineKeyboardButton("📞 Поддержка", url="https://t.me/OnlyOffshore_bot?start=support")
        ]
    ])
    
    try:
        msg = await context.bot.send_message(
            chat_id=CHANNEL_USERNAME,
            text=menu_text,
            parse_mode='HTML',
            reply_markup=keyboard
        )
        # Закрепляем пост
        await context.bot.pin_chat_message(
            chat_id=CHANNEL_USERNAME,
            message_id=msg.message_id,
            disable_notification=True
        )
        await update.message.reply_text("✅ Меню опубликовано и закреплено в канале!")
        logger.info("✅ Меню опубликовано в канале")
    except Exception as e:
        error_msg = str(e)
        if "CHAT_ADMIN_REQUIRED" in error_msg:
            await update.message.reply_text(
                "❌ <b>Ошибка:</b> Бот не является администратором канала.\n\n"
                f"<b>Как исправить:</b>\n"
                f"1. Откройте канал {CHANNEL_USERNAME}\n"
                f"2. Настройки → Администраторы\n"
                f"3. Добавьте бота как администратора\n"
                f"4. Дайте права: публиковать и закреплять сообщения",
                parse_mode='HTML'
            )
        else:
            await update.message.reply_text(f"❌ Ошибка: {error_msg}")
        logger.error(f"❌ Ошибка публикации в канал: {e}")

# =================================================================
# MAIN
# =================================================================

def main():
    print("=" * 60)
    print("🌊 SEAFARER CV BOT - LOCAL TEST")
    print("=" * 60)
    
    load_local_database()
    
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    
    # Conversation для рассылки
    conv = ConversationHandler(
        entry_points=[
            CommandHandler('start', start),
            CallbackQueryHandler(start_payment_handler, pattern='^start_payment$')
        ],
        states={
            AWAITING_PAYMENT: [MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment)],
            EMAIL_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, email_handler)],
            UPLOAD_CV: [MessageHandler(filters.Document.ALL, cv_handler)],
            ROLE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, role_handler)],
            PREF_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, pref_handler)]
        },
        fallbacks=[CommandHandler('cancel', start)],
        per_message=False
    )
    
    app.add_handler(conv)
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(CommandHandler('ollama', check_ollama))
    app.add_handler(CommandHandler('publish_menu', publish_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu_buttons))
    
    print(f"✅ База: {len(recruiter_db_cache)} контактов")
    print(f"✅ Канал: {CHANNEL_USERNAME}")
    print(f"✅ Ollama: {OLLAMA_API_URL}")
    print("\n🚀 Бот запущен!")
    print("📝 Команды:")
    print("   /start - Главное меню")
    print("   /publish_menu - Опубликовать меню в канале")
    print("   /ollama - Проверить AI\n")
    
    app.run_polling()

if __name__ == '__main__':
    main()
