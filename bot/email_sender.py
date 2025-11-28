# -*- coding: utf-8 -*-
"""
Модуль для отправки email через SMTP или SendGrid
"""
import os
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from typing import Optional

logger = logging.getLogger(__name__)

try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail, Email, To, Content, Attachment, FileContent, FileName, FileType, Disposition
    import base64
    SENDGRID_AVAILABLE = True
except ImportError:
    SENDGRID_AVAILABLE = False
    logger.info("SendGrid не установлен, используется SMTP")


class EmailSender:
    """Класс для отправки email через SMTP или SendGrid"""

    def __init__(
        self,
        use_gmail: bool = True,
        gmail_address: Optional[str] = None,
        gmail_app_password: Optional[str] = None,
        smtp_server: Optional[str] = None,
        smtp_port: int = 465,
        smtp_username: Optional[str] = None,
        smtp_password: Optional[str] = None,
        sendgrid_api_key: Optional[str] = None
    ):
        """
        Args:
            use_gmail: Использовать Gmail SMTP
            gmail_address: Gmail адрес
            gmail_app_password: App Password для Gmail
            smtp_server: SMTP сервер (если не Gmail)
            smtp_port: SMTP порт
            smtp_username: SMTP username
            smtp_password: SMTP password
            sendgrid_api_key: API ключ SendGrid (опционально)
        """
        self.use_gmail = use_gmail
        self.gmail_address = gmail_address
        self.gmail_app_password = gmail_app_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.sendgrid_api_key = sendgrid_api_key

        # Проверка SendGrid
        if sendgrid_api_key and not SENDGRID_AVAILABLE:
            logger.warning("⚠️ SendGrid API ключ указан, но библиотека не установлена")

    def send_smtp(
        self,
        target_email: str,
        subject: str,
        body: str,
        cv_path: Optional[str] = None,
        reply_to: Optional[str] = None
    ) -> bool:
        """
        Отправка email через SMTP

        Args:
            target_email: Email получателя
            subject: Тема письма
            body: Текст письма
            cv_path: Путь к CV файлу (опционально)
            reply_to: Reply-To адрес

        Returns:
            True если успешно отправлено
        """
        try:
            logger.info(f"📧 Начинаю отправку письма на {target_email}")
            logger.info(f"📧 Тема: {subject}")
            logger.info(f"📧 Reply-To: {reply_to}")
            logger.info(f"📧 CV файл: {cv_path if cv_path else 'Нет'}")
            msg = MIMEMultipart()

            # Настройка отправителя
            if self.use_gmail:
                if not self.gmail_address or not self.gmail_app_password:
                    logger.error("❌ GMAIL_ADDRESS или GMAIL_APP_PASSWORD не настроены!")
                    return False

                msg['From'] = self.gmail_address
                if reply_to:
                    msg['Reply-To'] = reply_to
                smtp_server = "smtp.gmail.com"
                smtp_port = 587
                smtp_user = self.gmail_address
                smtp_pass = self.gmail_app_password
                logger.info(f"📧 Используем Gmail SMTP: {smtp_server}:{smtp_port}")
                logger.info(f"📧 Gmail адрес: {self.gmail_address}")
            else:
                msg['From'] = self.smtp_username
                if reply_to:
                    msg['Reply-To'] = reply_to
                smtp_server = self.smtp_server
                smtp_port = self.smtp_port
                smtp_user = self.smtp_username
                smtp_pass = self.smtp_password

            msg['To'] = target_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body, 'plain'))

            # Прикрепление CV
            if cv_path and os.path.exists(cv_path):
                with open(cv_path, "rb") as f:
                    attach = MIMEApplication(f.read(), _subtype="pdf")
                    attach.add_header(
                        'Content-Disposition',
                        'attachment',
                        filename=os.path.basename(cv_path)
                    )
                    msg.attach(attach)

            # Отправка
            logger.info(f"📧 Подключаемся к SMTP серверу {smtp_server}:{smtp_port}")
            if self.use_gmail:
                server = smtplib.SMTP(smtp_server, smtp_port)
                server.starttls()
                logger.info("📧 STARTTLS успешно")
            else:
                server = smtplib.SMTP_SSL(smtp_server, smtp_port)
                logger.info("📧 SSL подключение успешно")

            logger.info("📧 Выполняем login...")
            server.login(smtp_user, smtp_pass)
            logger.info("📧 Login успешен")

            logger.info("📧 Отправляем сообщение...")
            server.send_message(msg)
            logger.info("📧 Сообщение отправлено")

            server.quit()
            logger.info(f"✅ Email отправлен на {target_email}")
            return True

        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"❌ Ошибка аутентификации SMTP: {e}")
            logger.error("Проверьте GMAIL_ADDRESS и GMAIL_APP_PASSWORD в .env файле!")
            return False
        except smtplib.SMTPException as e:
            logger.error(f"❌ SMTP ошибка при отправке на {target_email}: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Общая ошибка отправки на {target_email}: {e}")
            logger.exception("Детали ошибки:")
            return False

    def send_sendgrid(
        self,
        target_email: str,
        subject: str,
        body: str,
        cv_path: Optional[str] = None,
        reply_to: Optional[str] = None,
        from_email: Optional[str] = None
    ) -> bool:
        """
        Отправка email через SendGrid API

        Args:
            target_email: Email получателя
            subject: Тема письма
            body: Текст письма
            cv_path: Путь к CV файлу (опционально)
            reply_to: Reply-To адрес
            from_email: Email отправителя

        Returns:
            True если успешно отправлено
        """
        if not SENDGRID_AVAILABLE:
            logger.error("❌ SendGrid не установлен")
            return False

        if not self.sendgrid_api_key:
            logger.error("❌ SendGrid API ключ не указан")
            return False

        try:
            message = Mail(
                from_email=from_email or self.gmail_address,
                to_emails=target_email,
                subject=subject,
                plain_text_content=body
            )

            if reply_to:
                message.reply_to = Email(reply_to)

            # Прикрепление CV
            if cv_path and os.path.exists(cv_path):
                with open(cv_path, 'rb') as f:
                    file_data = f.read()
                    encoded = base64.b64encode(file_data).decode()

                attachment = Attachment(
                    FileContent(encoded),
                    FileName(os.path.basename(cv_path)),
                    FileType('application/pdf'),
                    Disposition('attachment')
                )
                message.attachment = attachment

            sg = SendGridAPIClient(self.sendgrid_api_key)
            response = sg.send(message)

            if response.status_code in [200, 202]:
                logger.info(f"✅ Email отправлен через SendGrid на {target_email}")
                return True
            else:
                logger.error(f"❌ SendGrid ошибка: {response.status_code}")
                return False

        except Exception as e:
            logger.error(f"❌ Ошибка SendGrid для {target_email}: {e}")
            return False

    def send(
        self,
        target_email: str,
        subject: str,
        body: str,
        cv_path: Optional[str] = None,
        reply_to: Optional[str] = None,
        use_sendgrid: bool = False
    ) -> bool:
        """
        Отправка email (автоматический выбор метода)

        Args:
            target_email: Email получателя
            subject: Тема письма
            body: Текст письма
            cv_path: Путь к CV файлу (опционально)
            reply_to: Reply-To адрес
            use_sendgrid: Принудительно использовать SendGrid

        Returns:
            True если успешно отправлено
        """
        if use_sendgrid and self.sendgrid_api_key and SENDGRID_AVAILABLE:
            return self.send_sendgrid(
                target_email,
                subject,
                body,
                cv_path,
                reply_to
            )
        else:
            return self.send_smtp(
                target_email,
                subject,
                body,
                cv_path,
                reply_to
            )
