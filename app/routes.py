import asyncio
import logging
import os
import time
from datetime import date

from flask import request, jsonify, Blueprint

from app import db
from app.models import ClientsData, PartnerInfo, MessageTemplate, City, Partner, partner_salons, PartnerDailyStats
from app.services import (
    send_message,
    create_amocrm_contact,
    create_or_update_amocrm_lead,
    get_amocrm_contact_id,
    set_salon_status,
    get_salon_status,
    send_telegram_notification,
    create_partner_amocrm_contact,
    create_or_update_partner_amocrm_lead
)
from app.utils import get_random_discount

bp = Blueprint('routes', __name__)


@bp.route('/webhook', methods=['POST'])
async def webhook():
    """Обрабатывает входящие webhook-запросы от WhatsApp."""
    data = request.json
    logging.info(f"Received data: {data}")

    event_type = data.get('event', {}).get('type')

    if event_type == 'messages':
        message_data = data.get('messages', [])[0]
        chat_id = message_data.get('chat_id', '').replace('@s.whatsapp.net', '')
        message_body = message_data.get('text', {}).get('body', '').lower()

        if not chat_id or not message_body:
            logging.error("Missing phone number or message in received data")
            return jsonify({"status": "error", "message": "Invalid data"}), 400

        try:
            await handle_incoming_message(chat_id, message_body, message_data)
        except Exception as e:
            logging.error(f"Error handling incoming message: {e}")
            return jsonify({"status": "error", "message": str(e)}), 500

    return jsonify({"status": "ok"}), 200


async def handle_incoming_message(chat_id: str, message_body: str, message_data: dict):
    """Обрабатывает входящее сообщение от пользователя."""
    time.time()
    logging.info(f"Обработка сообщения для номера телефона: {chat_id}, сообщение: {message_body}")

    if message_data.get('from_me', False):
        logging.info("Пропускаем обработку сообщения, отправленного ботом")
        return

    if chat_id == os.environ.get("BOT_CHAT_ID"):
        logging.info("Пропускаем отправку сообщения самому себе")
        return

    message_body_lower = message_body.lower()

    if message_body_lower.startswith("получить подарок"):
        await handle_start_command(chat_id, message_body_lower, message_data)
    elif message_body_lower in ['да', '1', '2', 'нет', 'первый', 'предыдущий', 'второй'] or message_body.isdigit():
        await handle_user_response(chat_id, message_body_lower)
    else:
        logging.info("Сообщение не относится к логике бота и будет проигнорировано")


