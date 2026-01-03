"""
Контекстные переменные для передачи данных между middleware и хуками
"""

from contextvars import ContextVar
from typing import Optional


# Контекстная переменная для хранения key_name текущего запроса
current_key_name: ContextVar[Optional[str]] = ContextVar("current_key_name", default=None)
