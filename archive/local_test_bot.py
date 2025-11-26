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
    logger.warning("⚠️ SendGrid не установлен. Установите: pip install sendgrid")

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

# 🔥 НОВОЕ: Используем Gmail SMTP напрямую (корпоративная почта Google)
USE_GMAIL = True  # Включить Gmail вместо SendPulse
GMAIL_ADDRESS = "info@your-company.com"  # Ваша корпоративная почта
GMAIL_APP_PASSWORD = "your-app-password"  # Пароль приложения из Google

# Старые настройки SendPulse (можно удалить)
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

# 🔥 УЛУЧШЕННОЕ ЛОГИРОВАНИЕ
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),  # Логи в файл
        logging.StreamHandler()  # И в консоль
    ]
)
logger = logging.getLogger(__name__)

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
# 🔥 ИСПРАВЛЕННАЯ ОТПРАВКА EMAIL (С GMAIL)
# =================================================================

def send_email_sync(target_email, subject, body, cv_path, user_reply_to):
    """
    Отправка через Gmail SMTP или SendPulse.
    Reply-To теперь правильно настроен!
    """
    try:
        msg = MIMEMultipart()
        
        if USE_GMAIL:
            # 🔥 GMAIL: От имени корпоративной почты, но ответы идут моряку
            msg['From'] = GMAIL_ADDRESS
            msg['Reply-To'] = user_reply_to  # Ответы крюингов придут сюда
            smtp_server = "smtp.gmail.com"
            smtp_port = 587
            smtp_user = GMAIL_ADDRESS
            smtp_pass = GMAIL_APP_PASSWORD
        else:
            # SendPulse (если используется)
            msg['From'] = SMTP_USERNAME
            msg['Reply-To'] = user_reply_to
            smtp_server = SMTP_SERVER
            smtp_port = SMTP_PORT
            smtp_user = SMTP_USERNAME
            smtp_pass = SMTP_PASSWORD
        
        msg['To'] = target_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        # Прикрепляем CV
        if cv_path and os.path.exists(cv_path):
            with open(cv_path, "rb") as f:
                attach = MIMEApplication(f.read(), _subtype="pdf")
                attach.add_header('Content-Disposition', 'attachment', filename="CV.pdf")
                msg.attach(attach)
        
        # 🔥 ОТПРАВКА
        try:
            if USE_GMAIL:
                # Gmail использует STARTTLS (порт 587)
                with smtplib.SMTP(smtp_server, smtp_port, timeout=10) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                    logger.info(f"✅ [GMAIL] Письмо отправлено на {target_email} (Reply-To: {user_reply_to})")
            else:
                # SendPulse использует SSL (порт 465)
                with smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10) as server:
                    server.login(smtp_user, smtp_pass)
                    server.send_message(msg)
                    logger.info(f"✅ [SMTP] Письмо отправлено на {target_email}")
            
            return True
            
        except Exception as smtp_error:
            logger.error(f"❌ SMTP Ошибка: {smtp_error}")
            # В тестовом режиме симулируем успех
            if TEST_MODE:
                logger.info(f"📨 [СИМУЛЯЦИЯ] Письмо на {target_email} (Reply-To: {user_reply_to})")
                return True
            return False
            
    except Exception as e:
        logger.error(f"Критическая ошибка сборки письма: {e}")
        return False

# =================================================================
# МАССОВАЯ РАССЫЛКА
# =================================================================

async def perform_mass_apply(user_id, context, user_data):
    logger.info(f"🚀 Начало рассылки для пользователя {user_id}")
    
    try:
        await context.bot.send_message(user_id, "⚙️ Анализирую CV и подбираю компании...")
        
        # 1. Извлекаем текст из CV
        cv_text = ""
        if user_data.get('cv_path'):
            cv_text = await asyncio.to_thread(extract_text_from_pdf, user_data['cv_path'])
            logger.info(f"📄 CV текст извлечен ({len(cv_text)} символов)")
        
        # 2. AI анализ
        email_body, exclude_company = await analyze_cv_and_preferences(
            cv_text, 
            user_data.get('preferences', '')
        )
        
        if exclude_company and exclude_company != "NONE":
            await context.bot.send_message(
                user_id, 
                f"🛡️ <b>AI Защита:</b> Текущий работодатель <b>{exclude_company}</b> исключен.",
                parse_mode='HTML'
            )
        
        # 3. Формируем список получателей
        targets = []
        
        if TEST_MODE:
            targets = [TEST_TARGET_EMAIL] * 3
            logger.info(f"🧪 ТЕСТОВЫЙ РЕЖИМ: 3 письма на {TEST_TARGET_EMAIL}")
        else:
            pref = user_data.get('preferences', '').upper()
            for email, tags in recruiter_db_cache.items():
                # Исключаем текущего работодателя
                if exclude_company != "NONE" and exclude_company.lower() in email.lower():
                    logger.info(f"⏭️ Пропуск {email} (текущий работодатель)")
                    continue
                
                # Фильтруем по типу судна
                if not pref or 'ANY' in pref or any(p.strip().upper() in str(tags).upper() for p in pref.split(',')):
                    targets.append(email)
        
        await context.bot.send_message(user_id, f"🎯 Готово к отправке: {len(targets)} компаний.")
        logger.info(f"📊 Целей для рассылки: {len(targets)}")
        
        # 4. Рассылка
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
                        f"📨 <b>Отправлено</b> ({i+1}/3) на {email}\n\n"
                        f"💬 <b>Текст:</b> {email_body[:80]}...\n"
                        f"📧 <b>Reply-To:</b> {user_data['email']}",
                        parse_mode='HTML'
                    )
            
            await asyncio.sleep(1)  # Задержка между письмами

        await context.bot.send_message(
            user_id, 
            f"🎉 <b>Рассылка завершена!</b>\nОтправлено писем: {sent_count}",
            parse_mode='HTML'
        )
        logger.info(f"✅ Рассылка завершена. Успешно: {sent_count}/{len(targets)}")
        
    except Exception as e:
        logger.error(f"❌ Ошибка в perform_mass_apply: {e}", exc_info=True)
        await context.bot.send_message(user_id, f"❌ Ошибка рассылки: {e}")

