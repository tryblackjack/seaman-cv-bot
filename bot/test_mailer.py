# -*- coding: utf-8 -*-
"""
Тестовый режим рассылки БЕЗ отправки писем
Показывает как работает AI генерация и фильтрация
"""

import logging
import asyncio
from bot.ai_hybrid_letter import generate_hybrid_letter
from bot.database_manager import DatabaseManager

logger = logging.getLogger(__name__)

async def test_campaign(message, context, cv_data, cv_file_path, db_manager):
    """
    Тестовая рассылка:
    1. Фильтрует компании (исключает текущий крюинг)
    2. Генерирует письма для первых 10 компаний
    3. Показывает результат БЕЗ отправки

    Args:
        message: Telegram message object
        context: Telegram context
        cv_data: данные из CV (dict)
        cv_file_path: путь к файлу CV
        db_manager: DatabaseManager instance
    """
    # Получаем все компании из базы
    all_companies = db_manager.get_all()

    # Фильтрация: исключаем текущий крюинг
    current_company = cv_data.get('current_company', '').lower()

    # Создаём список email'ов (исключая текущую компанию)
    filtered_emails = []
    for email, vessel_types in all_companies.items():
        # Простая проверка - если имя компании не содержится в email
        if not current_company or current_company not in email.lower():
            filtered_emails.append(email)

    total_companies = len(filtered_emails)

    await message.reply_text(
        f"🎯 **Тестовый режим рассылки**\n\n"
        f"📊 Всего компаний в базе: {len(all_companies)}\n"
        f"✅ После фильтрации: {total_companies}\n"
        f"❌ Исключён текущий крюинг: {cv_data.get('current_company', 'N/A')}\n\n"
        f"Генерирую письма для первых 10 компаний...",
        parse_mode='Markdown'
    )

    # Генерируем письма для первых 10 компаний
    sample_size = min(10, total_companies)

    for i, email in enumerate(filtered_emails[:sample_size]):
        # Создаём имя компании из email (для примера)
        company_name = email.split('@')[1].split('.')[0].title() + " Crewing"

        # Генерируем письмо
        letter = generate_hybrid_letter(cv_data, company_name)

        ai_badge = "🤖" if letter['used_ai'] else "📝"

        # Показываем результат
        message_text = (
            f"{ai_badge} **{i+1}/{sample_size}** {company_name}\n"
            f"📧 {email}\n\n"
            f"**Тема:** {letter['subject']}\n\n"
            f"**Текст:**\n{letter['body'][:200]}...\n\n"
            f"---\n"
            f"⚠️ Письмо НЕ отправлено (тестовый режим)"
        )

        await message.reply_text(message_text, parse_mode='Markdown')

        # Задержка для читаемости
        await asyncio.sleep(1)

    # Финальный отчёт
    await message.reply_text(
        f"✅ **Тестовая рассылка завершена!**\n\n"
        f"📊 Результаты:\n"
        f"• Компаний обработано: {sample_size}\n"
        f"• AI генерация: активна\n"
        f"• Письма: готовы\n\n"
        f"⚠️ В продакшн режиме будет отправлено в {total_companies} компаний\n\n"
        f"💡 Для реальной отправки нужен Gmail OAuth2",
        parse_mode='Markdown'
    )
