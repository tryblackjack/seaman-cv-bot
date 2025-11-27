# -*- coding: utf-8 -*-
import json
from docx import Document

try:
    # Читаем docx файл
    doc = Document('Оферта_i18n.docx')

    # Собираем весь текст
    full_text = []
    for para in doc.paragraphs:
        if para.text.strip():  # Пропускаем пустые параграфы
            full_text.append(para.text)

    # Объединяем в один текст
    complete_text = '\n\n'.join(full_text)

    # Сохраняем в JSON файл для дальнейшего использования
    result = {
        'text': complete_text,
        'paragraphs': full_text
    }

    with open('extracted_offer.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print("OK: Text extracted and saved to extracted_offer.json")
    print(f"Total paragraphs: {len(full_text)}")
    print(f"Text length: {len(complete_text)} characters")

except ImportError as e:
    print(f"ERROR Import: {e}")
    print("Install python-docx: pip install python-docx")
except Exception as e:
    print(f"ERROR: {e}")
