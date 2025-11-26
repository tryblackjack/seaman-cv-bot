# -*- coding: utf-8 -*-
"""
Менеджер очереди рассылки с приоритетами
"""
import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from typing import Optional, Dict, Any, Callable
from queue import PriorityQueue

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    """Уровни приоритета задач (чем меньше число, тем выше приоритет)"""
    URGENT = 1      # Срочные задачи (платные пользователи)
    HIGH = 2        # Высокий приоритет
    NORMAL = 3      # Обычный приоритет
    LOW = 4         # Низкий приоритет


@dataclass(order=True)
class Task:
    """Задача в очереди"""
    priority: int
    timestamp: float = field(default_factory=lambda: datetime.now().timestamp())
    user_id: int = field(default=0, compare=False)
    task_id: str = field(default="", compare=False)
    data: Dict[str, Any] = field(default_factory=dict, compare=False)
    callback: Optional[Callable] = field(default=None, compare=False)

    def __post_init__(self):
        if not self.task_id:
            self.task_id = f"{self.user_id}_{int(self.timestamp)}"


class QueueManager:
    """Менеджер очереди с приоритетами для асинхронной обработки задач"""

    def __init__(self, max_concurrent_tasks: int = 3):
        """
        Args:
            max_concurrent_tasks: Максимальное количество одновременно выполняемых задач
        """
        self.queue: PriorityQueue[Task] = PriorityQueue()
        self.max_concurrent_tasks = max_concurrent_tasks
        self.active_tasks: Dict[str, Task] = {}
        self.completed_tasks: Dict[str, Dict[str, Any]] = {}
        self.failed_tasks: Dict[str, Dict[str, Any]] = {}
        self.is_running = False
        self._worker_task: Optional[asyncio.Task] = None

    def add_task(
        self,
        user_id: int,
        data: Dict[str, Any],
        priority: Priority = Priority.NORMAL,
        callback: Optional[Callable] = None,
        task_id: Optional[str] = None
    ) -> str:
        """
        Добавляет задачу в очередь

        Args:
            user_id: ID пользователя
            data: Данные задачи
            priority: Приоритет задачи
            callback: Callback функция для выполнения
            task_id: Уникальный ID задачи (опционально)

        Returns:
            ID добавленной задачи
        """
        task = Task(
            priority=priority.value,
            user_id=user_id,
            task_id=task_id or "",
            data=data,
            callback=callback
        )

        self.queue.put(task)
        logger.info(f"📋 Задача {task.task_id} добавлена в очередь (приоритет: {priority.name})")
        return task.task_id

    def get_queue_size(self) -> int:
        """Возвращает размер очереди"""
        return self.queue.qsize()

    def get_active_count(self) -> int:
        """Возвращает количество активных задач"""
        return len(self.active_tasks)

    def get_position(self, task_id: str) -> Optional[int]:
        """
        Возвращает позицию задачи в очереди

        Args:
            task_id: ID задачи

        Returns:
            Позицию в очереди или None если не найдена
        """
        if task_id in self.active_tasks:
            return 0  # Задача выполняется

        # Проверка в очереди (необходимо перебрать)
        temp_queue = []
        position = None
        idx = 1

        while not self.queue.empty():
            task = self.queue.get()
            temp_queue.append(task)
            if task.task_id == task_id:
                position = idx
            idx += 1

        # Возвращаем задачи обратно
        for task in temp_queue:
            self.queue.put(task)

        return position

    def get_status(self, task_id: str) -> Dict[str, Any]:
        """
        Возвращает статус задачи

        Args:
            task_id: ID задачи

        Returns:
            Словарь со статусом задачи
        """
        if task_id in self.active_tasks:
            return {
                "status": "active",
                "task": self.active_tasks[task_id]
            }
        elif task_id in self.completed_tasks:
            return {
                "status": "completed",
                "result": self.completed_tasks[task_id]
            }
        elif task_id in self.failed_tasks:
            return {
                "status": "failed",
                "error": self.failed_tasks[task_id]
            }
        else:
            position = self.get_position(task_id)
            if position is not None:
                return {
                    "status": "queued",
                    "position": position
                }
            else:
                return {
                    "status": "not_found"
                }

    async def process_task(self, task: Task) -> None:
        """
        Обрабатывает одну задачу

        Args:
            task: Задача для обработки
        """
        self.active_tasks[task.task_id] = task
        logger.info(f"⚙️ Обработка задачи {task.task_id} (пользователь: {task.user_id})")

        try:
            if task.callback:
                if asyncio.iscoroutinefunction(task.callback):
                    result = await task.callback(task.data)
                else:
                    result = task.callback(task.data)

                self.completed_tasks[task.task_id] = {
                    "user_id": task.user_id,
                    "result": result,
                    "completed_at": datetime.now().isoformat()
                }
                logger.info(f"✅ Задача {task.task_id} завершена успешно")
            else:
                logger.warning(f"⚠️ Задача {task.task_id} не имеет callback")

        except Exception as e:
            logger.error(f"❌ Ошибка при выполнении задачи {task.task_id}: {e}")
            self.failed_tasks[task.task_id] = {
                "user_id": task.user_id,
                "error": str(e),
                "failed_at": datetime.now().isoformat()
            }

        finally:
            if task.task_id in self.active_tasks:
                del self.active_tasks[task.task_id]

    async def worker(self) -> None:
        """Основной worker для обработки очереди"""
        logger.info("🚀 Queue worker запущен")

        while self.is_running:
            try:
                # Ждем пока есть свободные слоты
                while len(self.active_tasks) >= self.max_concurrent_tasks:
                    await asyncio.sleep(0.5)

                # Получаем задачу из очереди
                if not self.queue.empty():
                    task = self.queue.get()
                    asyncio.create_task(self.process_task(task))
                else:
                    await asyncio.sleep(1)

            except Exception as e:
                logger.error(f"❌ Ошибка в worker: {e}")
                await asyncio.sleep(1)

        logger.info("🛑 Queue worker остановлен")

    async def start(self) -> None:
        """Запускает обработку очереди"""
        if not self.is_running:
            self.is_running = True
            self._worker_task = asyncio.create_task(self.worker())
            logger.info("✅ QueueManager запущен")

    async def stop(self) -> None:
        """Останавливает обработку очереди"""
        if self.is_running:
            self.is_running = False
            if self._worker_task:
                await self._worker_task
            logger.info("✅ QueueManager остановлен")

    def clear(self) -> None:
        """Очищает очередь"""
        while not self.queue.empty():
            self.queue.get()
        self.active_tasks.clear()
        logger.info("🗑️ Очередь очищена")

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику очереди"""
        return {
            "queued": self.queue.qsize(),
            "active": len(self.active_tasks),
            "completed": len(self.completed_tasks),
            "failed": len(self.failed_tasks),
            "is_running": self.is_running
        }
