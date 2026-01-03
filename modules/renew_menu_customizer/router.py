"""
Модуль renew_menu_customizer - Кастомизация меню продления

Версия: 1.0.0-alpha
"""

from math import ceil

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_balance, get_key_details, get_tariff_by_id
from handlers.buttons import MAIN_MENU, PAYMENT
from handlers.utils import edit_or_send_message
from hooks.hooks import register_hook
from logger import logger

from .context import current_key_name
from .middleware import RenewMenuMiddleware


router = Router(name="renew_menu_customizer")

# Глобальный флаг для отключения кастомизации
_customization_disabled = False


def register_module_middleware():
    """
    Функция для регистрации middleware модуля.
    
    Returns:
        dict: middleware данные с ключом "middleware"
    """
    return {"middleware": RenewMenuMiddleware()}


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
            logger.info(f"[RenewMenuCustomizer] У ключа нет тарифа")
            return _create_show_all_button_only(key_name)

        # Получаем информацию о тарифе
        current_tariff = await get_tariff_by_id(session, current_tariff_id)
        if not current_tariff or not current_tariff.get("is_active"):
            logger.info(f"[RenewMenuCustomizer] Тариф недоступен")
            return _create_show_all_button_only(key_name)

        # Проверяем группу тарифа
        forbidden_groups = ["trial", "gifts"]
        if current_tariff.get("group_code") in forbidden_groups:
            logger.info(f"[RenewMenuCustomizer] Тариф в запрещённой группе")
            return _create_show_all_button_only(key_name)

        # Создаём команды для модификации клавиатуры
        commands = []

        # Удаляем стандартные кнопки тарифов
        commands.append({"remove_prefix": "renew_plan|"})
        commands.append({"remove_prefix": "renew_subgroup|"})

        # Кнопка быстрого продления БЕЗ цены
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


def _create_show_all_button_only(key_name: str) -> list:
    """Создаёт только кнопку показа всех тарифов"""
    show_all_button = InlineKeyboardButton(
        text="📋 Показать все тарифы",
        callback_data=f"renew_key_show_all|{key_name}"
    )
    
    return [
        {"remove_prefix": "renew_plan|"},
        {"remove_prefix": "renew_subgroup|"},
        {"insert_at": 0, "button": show_all_button}
    ]


@router.callback_query(F.data.regexp(r"^quick_renew_\d+\|"))
async def handle_quick_renew(callback_query: CallbackQuery, state: FSMContext, session: AsyncSession):
    """Обработчик быстрого продления текущего тарифа"""
    try:
        tg_id = callback_query.from_user.id
        callback_data = callback_query.data
        
        parts = callback_data.split("|")
        tariff_id = int(parts[0].replace("quick_renew_", ""))
        key_name = parts[1] if len(parts) > 1 else None

        if not key_name:
            await callback_query.answer("❌ Ошибка: не указан ключ", show_alert=True)
            return

        # Проверяем тариф
        tariff = await get_tariff_by_id(session, tariff_id)
        if not tariff or not tariff.get("is_active"):
            await callback_query.answer("❌ Тариф недоступен", show_alert=True)
            
            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(
                text="📋 Показать все тарифы",
                callback_data=f"renew_key_show_all|{key_name}"
            ))
            builder.row(InlineKeyboardButton(text=MAIN_MENU, callback_data="profile"))
            
            await edit_or_send_message(
                target_message=callback_query.message,
                text="❌ <b>Выбранный тариф больше не доступен</b>\n\nВыберите другой тариф.",
                reply_markup=builder.as_markup()
            )
            return

        # Проверяем баланс
        balance = round(await get_balance(session, tg_id) or 0, 2)
        cost_raw = tariff.get("price_rub", 0)
        cost = round(float(cost_raw) if cost_raw is not None else 0, 2)

        if balance < cost:
            required_amount = ceil(cost - balance)
            required_text = f"{required_amount:.0f} ₽"

            builder = InlineKeyboardBuilder()
            builder.row(InlineKeyboardButton(text=PAYMENT, callback_data="pay"))
            builder.row(InlineKeyboardButton(
                text="📋 Выбрать другой тариф",
                callback_data=f"renew_key_show_all|{key_name}"
            ))
            builder.row(InlineKeyboardButton(text=MAIN_MENU, callback_data="profile"))

            await edit_or_send_message(
                target_message=callback_query.message,
                text=(
                    f"❌ <b>Недостаточно средств</b>\n\n"
                    f"Для продления «{tariff['name']}» пополните баланс.\n\n"
                    f"<b>Требуется:</b> {required_text}"
                ),
                reply_markup=builder.as_markup()
            )
            return

        # Баланса достаточно - обновляем state и вызываем стандартный обработчик
        logger.info(f"[RenewMenuCustomizer] Быстрое продление: tariff_id={tariff_id}, key={key_name}")
        
        # Получаем информацию о ключе
        key_info = await get_key_details(session, key_name)
        if not key_info:
            await callback_query.answer("❌ Ключ не найден", show_alert=True)
            return
        
        # Обновляем FSM state
        await state.update_data(
            renew_key_name=key_name,
            renew_client_id=key_info["client_id"]
        )
        
        await callback_query.answer("✅ Обрабатываем продление...", show_alert=False)
        
        # Импортируем и вызываем стандартный обработчик
        from handlers.keys.key_renew import process_callback_renew_plan
        
        # Создаём новый callback с изменённым data
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
            # Импортируем стандартный обработчик
            from handlers.keys.key_renew import process_callback_renew_key
            
            # Создаём новый callback с другим data
            new_callback = callback_query.model_copy(update={"data": f"renew_key|{key_name}"})
            
            await process_callback_renew_key(new_callback, state, session)
            
        finally:
            # Включаем кастомизацию обратно
            _customization_disabled = False
            logger.debug("[RenewMenuCustomizer] Кастомизация включена")

    except Exception as e:
        _customization_disabled = False
        logger.error(f"[RenewMenuCustomizer] Ошибка в handle_show_all_tariffs: {e}", exc_info=True)
        await callback_query.answer("❌ Произошла ошибка", show_alert=True)