# =================================================================
# HANDLERS
# =================================================================

(OFFER, PAYMENT, EMAIL, UPLOAD, ROLE, PREF) = range(6)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"👤 /start от пользователя {update.message.chat_id}")
    await update.message.reply_text("👋 Привет! Я бот для рассылки CV. Нажмите /start_apply")

async def start_apply(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🚀 /start_apply от пользователя {update.message.chat_id}")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("💳 Оплатить (Тест)", callback_data='pay')],
        [InlineKeyboardButton("🔐 Админ доступ", callback_data='admin')]
    ])
    await update.message.reply_text("Оплата услуги: 50 EUR.", reply_markup=keyboard)
    return PAYMENT

async def pay_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"💳 Попытка оплаты от {query.message.chat_id}")
    
    try:
        await context.bot.send_invoice(
            query.message.chat_id, 
            "Рассылка CV", 
            "Test Service", 
            "payload", 
            PAYMENT_PROVIDER_TOKEN, 
            "EUR", 
            [LabeledPrice("Service", 5000)]
        )
        return PAYMENT
    except Exception as e:
        logger.warning(f"⚠️ Ошибка тестовой оплаты: {e}. Пропускаем шаг оплаты.")
        await query.message.reply_text("⚠️ Тестовый режим: оплата пропущена.")
        # 🔥 ИСПРАВЛЕНО: правильный переход к следующему шагу
        await query.message.reply_text("📧 Введите ваш **личный Email** (на него будут отвечать крюинги):", parse_mode='Markdown')
        return EMAIL

async def successful_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"✅ Успешная оплата от {update.message.chat_id}")
    # 🔥 ИСПРАВЛЕНО: используем update.message вместо callback_query
    await update.message.reply_text("📧 Введите ваш **личный Email** (на него будут отвечать крюинги):", parse_mode='Markdown')
    return EMAIL

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    logger.info(f"🔐 Запрос админ доступа от {query.message.chat_id}")
    await query.message.reply_text("Введите пароль:")
    return PAYMENT

async def check_passcode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == ADMIN_PASSPHRASE:
        logger.info(f"✅ Админ доступ предоставлен {update.message.chat_id}")
        await update.message.reply_text("✅ Пароль принят.")
        await update.message.reply_text("📧 Введите ваш **личный Email**:", parse_mode='Markdown')
        return EMAIL
    else:
        logger.warning(f"❌ Неверный пароль от {update.message.chat_id}")
        await update.message.reply_text("❌ Неверно.")
        return PAYMENT

async def save_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    email = update.message.text.strip()
    context.user_data['email'] = email
    logger.info(f"📧 Email сохранен: {email}")
    await update.message.reply_text("📂 Загрузите CV (PDF):")
    return UPLOAD

async def save_cv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith('.pdf'):
        await update.message.reply_text("❌ Только PDF файлы.")
        return UPLOAD
    
    logger.info(f"📄 Получен CV: {doc.file_name}")
    f = await doc.get_file()
    path = os.path.join(TEMP_DIR, f"{update.message.chat_id}_{doc.file_name}")
    await f.download_to_drive(path)
    context.user_data['cv_path'] = path
    logger.info(f"💾 CV сохранен: {path}")
    
    await update.message.reply_text("⚓ Ваша должность?")
    return ROLE

async def save_role(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = update.message.text.strip()
    context.user_data['job_title'] = role
    logger.info(f"⚓ Должность: {role}")
    await update.message.reply_text("🚢 Пожелания по судну (или 'Any')?")
    return PREF

async def save_pref(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pref = update.message.text.strip()
    context.user_data['preferences'] = pref
    logger.info(f"🚢 Предпочтения: {pref}")
    
    await update.message.reply_text("🚀 Запускаю процесс рассылки...")
    
    # 🔥 ИСПРАВЛЕНО: await вместо create_task для корректного логирования
    await perform_mass_apply(update.message.chat_id, context, context.user_data)
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"🛑 Отмена от {update.message.chat_id}")
    await update.message.reply_text("Отмена.")
    return ConversationHandler.END

async def precheckout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.pre_checkout_query.answer(ok=True)

# =================================================================
# MAIN
# =================================================================

def main():
    logger.info("=" * 50)
    logger.info("🤖 ЗАПУСК БОТА")
    logger.info("=" * 50)
    
    load_database()
    app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

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

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv)
    app.add_handler(PreCheckoutQueryHandler(precheckout))

    logger.info("✅ Бот запущен и готов к работе!")
    app.run_polling()

if __name__ == '__main__':
    main()