async def handle_start_command(chat_id: str, message_body: str, message_data: dict):
    """Обрабатывает команду 'Начать' от пользователя."""
    partner_id = message_body.split("получить подарок (", 1)[-1].replace(")", "").strip()
    client_name = message_data.get('from_name', 'Клиент')

    # Получаем PartnerInfo
    partner_info = PartnerInfo.query.get(partner_id)
    if not partner_info:
        await send_message(chat_id, await get_template_or_default('salon_not_found'))
        return

    # Получаем Partner по salon_id из partner_info
    partner = Partner.query.join(partner_salons).filter(
        partner_salons.c.salon_id == partner_info.id
    ).first()

    client_data = ClientsData.query.filter_by(chat_id=chat_id).first()

    # Проверка статуса салона для клиента
    existing_salon_status = None
    if client_data:
        existing_salon_status = await get_salon_status(client_data.id, partner_id)
        if existing_salon_status == 'visited':
            await send_message(chat_id, await get_template_or_default('already_visited'))
            return

    # Новый пользователь или пользователь не взаимодействовал с этим салоном
    if not client_data:
        # Получаем объект City по названию
        City.query.filter_by(name=partner_info.city.name).first()

        client_data = ClientsData(
            chat_id=chat_id,
            initial_salon_name=partner_info.name,
            initial_salon_id=partner_id,
            client_name=client_name,
            city=partner_info.city.name,
            discount_claimed=False,
            claimed_salon_name=None,
            claimed_salon_id=None,
            attempts_left=1,
            date=date.today(),
            partner_id=partner.id  # Добавляем partner_id
        )
        db.session.add(client_data)
        db.session.flush()  # Добавляем flush, чтобы получить ID клиента

        # Обновляем статистику - clients_brought
        update_partner_daily_stats(partner_info.id, 'clients_brought')

        await set_salon_status(client_data.id, partner_id, 'visited')

        # Отправка приветственного сообщения из шаблона
        start_message = await get_template_or_default('start_message')
        await send_message(chat_id, start_message)
    else:
        # Обновляем данные пользователя
        client_data.initial_salon_name = partner_info.name
        # Получаем объект City по названию
        City.query.filter_by(name=partner_info.city.name).first()

        client_data.city = partner_info.city.name
        client_data.discount_claimed = False
        client_data.claimed_salon_name = None
        client_data.claimed_salon_id = None
        client_data.attempts_left = 1

        # Проверяем, изменился ли initial_salon_id
        if client_data.initial_salon_id != partner_id:
            # Обновляем статистику - clients_brought для нового initial_salon_id
            update_partner_daily_stats(partner_id, 'clients_brought')

            # Обновляем initial_salon_id в данных клиента
            client_data.initial_salon_id = partner_id

        # Старый пользователь
        await send_message(chat_id, await get_template_or_default('welcome_back'))

    #  Если статус уже был установлен (claimed или rejected), не меняем его
    if existing_salon_status not in ('claimed', 'rejected'):
        await set_salon_status(client_data.id, partner_id, 'visited')

    partner_info.clients_brought += 1
    db.session.commit()
    logging.info(f"Данные сохранены в базе данных: {client_data}")

    # Создаем контакт в AmoCRM
    contact_id = await create_amocrm_contact(client_data)
    if contact_id:
        # Создаем сделку в AmoCRM
        await create_or_update_amocrm_lead(client_data, contact_id)

    await handle_discount_request(chat_id, client_data)

    # Получаем Partner по salon_id из partner_info
    partner = Partner.query.join(partner_salons).filter(
        partner_salons.c.salon_id == partner_info.id
    ).first()

    # Отправка оповещения владельцу салона
    if partner and partner.telegram_chat_id:
        owner_chat_id = partner.telegram_chat_id
        message = f"🎉 Вы привели нового клиента!\n\n{client_data.client_name} ({client_data.chat_id})"
        await send_telegram_notification(owner_chat_id, message)


async def handle_user_response(chat_id: str, message_body: str):
    """Обрабатывает ответ пользователя на запрос о скидке."""
    client_data = ClientsData.query.filter_by(chat_id=chat_id).first()
    if not client_data:
        await send_message(chat_id, await get_template_or_default('data_loading_error'))
        return

    if message_body in ['да', '1', 'второй']:
        if client_data.chosen_salon_id:
            await handle_claim_discount(chat_id, client_data)
        else:
            await send_message(chat_id, await get_template_or_default('spin_wheel_first'))
    elif message_body in ['нет', '2', 'предыдущий', 'первый']:
        if client_data.chosen_salon_id:
            await set_salon_status(client_data.id, client_data.chosen_salon_id, 'rejected')
            update_partner_daily_stats(client_data.chosen_salon_id, 'offers_rejected')         
            if client_data.attempts_left > 0: 
                client_data.attempts_left -= 1
                db.session.commit()
                await handle_discount_request(chat_id, client_data)
            else:
                # Вторая попытка, пользователь отказался - выбираем первый салон
                client_data.chosen_salon_id = client_data.first_offered_salon_id
                client_data.chosen_salon_name = PartnerInfo.query.get(client_data.chosen_salon_id).name
                update_partner_daily_stats(client_data.chosen_salon_id, 'offers_rejected', increment=-1)
                await set_salon_status(client_data.id, client_data.chosen_salon_id, 'rejected')
                await handle_claim_discount(chat_id, client_data)
        else:
            await send_message(chat_id, await get_template_or_default('user_declined'))
    else:
        await send_message(chat_id, await get_template_or_default('accept_terms'))


async def handle_discount_request(chat_id: str, client_data: ClientsData):
    """Обрабатывает запрос на скидку и отправляет сообщение с результатом."""

    await send_spinning_wheel_message(chat_id)
    
    if client_data.attempts_left > 0:
        discount_message = await get_discount_message(client_data)
        await send_message(chat_id, discount_message)
        # Обновляем статистику - offer shown
        update_partner_daily_stats(client_data.chosen_salon_id, 'offers_shown')
    else:
        await handle_no_attempts_left(chat_id, client_data)


