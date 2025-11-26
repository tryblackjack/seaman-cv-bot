# -*- coding: utf-8 -*-
"""
Пример использования QueueManager для управления очередью рассылки
"""
import asyncio
import logging
from queue_manager import QueueManager, Priority

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Пример callback функции для обработки задачи
async def process_email_task(data):
    """
    Функция обработки задачи отправки email

    Args:
        data: Словарь с данными задачи
    """
    user_id = data.get('user_id')
    email = data.get('email')
    cv_path = data.get('cv_path')

    logger.info(f"📧 Отправка email для пользователя {user_id} на {email}")

    # Здесь должна быть логика отправки email
    await asyncio.sleep(2)  # Имитация отправки

    logger.info(f"✅ Email отправлен на {email}")
    return {"success": True, "email": email}


async def main():
    """Пример использования QueueManager"""

    # Создаем менеджер очереди
    queue = QueueManager(max_concurrent_tasks=3)

    # Запускаем обработку
    await queue.start()

    # Добавляем задачи с разными приоритетами

    # Обычный пользователь
    task_id_1 = queue.add_task(
        user_id=12345,
        data={
            'user_id': 12345,
            'email': 'crew@company1.com',
            'cv_path': '/path/to/cv.pdf'
        },
        priority=Priority.NORMAL,
        callback=process_email_task
    )
    logger.info(f"Добавлена задача {task_id_1} с приоритетом NORMAL")

    # Платный пользователь (высокий приоритет)
    task_id_2 = queue.add_task(
        user_id=67890,
        data={
            'user_id': 67890,
            'email': 'hr@company2.com',
            'cv_path': '/path/to/cv2.pdf'
        },
        priority=Priority.URGENT,
        callback=process_email_task
    )
    logger.info(f"Добавлена задача {task_id_2} с приоритетом URGENT")

    # Еще одна обычная задача
    task_id_3 = queue.add_task(
        user_id=11111,
        data={
            'user_id': 11111,
            'email': 'manning@company3.com',
            'cv_path': '/path/to/cv3.pdf'
        },
        priority=Priority.NORMAL,
        callback=process_email_task
    )
    logger.info(f"Добавлена задача {task_id_3} с приоритетом NORMAL")

    # Проверяем статистику
    await asyncio.sleep(1)
    stats = queue.get_stats()
    logger.info(f"📊 Статистика: {stats}")

    # Проверяем статус задачи
    status = queue.get_status(task_id_1)
    logger.info(f"Статус задачи {task_id_1}: {status}")

    # Ждем завершения всех задач
    await asyncio.sleep(10)

    # Финальная статистика
    final_stats = queue.get_stats()
    logger.info(f"📊 Финальная статистика: {final_stats}")

    # Останавливаем обработку
    await queue.stop()


if __name__ == '__main__':
    asyncio.run(main())
