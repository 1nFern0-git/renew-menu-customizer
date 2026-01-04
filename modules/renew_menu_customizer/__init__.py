"""
Модуль Renew Menu Customizer
=============================

Кастомизация меню продления подписки БЕЗ изменений в ядре.

Версия: 1.0.1-alpha
Дата: 2026-01-04
Автор: 1nFern0-git
"""

from .middleware import RenewMenuMiddleware
from .router import router

__all__ = ["router", "RenewMenuMiddleware"]
__version__ = "1.0.1-alpha"


# При импорте модуля регистрируем middleware глобально
try:
    from bot import dp
    
    # Регистрируем middleware на dispatcher
    dp.callback_query.outer_middleware(RenewMenuMiddleware())
    
    from logger import logger
    logger.info("[RenewMenuCustomizer] Middleware зарегистрирован")
except Exception as e:
    # Если не удалось зарегистрировать - не критично, логируем
    try:
        from logger import logger
        logger.warning(f"[RenewMenuCustomizer] Не удалось зарегистрировать middleware: {e}")
    except:
        pass