async def handle_no_attempts_left(chat_id: str, client_data: ClientsData):
    """Обрабатывает ситуацию, когда у пользователя не осталось попыток."""
    # Выбираем случайный салон
    discount_data = await get_random_discount(client_data)
    if not discount_data:
        await send_message(chat_id, await get_template_or_default('no_discounts_available'))
        return

    chosen_salon, _ = discount_data

    # Сохраняем выбранный салон 
    client_data.chosen_salon_id = chosen_salon.id
    client_data.chosen_salon_name = chosen_salon.name
    update_partner_daily_stats(client_data.chosen_salon_id, 'offers_shown')
    db.session.commit()

    # Отправка сообщения о результате из шаблона
    get_discount_message = await get_template_or_default(
        'get_discount_message',
        discount=chosen_salon.discount,
        salon_name=chosen_salon.name,
        message_salon_name=chosen_salon.message_partner_name,
        contacts=chosen_salon.contacts,
        categories=", ".join([category.name for category in chosen_salon.categories])
    )
    await send_message(chat_id, get_discount_message)


async def handle_claim_discount(chat_id: str, client_data: ClientsData):
    """Обрабатывает запрос пользователя на получение скидки."""
    if client_data and client_data.chosen_salon_id:
        # Определяем chosen_salon здесь, вне условия if chosen_salon:
        chosen_salon = PartnerInfo.query.get(client_data.chosen_salon_id)

        if chosen_salon:
            #  Изменение client_salon_status
            await set_salon_status(client_data.id, chosen_salon.id, 'claimed')

            client_data.discount_claimed = True
            client_data.claimed_salon_name = chosen_salon.name
            client_data.claimed_salon_id = chosen_salon.id
            chosen_salon.clients_received += 1

            # Обновляем статистику - offer accepted
            update_partner_daily_stats(chosen_salon.id, 'offers_accepted')

            db.session.commit()

            # Отправка сообщения с поздравлением из шаблона
            claim_discount_message = await get_template_or_default(
                'claim_discount',
                salon_name=chosen_salon.name,
                contacts=chosen_salon.contacts,
                message_salon_name=chosen_salon.message_partner_name
            )
            await send_message(chat_id, claim_discount_message)

            # --- Создаем/обновляем сделку в вашем AmoCRM ---
            contact_id = await get_amocrm_contact_id(client_data.chat_id)
            if contact_id:
                await create_or_update_amocrm_lead(client_data, contact_id)

            # --- Создаем сделку в AmoCRM партнера ---
            partner = Partner.query.join(partner_salons).filter(
                partner_salons.c.salon_id == client_data.chosen_salon_id
            ).first()

            if partner:
                logging.info(f"Найден партнер с ID: {partner.id}")
                if partner.amocrm_subdomain and partner.amocrm_api_key and partner.amocrm_field_mapping and partner.amocrm_settings:
                    # Создаем контакт в AmoCRM партнера
                    partner_contact_id = await create_partner_amocrm_contact(client_data, partner)
                    # Создаем сделку в AmoCRM партнера
                    await create_or_update_partner_amocrm_lead(client_data, partner_contact_id, partner, chosen_salon)
            else:
                logging.warning(f"Партнер для салона с ID {client_data.chosen_salon_id} не найден!")

            # Отправка оповещения партнеру о полученном клиенте
            receiving_partner = Partner.query.join(partner_salons).filter(
                partner_salons.c.salon_id == chosen_salon.id
            ).first()
            if receiving_partner and receiving_partner.telegram_chat_id:
                receiving_partner_chat_id = receiving_partner.telegram_chat_id
                message = f"🎉 Новый клиент!\n\n{client_data.client_name} ({client_data.chat_id}) выбрал(а) скидку вашего салона."
                await send_telegram_notification(receiving_partner_chat_id, message)
        else:
            logging.warning("Не найдены контактные данные салона для этого пользователя")
            await send_message(chat_id, await get_template_or_default('general_error'))
    else:
        logging.warning("Не найдены данные о салоне для этого пользователя")
        await send_message(chat_id, await get_template_or_default('general_error'))


async def send_spinning_wheel_message(chat_id: str):
    """Отправляет сообщение "Запускаю колесо фортуны...".
    """
    # Отправка сообщения о запуске колеса фортуны из шаблона
    spinning_wheel_message = await get_template_or_default('spinning_wheel_message')
    await send_message(chat_id, spinning_wheel_message)
    await asyncio.sleep(3)


