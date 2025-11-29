# -*- coding: utf-8 -*-
"""
AI анализ CV через Google Gemini 1.5 Flash
Извлекает: ФИО, должности, крюинг, email, телефон
"""

import google.generativeai as genai
import os
import logging
import json

logger = logging.getLogger(__name__)

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None
    logger.warning("⚠️ pypdf не установлена, используем альтернативный метод")

def extract_text_from_pdf(pdf_path: str) -> str:
    """Извлекает текст из PDF"""
    if not PdfReader:
        logger.error("❌ pypdf не установлена")
        return ""

    try:
        reader = PdfReader(pdf_path)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        logger.info(f"✅ Извлечено {len(text)} символов из PDF")
        return text
    except Exception as e:
        logger.error(f"❌ Ошибка чтения PDF: {e}")
        return ""

def analyze_cv_with_ai(cv_path: str) -> dict:
    """
    Анализирует CV через Gemini 1.5 Flash

    Args:
        cv_path: путь к PDF файлу с CV

    Returns:
        {
            'full_name': str,
            'current_rank': str,
            'current_company': str,
            'desired_rank': str,
            'vessel_type': str,
            'experience_years': str,
            'email': str,
            'phone': str
        }
        или None в случае ошибки
    """
    # API key
    api_key = os.getenv('GOOGLE_AI_API_KEY')
    if not api_key:
        logger.error("❌ No GOOGLE_AI_API_KEY in .env")
        return None

    # Извлекаем текст из PDF
    cv_text = extract_text_from_pdf(cv_path)
    if not cv_text or len(cv_text) < 50:
        logger.error("❌ Не удалось извлечь текст из PDF или текст слишком короткий")
        return None

    # Обрезаем до 10000 символов (экономия токенов)
    cv_text = cv_text[:10000]

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""Extract information from this seafarer CV and return ONLY valid JSON.

Required fields:
- full_name: full name of the person
- current_rank: current position (e.g. "2nd Officer", "AB", "Chief Engineer")
- current_company: current or last employer/crewing company
- desired_rank: desired position (if not mentioned, same as current_rank)
- vessel_type: type of vessel experience (e.g. "tanker", "container", "bulk", "offshore")
- experience_years: total years of sea experience
- email: email address
- phone: phone number with country code

Return ONLY this JSON object, nothing else:
{{
  "full_name": "...",
  "current_rank": "...",
  "current_company": "...",
  "desired_rank": "...",
  "vessel_type": "...",
  "experience_years": "...",
  "email": "...",
  "phone": "..."
}}

CV text:
{cv_text}
"""

        logger.info("🤖 Отправка запроса в Gemini 1.5 Flash...")

        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.1,  # низкая для точности
                'max_output_tokens': 300
            }
        )

        # Парсим JSON из ответа
        response_text = response.text.strip()

        logger.info(f"📥 Получен ответ от AI: {response_text[:200]}...")

        # Убираем markdown если есть
        if response_text.startswith('```'):
            lines = response_text.split('\n')
            response_text = '\n'.join(lines[1:-1])  # убираем первую и последнюю строку
            if response_text.startswith('json'):
                response_text = response_text[4:].strip()

        cv_data = json.loads(response_text)

        logger.info(f"✅ CV проанализировано: {cv_data.get('full_name')}")
        logger.info(f"📋 Извлечённые данные: {json.dumps(cv_data, ensure_ascii=False, indent=2)}")

        return cv_data

    except json.JSONDecodeError as e:
        logger.error(f"❌ Ошибка парсинга JSON: {e}")
        logger.error(f"Response text: {response_text}")
        return None
    except Exception as e:
        logger.error(f"❌ Ошибка анализа CV: {e}", exc_info=True)
        return None
