# -*- coding: utf-8 -*-
"""
Модуль для отправки email через Gmail API с OAuth2 аутентификацией
"""
import os
import pickle
import logging
import base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_AVAILABLE = True
except ImportError:
    GOOGLE_API_AVAILABLE = False
    logger.warning("⚠️ Google API библиотеки не установлены. OAuth2 недоступен.")

# Gmail API scopes
SCOPES = ['https://www.googleapis.com/auth/gmail.send']


def get_gmail_service():
    """
    Получает Gmail API service с OAuth2 аутентификацией

    Returns:
        Gmail API service объект или None при ошибке
    """
    if not GOOGLE_API_AVAILABLE:
        logger.error("❌ Google API библиотеки не установлены")
        return None

    creds = None
    token_path = 'token.pickle'
    credentials_path = 'credentials.json'

    # Загружаем сохраненные credentials
    if os.path.exists(token_path):
        logger.info("📂 Загружаем сохраненный token.pickle")
        with open(token_path, 'rb') as token:
            creds = pickle.load(token)

    # Если нет валидных credentials, запрашиваем авторизацию
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            logger.info("🔄 Обновляем expired токен")
            creds.refresh(Request())
        else:
            if not os.path.exists(credentials_path):
                logger.error(f"❌ Файл {credentials_path} не найден!")
                logger.error("Скачайте credentials.json из Google Cloud Console")
                return None

            logger.info("🔑 Запускаем OAuth2 авторизацию")
            flow = InstalledAppFlow.from_client_secrets_file(
                credentials_path, SCOPES)
            creds = flow.run_local_server(port=0)

        # Сохраняем credentials для следующего использования
        logger.info("💾 Сохраняем credentials в token.pickle")
        with open(token_path, 'wb') as token:
            pickle.dump(creds, token)

    try:
        service = build('gmail', 'v1', credentials=creds)
        logger.info("✅ Gmail API service успешно инициализирован")
        return service
    except Exception as e:
        logger.error(f"❌ Ошибка создания Gmail service: {e}")
        return None


def create_message_with_attachment(
    sender: str,
    to: str,
    subject: str,
    body: str,
    reply_to_email: Optional[str] = None,
    cv_path: Optional[str] = None
) -> dict:
    """
    Создает email сообщение с вложением

    Args:
        sender: Email отправителя
        to: Email получателя
        subject: Тема письма
        body: Текст письма
        reply_to_email: Email для Reply-To header
        cv_path: Путь к CV файлу (опционально)

    Returns:
        Dict с закодированным сообщением для Gmail API
    """
    message = MIMEMultipart()
    message['From'] = sender
    message['To'] = to
    message['Subject'] = subject

    # КРИТИЧНО: Добавляем Reply-To header
    if reply_to_email:
        message['Reply-To'] = reply_to_email
        logger.info(f"📧 Reply-To установлен: {reply_to_email}")

    # Добавляем тело письма
    message.attach(MIMEText(body, 'plain', 'utf-8'))

    # Прикрепляем CV файл
    if cv_path and os.path.exists(cv_path):
        logger.info(f"📎 Прикрепляем файл: {cv_path}")
        with open(cv_path, 'rb') as f:
            attach = MIMEApplication(f.read(), _subtype='pdf')
            attach.add_header(
                'Content-Disposition',
                'attachment',
                filename=os.path.basename(cv_path)
            )
            message.attach(attach)

    # Кодируем сообщение в base64
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
    return {'raw': raw_message}


def send_email_oauth(
    target_email: str,
    subject: str,
    body: str,
    sender_email: str = 'office@onlyoffshore.biz',
    reply_to_email: Optional[str] = None,
    cv_path: Optional[str] = None
) -> bool:
    """
    Отправляет email через Gmail API с OAuth2

    Args:
        target_email: Email получателя (крюинг)
        subject: Тема письма
        body: Текст письма
        sender_email: Email отправителя (по умолчанию office@onlyoffshore.biz)
        reply_to_email: Email соискателя для Reply-To
        cv_path: Путь к CV файлу

    Returns:
        True если отправка успешна
    """
    if not GOOGLE_API_AVAILABLE:
        logger.error("❌ Google API библиотеки не установлены")
        return False

    try:
        logger.info("=" * 60)
        logger.info("📧 ОТПРАВКА EMAIL ЧЕРЕЗ GMAIL API (OAuth2)")
        logger.info(f"📤 От: {sender_email}")
        logger.info(f"📥 Кому: {target_email}")
        logger.info(f"📝 Тема: {subject}")
        logger.info(f"↩️  Reply-To: {reply_to_email}")
        logger.info(f"📎 CV файл: {cv_path if cv_path else 'Нет'}")
        logger.info("=" * 60)

        # Получаем Gmail service
        service = get_gmail_service()
        if not service:
            logger.error("❌ Не удалось получить Gmail service")
            return False

        # Создаем сообщение
        message = create_message_with_attachment(
            sender=sender_email,
            to=target_email,
            subject=subject,
            body=body,
            reply_to_email=reply_to_email,
            cv_path=cv_path
        )

        # Отправляем
        logger.info("📤 Отправляем сообщение через Gmail API...")
        result = service.users().messages().send(
            userId='me',
            body=message
        ).execute()

        logger.info(f"✅ Email успешно отправлен! Message ID: {result['id']}")
        logger.info("=" * 60)
        return True

    except HttpError as error:
        logger.error(f"❌ Gmail API HTTP ошибка: {error}")
        logger.error(f"Детали: {error.error_details if hasattr(error, 'error_details') else 'N/A'}")
        return False
    except Exception as e:
        logger.error(f"❌ Ошибка отправки email через OAuth2: {e}")
        logger.exception("Детали ошибки:")
        return False