async def get_discount_message(client_data: ClientsData) -> str:
    """Возвращает сообщение с информацией о скидке или ошибке."""
    discount_data = await get_random_discount(client_data)
    if not discount_data:
        return await get_template_or_default('no_discounts_available')

    chosen_salon, is_priority = discount_data
    client_data.chosen_salon_id = chosen_salon.id
    client_data.chosen_salon_name = chosen_salon.name
    db.session.commit()

    # Формируем строку с категориями
    categories_str = ", ".join([category.name for category in chosen_salon.categories])

    if is_priority:
        #  Если салон приоритетный, сразу записываем данные в claimed_*
        # Сохраняем ID первого предложенного салона
        if client_data.attempts_left == 1:  # Только при первой попытке
            client_data.first_offered_salon_id = chosen_salon.id
            db.session.commit()
        await handle_claim_discount(client_data.chat_id, client_data)
        return await get_template_or_default(
            'get_discount_message',
            discount=chosen_salon.discount,
            salon_name=chosen_salon.name,
            contacts=chosen_salon.contacts,
            message_salon_name=chosen_salon.message_partner_name,
            categories=categories_str  # Передаем категории в шаблон
        )
    else:
        # Отправка предложения скидки из шаблона
        # Сохраняем ID первого предложенного салона
        if client_data.attempts_left == 1:  # Только при первой попытке
            client_data.first_offered_salon_id = chosen_salon.id
            db.session.commit()
        discount_offer_message = await get_template_or_default(
            'discount_offer',
            discount=chosen_salon.discount,
            salon_name=chosen_salon.name,
            attempts_left=client_data.attempts_left,
            message_salon_name=chosen_salon.message_partner_name,
            categories=categories_str  # Передаем категории в шаблон
        )
        return discount_offer_message

def update_partner_daily_stats(salon_id: str, field: str, increment: int = 1):
    """Обновляет ежедневную статистику партнера."""
    today = date.today()
    salon = PartnerInfo.query.get(salon_id)
    partner_id = Partner.query.join(partner_salons).filter(
        partner_salons.c.salon_id == salon_id
    ).first().id
    stats = PartnerDailyStats.query.filter_by(partner_id=partner_id, salon_id=salon_id, date=today).first()
    if stats:
        setattr(stats, field, getattr(stats, field) + increment)
    else:
        stats_data = {
            'partner_id': partner_id,
            'salon_id': salon_id,
            'date': today,
            field: increment
        }
        stats = PartnerDailyStats(**stats_data)
        db.session.add(stats)
    db.session.commit()

async def get_template_or_default(template_name: str, **kwargs) -> str:
    """Возвращает шаблон сообщения из базы данных или сообщение по умолчанию,
       если шаблон не найден.
    """
    template = MessageTemplate.query.filter_by(name=template_name).first()
    if template:

        return template.template.format(**kwargs)
    else:
        # Вернуть сообщение по умолчанию для данного шаблона
        return {
            'invalid_salon_id': "Неверный формат ID салона. ID должен состоять только из цифр.",
            'salon_not_found': "Салон с таким ID не найден.",
            'already_visited': "Вы уже получали скидку в этом салоне.",
            'welcome_back': "Рады видеть Вас снова!",
            'data_loading_error': "Ошибка при загрузке данных. Пожалуйста, начните сначала.",
            'spin_wheel_first': "Чтобы получить скидку, сначала нужно сыграть в колесо фортуны. Напишите 'Да', чтобы начать.",
            'user_declined': "Хорошо. ",
            'no_attempts_left': "😔 У вас больше нет попыток",
            'accept_terms': "Извините, но для участия в акции необходимо принять условия использования сервиса. Без этого мы не можем предоставить вам скидку. Пожалуйста, ознакомьтесь с условиями и дайте согласие, чтобы продолжить.",
            'no_discounts_available': "Извините, нет доступных скидок.",
            'spinning_wheel_message': " Запускаю колесо фортуны...",
            'get_discount_message': "✨ И вам выпадает {discount} в {message_salon_name} ({categories})! 🤩\n\n📞 Контакты: {contacts}",
            'claim_discount': "Поздравляем! В ближайшее время с Вами свяжется администратор из {message_salon_name}.\n\n Контактные данные: {contacts}",
            'discount_offer': "✨ И вам выпадает {discount} в {message_salon_name} ({categories})! 🤩\n\nХотите забрать подарок?\n\n1 - Да / 2 - Нет (осталось {attempts_left} попытка)",
            'general_error': "Произошла ошибка. Пожалуйста, попробуйте позже."
        }.get(template_name, "Произошла ошибка. Попробуйте позже.")
