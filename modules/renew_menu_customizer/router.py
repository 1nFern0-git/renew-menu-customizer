"""
Модуль renew_menu_customizer - Кастомизация меню продления

Версия: 1.0.1-alpha
"""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_key_details, get_tariff_by_id
from hooks.hooks import register_hook
from logger import logger

from .context import current_key_name


router = Router(name="renew_menu_customizer")

# Глобальный флаг для отключения кастомизации
_customization_disabled = False


@register_hook("renew_tariffs")
async def customize_renew_menu(chat_id: int, admin: bool, session: AsyncSession, **kwargs):
    """
    Хук для модификации меню продления подписки.
    Получает key_name из контекста (ContextVar).
    """
    global _customization_disabled
    
    if _customization_disabled:
        logger.debug("[RenewMenuCustomizer] Кастомизация отключена")
        return []
    
    try:
        # Получаем key_name из контекста
        key_name = current_key_name.get()
        
        if not key_name:
            logger.warning("[RenewMenuCustomizer] key_name не найден в контексте")
            return []
        
        logger.debug(f"[RenewMenuCustomizer] key_name: {key_name}")

        # Получаем информацию о ключе
        key_info = await get_key_details(session, key_name)
        if not key_info:
            logger.warning(f"[RenewMenuCustomizer] Ключ {key_name} не найден")
            return []

        current_tariff_id = key_info.get("tariff_id")
        if not current_tariff_id:
            logger.info(f"[RenewMenuCustomizer] У ключа нет тарифа — пропускаем кастомизацию")
            return []

        # Получаем информацию о тарифе
        current_tariff = await get_tariff_by_id(session, current_tariff_id)
        if not current_tariff or not current_tariff.get("is_active"):
            logger.info(f"[RenewMenuCustomizer] Тариф недоступен — пропускаем кастомизацию")
            return []

        # Проверяем группу тарифа
        forbidden_groups = ["trial", "gifts"]
        if current_tariff.get("group_code") in forbidden_groups:
            logger.info(f"[RenewMenuCustomizer] Тариф в запрещённой группе — пропускаем кастомизацию")
            return []

        # Создаём команды для модификации клавиатуры
        commands = []

        # Удаляем стандартные кнопки тарифов
        commands.append({"remove_prefix": "renew_plan|"})
        commands.append({"remove_prefix": "renew_subgroup|"})

        # Кнопка быстрого продления
        tariff_name = current_tariff.get('name', 'Текущий тариф')
        quick_renew_button = InlineKeyboardButton(
            text=f"💳 Продлить «{tariff_name}»",
            callback_data=f"quick_renew_{current_tariff_id}|{key_name}"
        )
        commands.append({"insert_at": 0, "button": quick_renew_button})

        # Кнопка "Показать все тарифы"
        show_all_button = InlineKeyboardButton(
            text="📋 Показать все тарифы",
            callback_data=f"renew_key_show_all|{key_name}"
        )
        commands.append({"insert_at": 1, "button": show_all_button})

        logger.info(f"[RenewMenuCustomizer] Меню кастомизировано: {tariff_name}")
        return commands

    except Exception as e:
        logger.error(f"[RenewMenuCustomizer] Ошибка: {e}", exc_info=True)
        return []


@router.callback_query(F.data.regexp(r"^quick_renew_\d+\|"))
async def handle_quick_renew(callback_query: CallbackQuery, state: FSMContext, session: AsyncSession):
    """
    Обработчик быстрого продления текущего тарифа.
    
    Перенаправляет на стандартное меню подтверждения тарифа,
    где реализованы выбор опций и проверка баланса.
    """
    try:
        callback_data = callback_query.data
        
        parts = callback_data.split("|")
        tariff_id = int(parts[0].replace("quick_renew_", ""))
        key_name = parts[1] if len(parts) > 1 else None

        if not key_name:
            await callback_query.answer("❌ Ошибка: не указан ключ", show_alert=True)
            return

        # Проверяем доступность тарифа
        tariff = await get_tariff_by_id(session, tariff_id)
        if not tariff or not tariff.get("is_active"):
            await callback_query.answer("❌ Тариф недоступен", show_alert=True)
            
            # Перенаправляем на меню со всеми тарифами
            from handlers.keys.key_renew import process_callback_renew_key
            new_callback = callback_query.model_copy(update={"data": f"renew_key|{key_name}"})
            await process_callback_renew_key(new_callback, state, session)
            return

        # Получаем информацию о ключе для обновления state
        key_info = await get_key_details(session, key_name)
        if not key_info:
            await callback_query.answer("❌ Ключ не найден", show_alert=True)
            return
        
        # Обновляем FSM state
        await state.update_data(
            renew_key_name=key_name,
            renew_client_id=key_info["client_id"]
        )
        
        logger.info(f"[RenewMenuCustomizer] Быстрое продление: tariff_id={tariff_id}, key={key_name}")
        
        # Перенаправляем на стандартный обработчик подтверждения тарифа
        from handlers.keys.key_renew import process_callback_renew_plan
        
        new_callback = callback_query.model_copy(update={"data": f"renew_plan|{tariff_id}"})
        await process_callback_renew_plan(new_callback, state, session)

    except Exception as e:
        logger.error(f"[RenewMenuCustomizer] Ошибка в handle_quick_renew: {e}", exc_info=True)
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)


@router.callback_query(F.data.startswith("renew_key_show_all|"))
async def handle_show_all_tariffs(callback_query: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Показывает все доступные тарифы"""
    global _customization_disabled
    
    try:
        key_name = callback_query.data.split("|")[1]
        
        logger.info(f"[RenewMenuCustomizer] Показываем все тарифы для {key_name}")
        await callback_query.answer("📋 Показываю все тарифы...", show_alert=False)
        
        # Временно отключаем кастомизацию
        _customization_disabled = True
        
        try:
            from handlers.keys.key_renew import process_callback_renew_key
            
            new_callback = callback_query.model_copy(update={"data": f"renew_key|{key_name}"})
            await process_callback_renew_key(new_callback, state, session)
            
        finally:
            _customization_disabled = False
            logger.debug("[RenewMenuCustomizer] Кастомизация включена")

    except Exception as e:
        _customization_disabled = False
        logger.error(f"[RenewMenuCustomizer] Ошибка в handle_show_all_tariffs: {e}", exc_info=True)
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)
