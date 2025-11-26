# 📦 Модульная структура бота

## Обзор модулей

Бот разделен на следующие модули для улучшения читаемости и поддерживаемости кода:

```
Seaman_job/
├── bot/
│   ├── __init__.py                  # Инициализация пакета
│   ├── main.py                      # Старая монолитная версия (603 строки)
│   ├── main_new.py                  # Новая модульная версия
│   ├── database_manager.py          # Управление базой крюингов
│   ├── email_sender.py              # Отправка email через SMTP/SendGrid
│   ├── queue_manager.py             # Очередь с приоритетами
│   └── example_queue_usage.py       # Пример использования очереди
├── config/
│   ├── __init__.py                  # Инициализация конфигурации
│   └── settings.py                  # Все настройки проекта
└── i18n/
    ├── en.json                      # Английская локализация
    ├── ru.json                      # Русская локализация
    └── uk.json                      # Украинская локализация
```

---

## 🔧 1. config/settings.py

**Назначение:** Централизованное хранение всех настроек проекта

**Основные настройки:**
- Telegram токены и пароли
- Email конфигурация (Gmail/SMTP)
- Ollama AI настройки
- Пути к базе данных и временным файлам
- Мультиязычность
- Логирование

**Использование:**
```python
from config import settings

# Доступ к настройкам
bot_token = settings.TELEGRAM_BOT_TOKEN
test_mode = settings.TEST_MODE
db_file = settings.LOCAL_DB_FILE
```

**Переменные окружения:**
Настройки можно переопределить через `.env` файл:
```env
TELEGRAM_BOT_TOKEN=your_token_here
USE_GMAIL=True
GMAIL_ADDRESS=your@gmail.com
TEST_MODE=False
```

---

## 🗄️ 2. bot/database_manager.py

**Назначение:** Управление базой данных крюинговых компаний

**Класс:** `DatabaseManager`

**Основные методы:**

### `__init__(db_file: str)`
Инициализация менеджера базы данных
```python
from bot.database_manager import DatabaseManager

db = DatabaseManager('data/recruiter_vessel_map.json')
```

### `load()` / `save()`
Загрузка и сохранение базы данных
```python
db.load()  # Загружает из файла
db.save()  # Сохраняет в файл
```

### `find_matching_emails(preferences: str, exclude_company: str = None) -> List[str]`
Находит подходящие email'ы по предпочтениям
```python
# Найти все крюинги для контейнеровозов
emails = db.find_matching_emails('CONTAINER')

# Найти танкеры и офшоры, исключить Maersk
emails = db.find_matching_emails('TANKER, OFFSHORE', 'Maersk')
```

### `add_company(email: str, vessel_types: List[str])`
Добавляет новую компанию
```python
db.add_company('hr@newcompany.com', ['CONTAINER', 'TANKER'])
```

### `count() -> int`
Возвращает количество компаний
```python
total = db.count()
print(f"Всего компаний: {total}")
```

---

## 📧 3. bot/email_sender.py

**Назначение:** Отправка email через SMTP или SendGrid API

**Класс:** `EmailSender`

**Основные методы:**

### `__init__(...)`
Инициализация с настройками email
```python
from bot.email_sender import EmailSender

sender = EmailSender(
    use_gmail=True,
    gmail_address='info@company.com',
    gmail_app_password='your_app_password'
)
```

### `send_smtp(target_email, subject, body, cv_path=None, reply_to=None) -> bool`
Отправка через SMTP
```python
success = sender.send_smtp(
    target_email='crew@company.com',
    subject='CV Application: Chief Engineer',
    body='Dear Sir, please find my CV attached.',
    cv_path='/path/to/cv.pdf',
    reply_to='seafarer@gmail.com'
)
```

### `send_sendgrid(...)`
Отправка через SendGrid API (если установлен)

### `send(..., use_sendgrid=False) -> bool`
Универсальный метод отправки
```python
# Автоматически выберет SMTP или SendGrid
sender.send(
    target_email='hr@company.com',
    subject='Application',
    body='CV attached',
    cv_path='cv.pdf'
)
```

---

## 📋 4. bot/queue_manager.py

**Назначение:** Управление очередью задач с приоритетами

**Классы:** `QueueManager`, `Priority`, `Task`

**Enum Priority:**
- `URGENT = 1` - Срочные задачи (платные пользователи)
- `HIGH = 2` - Высокий приоритет
- `NORMAL = 3` - Обычный приоритет
- `LOW = 4` - Низкий приоритет

**Основные методы:**

### `__init__(max_concurrent_tasks: int = 3)`
```python
from bot.queue_manager import QueueManager, Priority

queue = QueueManager(max_concurrent_tasks=5)
```

### `add_task(user_id, data, priority, callback) -> str`
Добавляет задачу в очередь
```python
async def send_email(data):
    email = data['email']
    print(f"Sending to {email}")
    return {"success": True}

task_id = queue.add_task(
    user_id=12345,
    data={'email': 'test@company.com'},
    priority=Priority.URGENT,
    callback=send_email
)
```

