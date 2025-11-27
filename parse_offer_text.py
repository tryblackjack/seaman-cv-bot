# -*- coding: utf-8 -*-
import json

# Читаем извлеченный текст
with open('extracted_offer.json', 'r', encoding='utf-8') as f:
    data = json.load(f)

full_text = data['text']

# Разделяем по языкам
ru_marker = "🇷🇺 ДОГОВОР ПУБЛИЧНОЙ ОФЕРТЫ"
en_marker = "🇬🇧 PUBLIC OFFER AGREEMENT"
uk_marker = "🇺🇦 ДОГОВІР ПУБЛІЧНОЇ ОФЕРТИ"

# Находим индексы начала каждого языка
ru_start = full_text.find(ru_marker)
en_start = full_text.find(en_marker)
uk_start = full_text.find(uk_marker)

# Извлекаем тексты для каждого языка
ru_text = full_text[ru_start:en_start].strip()
en_text = full_text[en_start:uk_start].strip()
uk_text = full_text[uk_start:].strip()

# Сохраняем результат
result = {
    'ru': ru_text,
    'en': en_text,
    'uk': uk_text
}

with open('offer_by_language.json', 'w', encoding='utf-8') as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print(f"RU length: {len(ru_text)} chars")
print(f"EN length: {len(en_text)} chars")
print(f"UK length: {len(uk_text)} chars")
print("\nSaved to offer_by_language.json")
