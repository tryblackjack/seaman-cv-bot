# -*- coding: utf-8 -*-
"""
Менеджер базы данных крюинговых компаний
"""
import json
import os
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Управление базой данных крюинговых компаний"""

    def __init__(self, db_file: str):
        """
        Args:
            db_file: Путь к JSON файлу с базой данных
        """
        self.db_file = db_file
        self.cache: Dict[str, List[str]] = {}
        self.load()

    def load(self) -> None:
        """Загружает базу данных из файла"""
        try:
            if os.path.exists(self.db_file):
                with open(self.db_file, 'r', encoding='utf-8') as f:
                    self.cache = json.load(f)
                logger.info(f"✅ База данных загружена: {len(self.cache)} записей")
            else:
                # Создаем тестовую базу
                self.cache = {
                    "crew@maersk.com": ["CONTAINER"],
                    "hr@bourbon-offshore.com": ["OFFSHORE", "AHTS"],
                    "manning@osm.no": ["OFFSHORE"],
                    "test@crewing.com": ["TANKER"]
                }
                logger.warning(f"⚠️ Файл {self.db_file} не найден. Создана тестовая база.")
                self.save()
        except Exception as e:
            logger.error(f"❌ Ошибка загрузки базы данных: {e}")
            self.cache = {}

    def save(self) -> None:
        """Сохраняет базу данных в файл"""
        try:
            # Создаем директорию если не существует
            os.makedirs(os.path.dirname(self.db_file), exist_ok=True)

            with open(self.db_file, 'w', encoding='utf-8') as f:
                json.dump(self.cache, f, indent=2, ensure_ascii=False)
            logger.info(f"✅ База данных сохранена: {len(self.cache)} записей")
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения базы данных: {e}")

    def get_all(self) -> Dict[str, List[str]]:
        """Возвращает всю базу данных"""
        return self.cache.copy()

    def get_by_vessel_type(self, vessel_type: str) -> List[str]:
        """
        Находит все email'ы крюингов по типу судна

        Args:
            vessel_type: Тип судна (CONTAINER, TANKER, OFFSHORE, etc.)

        Returns:
            Список email адресов
        """
        vessel_type = vessel_type.upper().strip()
        result = []

        for email, types in self.cache.items():
            if vessel_type == 'ANY' or vessel_type in [t.upper() for t in types]:
                result.append(email)

        return result

    def find_matching_emails(self, preferences: str, exclude_company: Optional[str] = None) -> List[str]:
        """
        Находит подходящие email'ы по предпочтениям пользователя

        Args:
            preferences: Предпочтения по типам судов (например "CONTAINER, TANKER" или "ANY")
            exclude_company: Название компании для исключения

        Returns:
            Список подходящих email адресов
        """
        result = []
        preferences_upper = preferences.upper().strip()

        # Разбиваем предпочтения на отдельные типы
        pref_list = [p.strip() for p in preferences_upper.split(',')]

        for email, vessel_types in self.cache.items():
            # Исключаем текущего работодателя
            if exclude_company and exclude_company.lower() != "none":
                if exclude_company.lower() in email.lower():
                    logger.info(f"⏭️ Пропуск {email} (текущий работодатель)")
                    continue

            # Проверяем совпадение типов
            if 'ANY' in pref_list:
                result.append(email)
            else:
                vessel_types_upper = [vt.upper() for vt in vessel_types]
                if any(pref in vessel_types_upper for pref in pref_list):
                    result.append(email)

        logger.info(f"🎯 Найдено {len(result)} подходящих крюингов")
        return result

    def add_company(self, email: str, vessel_types: List[str]) -> None:
        """
        Добавляет новую компанию в базу

        Args:
            email: Email крюинговой компании
            vessel_types: Список типов судов
        """
        self.cache[email] = vessel_types
        self.save()
        logger.info(f"✅ Добавлена компания: {email}")

    def remove_company(self, email: str) -> bool:
        """
        Удаляет компанию из базы

        Args:
            email: Email крюинговой компании

        Returns:
            True если удалено, False если не найдено
        """
        if email in self.cache:
            del self.cache[email]
            self.save()
            logger.info(f"✅ Удалена компания: {email}")
            return True
        return False

    def update_company(self, email: str, vessel_types: List[str]) -> bool:
        """
        Обновляет типы судов для компании

        Args:
            email: Email крюинговой компании
            vessel_types: Новый список типов судов

        Returns:
            True если обновлено, False если не найдено
        """
        if email in self.cache:
            self.cache[email] = vessel_types
            self.save()
            logger.info(f"✅ Обновлена компания: {email}")
            return True
        return False

    def count(self) -> int:
        """Возвращает количество компаний в базе"""
        return len(self.cache)