### `start()` / `stop()`
Запуск и остановка обработки очереди
```python
await queue.start()   # Запуск
# ... работа ...
await queue.stop()    # Остановка
```

### `get_stats() -> Dict`
Статистика очереди
```python
stats = queue.get_stats()
# {
#   'queued': 10,
#   'active': 3,
#   'completed': 45,
#   'failed': 2,
#   'is_running': True
# }
```

### `get_status(task_id: str) -> Dict`
Статус конкретной задачи
```python
status = queue.get_status(task_id)
# {'status': 'active'} или 'completed' или 'queued'
```

**Пример использования:**
См. `bot/example_queue_usage.py`

---

## 🤖 5. bot/main_new.py

**Назначение:** Основной файл бота с использованием всех модулей

**Отличия от старой версии (`main.py`):**
- ✅ Использует модули вместо монолитного кода
- ✅ Настройки вынесены в `config/settings.py`
- ✅ База данных через `DatabaseManager`
- ✅ Email через `EmailSender`
- ✅ Готов к интеграции `QueueManager`

**Запуск:**
```bash
python bot/main_new.py
```

---

## 🌍 6. i18n файлы

**Назначение:** Мультиязычная поддержка

**Файлы:**
- `i18n/en.json` - English
- `i18n/ru.json` - Русский
- `i18n/uk.json` - Українська

**Использование в коде:**
```python
from bot.main_new import t

# В handler'ах
await update.message.reply_text(
    t(context, 'start_welcome')
)

# С параметрами
await update.message.reply_text(
    t(context, 'targets_ready', count=10)
)
```

**Добавление нового ключа:**
1. Добавьте ключ во все 3 файла (en.json, ru.json, uk.json)
2. Используйте в коде через `t(context, 'your_key')`

---

## 🚀 Миграция со старой версии

**Шаг 1:** Переименовать старый main.py
```bash
mv bot/main.py bot/main_old.py
```

**Шаг 2:** Переименовать новый main_new.py
```bash
mv bot/main_new.py bot/main.py
```

**Шаг 3:** Создать .env файл
```bash
cp .env.example .env
# Отредактировать .env с вашими настройками
```

**Шаг 4:** Запустить
```bash
python bot/main.py
```

---

## 📝 Примеры использования

### Пример 1: Работа с базой данных
```python
from bot.database_manager import DatabaseManager

db = DatabaseManager('data/recruiter_vessel_map.json')

# Найти все контейнерные компании
emails = db.find_matching_emails('CONTAINER')
print(f"Найдено {len(emails)} компаний")

# Добавить новую компанию
db.add_company('new@crewing.com', ['TANKER', 'LNG'])

# Обновить компанию
db.update_company('new@crewing.com', ['TANKER', 'LNG', 'OFFSHORE'])
```

### Пример 2: Отправка email
```python
from bot.email_sender import EmailSender
from config import settings

sender = EmailSender(
    use_gmail=settings.USE_GMAIL,
    gmail_address=settings.GMAIL_ADDRESS,
    gmail_app_password=settings.GMAIL_APP_PASSWORD
)

success = sender.send(
    target_email='hr@company.com',
    subject='CV Application',
    body='Please find my CV attached.',
    cv_path='path/to/cv.pdf',
    reply_to='applicant@gmail.com'
)

if success:
    print("✅ Email sent!")
```

### Пример 3: Очередь с приоритетами
```python
import asyncio
from bot.queue_manager import QueueManager, Priority

async def process_task(data):
    email = data['email']
    print(f"Processing {email}")
    await asyncio.sleep(2)
    return {"sent": True}

async def main():
    queue = QueueManager(max_concurrent_tasks=3)
    await queue.start()

    # VIP пользователь
    queue.add_task(
        user_id=1,
        data={'email': 'vip@company.com'},
        priority=Priority.URGENT,
        callback=process_task
    )

    # Обычный пользователь
    queue.add_task(
        user_id=2,
        data={'email': 'normal@company.com'},
        priority=Priority.NORMAL,
        callback=process_task
    )

    await asyncio.sleep(10)
    await queue.stop()

asyncio.run(main())
```

---

## ✅ Преимущества модульной структуры

1. **Читаемость:** Код разделен на логические модули
2. **Поддерживаемость:** Легко найти и изменить нужный функционал
3. **Тестируемость:** Каждый модуль можно тестировать отдельно
4. **Переиспользование:** Модули можно использовать в других проектах
5. **Масштабируемость:** Легко добавлять новые модули

---

## 📚 Дополнительная информация

- Основной README: `../README.md`
- Примеры: `bot/example_queue_usage.py`
- Настройки: `config/settings.py`
- База данных: `data/recruiter_vessel_map.json`
