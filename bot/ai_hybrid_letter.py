# -*- coding: utf-8 -*-
"""
AI-hybrid email generator
Экономный: 200-400 токенов на письмо
10 шаблонов + Gemini 1.5 Flash для "очеловечивания"
"""

import os
import random
import logging
import re

logger = logging.getLogger(__name__)

try:
    import google.generativeai as genai
except ImportError:
    genai = None
    logger.warning("⚠️ google-generativeai не установлен, используем только шаблоны")

# ============ 10 ШАБЛОНОВ ============

TEMPLATES = [
    # A - Классический
    {
        "subject": "Application for {desired_rank}",
        "body": """Dear Hiring Team,

My name is {full_name}. I am applying for the {desired_rank} position and have {experience_years} years of sea-going experience.
I can join immediately. All certificates are valid.

Please find my CV attached.

Regards,
{full_name}"""
    },

    # B - Короткий
    {
        "subject": "{desired_rank} - Available immediately",
        "body": """Dear Crew Department,

I would like to apply for the {desired_rank} position.
Experience: {experience_years} years
Fleet: {vessel_type}
Available: immediately

CV attached.

Best regards,
{full_name}"""
    },

    # C - Offshore
    {
        "subject": "Offshore {desired_rank} application",
        "body": """Dear Sir/Madam,

My name is {full_name}, and I am applying for the {desired_rank} position in your offshore fleet.
I have experience with {vessel_type} vessels. All documents are up to date.

Best regards,
{full_name}"""
    },

    # D - Tanker
    {
        "subject": "{desired_rank} application - Tanker fleet",
        "body": """Dear Recruiter,

Please consider my application for the {desired_rank} position in your tanker fleet.
I have {experience_years} years of experience and valid documents.

Thank you.
{full_name}"""
    },

    # E - Container/Bulk
    {
        "subject": "Application: {desired_rank}",
        "body": """Dear Hiring Manager,

My name is {full_name}. I am interested in the {desired_rank} position for {vessel_type} vessels.
My experience is {experience_years}+ years.

Kind regards,
{full_name}"""
    },

    # F - Very short
    {
        "subject": "{desired_rank} - {full_name}",
        "body": """Dear Crew Team,

Applying for: {desired_rank}
Experience: {experience_years} years
Available: immediately
CV attached

Regards, {full_name}"""
    },

    # G - Senior positions
    {
        "subject": "Senior {desired_rank} application",
        "body": """Dear Sir/Madam,

My name is {full_name}, and I am applying for the {desired_rank} position.
I have {experience_years} years at sea and leadership experience gained on {vessel_type} vessels.

Respectfully,
{full_name}"""
    },

    # H - Professional
    {
        "subject": "{full_name} - {desired_rank} position",
        "body": """Dear Hiring Team,

I am writing to express my interest in the {desired_rank} position.
With {experience_years} years of maritime experience, I am confident in my ability to contribute to your operations.

Please find my CV attached for your consideration.

Best regards,
{full_name}"""
    },

    # I - Junior/Cadet
    {
        "subject": "{desired_rank} - Ready to join",
        "body": """Dear Crew Department,

My name is {full_name}. I am applying for a {desired_rank} position.
I have valid certificates and am ready to join immediately.

Thank you for your consideration.
{full_name}"""
    },

    # J - Flexible
    {
        "subject": "Seafarer application - {desired_rank}",
        "body": """Dear Hiring Team,

I am applying for the {desired_rank} position.
Experience: {experience_years} years
Vessel type: {vessel_type}

CV attached.

Regards,
{full_name}"""
    }
]

def generate_hybrid_letter(cv_data: dict, company_name: str) -> dict:
    """
    Генерирует AI-гибридное письмо

    Args:
        cv_data: данные из CV (full_name, desired_rank, etc.)
        company_name: название компании-получателя

    Returns:
        {
            'subject': str,
            'body': str,
            'used_ai': bool
        }
    """
    # Выбираем рандомный шаблон
    template = random.choice(TEMPLATES)

    # Подставляем данные (с безопасной обработкой)
    subject = _safe_format(template["subject"], cv_data)
    body = _safe_format(template["body"], cv_data)

    # AI "очеловечивание"
    ai_body = _humanize_with_ai(body, cv_data, company_name)

    if ai_body:
        body = ai_body
        used_ai = True
    else:
        # Fallback - локальное улучшение
        body = _local_humanize(body, cv_data)
        used_ai = False

    return {
        "subject": subject,
        "body": body,
        "used_ai": used_ai
    }

def _safe_format(template: str, data: dict) -> str:
    """Безопасная подстановка с заменой отсутствующих полей"""
    try:
        return template.format(**data)
    except KeyError:
        # Заменяем отсутствующие поля
        result = template
        for key, value in data.items():
            placeholder = "{" + key + "}"
            if placeholder in result:
                result = result.replace(placeholder, str(value))
        # Оставшиеся {field} заменяем на пустую строку
        result = re.sub(r'\{[^}]+\}', '', result)
        return result

def _humanize_with_ai(template_body: str, cv_data: dict, company_name: str) -> str:
    """AI-очеловечивание через Gemini 1.5 Flash"""
    if not genai:
        logger.warning("⚠️ google-generativeai не установлен - skipping AI")
        return None

    api_key = os.getenv('GOOGLE_AI_API_KEY')
    if not api_key:
        logger.warning("⚠️ No GOOGLE_AI_API_KEY - skipping AI")
        return None

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')

        prompt = f"""You are a maritime HR assistant. Lightly improve this email.

Rules:
- Change 10-15% of wording to sound natural and unique
- Add ONE short personalized sentence about candidate's last company: {cv_data.get('current_company', 'N/A')}
- Keep it professional and short (under 150 words)
- DO NOT add promises or guarantees
- Output ONLY the email body (no subject, no extra text)

Candidate: {cv_data.get('full_name')}
Position: {cv_data.get('desired_rank')}
Company: {company_name}

Template:
{template_body}
"""

        response = model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.3,
                'max_output_tokens': 250
            }
        )

        improved_text = response.text.strip()
        logger.info(f"✅ AI улучшил письмо для {company_name}")
        return improved_text

    except Exception as e:
        logger.error(f"❌ AI humanization failed: {e}")
        return None

def _local_humanize(template_body: str, cv_data: dict) -> str:
    """Локальный fallback - простые замены"""
    text = template_body

    # Добавляем персональную фразу о последней компании
    if cv_data.get('current_company'):
        personal = f"\nMy last contract was with {cv_data['current_company']}."
        # Вставляем после первого абзаца
        lines = text.split('\n\n')
        if len(lines) > 1:
            lines.insert(1, personal.strip())
            text = '\n\n'.join(lines)

    # Простые замены для вариативности (50% вероятность)
    replacements = [
        ("I would like to apply", "I would like to be considered"),
        ("CV attached", "Please find my CV attached"),
        ("All certificates are valid", "All documents are up to date"),
        ("immediately", "at your earliest convenience")
    ]

    for old, new in replacements:
        if random.random() > 0.5 and old in text:
            text = text.replace(old, new)

    logger.info("✅ Локальное улучшение письма (fallback)")
    return text
