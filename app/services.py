import asyncio
import logging
import os
from datetime import date
from typing import List, Optional

import json
import requests
import telegram

from app import db
from app.models import PartnerInfo, ClientsData, ClientSalonStatus, Category, Partner

async def send_message(chat_id: str, message: str) -> Optional[dict]:
    """Отправляет сообщение пользователю через WhatsApp API."""
    logging.info(f"Отправка сообщения на номер {chat_id}: {message}")
    data = {
        'to': chat_id,
        'body': message
    }
    headers = {
        'Authorization': f'Bearer {os.environ.get("WHAPI_API_KEY")}',
        'Content-Type': 'application/json'
    }
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(os.environ.get("WHAPI_BASE_URL"), json=data, headers=headers)
        )
        response.raise_for_status()
        logging.info(f"Ответ от WHAPI: {response.status_code} {response.text}")
        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при отправке сообщения: {e}")
        return None


async def create_amocrm_contact(client_data: ClientsData) -> Optional[int]:
    """Создает контакт в AmoCRM и возвращает его ID.
    Если контакт с таким номером уже существует, возвращается его ID.
    """
    existing_contact_id = await get_amocrm_contact_id(client_data.chat_id)
    if existing_contact_id:
        logging.info(f"Контакт с номером {client_data.chat_id} уже существует в AmoCRM, ID: {existing_contact_id}")
        return existing_contact_id

    url = f'https://{os.environ.get("AMOCRM_SUBDOMAIN")}.amocrm.ru/api/v4/contacts'
    headers = {
        'Authorization': f'Bearer {os.environ.get("AMOCRM_API_KEY")}',
        'Content-Type': 'application/json'
    }
    contact_data = {
        'name': client_data.client_name,
        'custom_fields_values': [
            {'field_id': 265455, 'values': [{'value': client_data.chat_id}]}
        ]
    }
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(url, headers=headers, json=[contact_data])
        )
        response.raise_for_status()
        response_data = response.json()
        contact_id = response_data['_embedded']['contacts'][0]['id']
        logging.info(f"Контакт успешно создан в AmoCRM, ID: {contact_id}")
        return contact_id
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при создании контакта в AmoCRM: {e}")
        return None


async def create_or_update_amocrm_lead(client_data: ClientsData, contact_id: int):
    """Создает или обновляет сделку в AmoCRM, привязанную к контакту."""
    url = f'https://{os.environ.get("AMOCRM_SUBDOMAIN")}.amocrm.ru/api/v4/leads'
    headers = {
        'Authorization': f'Bearer {os.environ.get("AMOCRM_API_KEY")}',
        'Content-Type': 'application/json'
    }

    # Получаем список сделок, привязанных к контакту
    contact_leads_url = f'https://{os.environ.get("AMOCRM_SUBDOMAIN")}.amocrm.ru/api/v4/contacts/{contact_id}/links'
    contact_leads_payload = {"to": "leads"}
    contact_leads_response = await asyncio.get_event_loop().run_in_executor(
        None, lambda: requests.get(contact_leads_url, headers=headers, json=contact_leads_payload)
    )

    if contact_leads_response.status_code == 200:
        contact_leads_data = contact_leads_response.json()
        lead_id = None
        for lead in contact_leads_data["_embedded"]["links"]:
            # Ищем сделку, относящуюся к текущему салону (по полю ID Салона)
            lead_url = f'https://{os.environ.get("AMOCRM_SUBDOMAIN")}.amocrm.ru/api/v4/leads/{lead["to_entity_id"]}'
            lead_response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.get(lead_url, headers=headers)
            )
            if lead_response.status_code == 200:
                lead_data = lead_response.json()
                for field in lead_data.get("custom_fields_values", []):
                    if field["field_id"] == 267157 and field["values"][0]["value"] == client_data.initial_salon_id:
                        lead_id = lead["to_entity_id"]
                        break
            if lead_id:  # Если нашли сделку, выходим из цикла
                break

        if lead_id:
            # Обновляем существующую сделку
            update_url = f'{url}/{lead_id}'
            lead_data = {
                'custom_fields_values': [
                    {'field_id': 267159, 'values': [{'value': client_data.claimed_salon_name}]},
                    {'field_id': 267161, 'values': [{'value': client_data.claimed_salon_id}]}
                ]
            }
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.patch(update_url, headers=headers, json=lead_data)
            )
            if response.status_code == 200 or response.status_code == 204:
                logging.info(f"Сделка успешно обновлена в AmoCRM, ID: {lead_id}")
            else:
                logging.error(f"Ошибка при обновлении сделки в AmoCRM: {response.status_code} {response.text}")
        else:
            # Создаем новую сделку, привязанную к контакту
            lead_data = {
                'name': 'Сделка из WhatsApp',
                '_embedded': {
                    'contacts': [{'id': contact_id}]
                },
                'custom_fields_values': [
                    {'field_id': 267155, 'values': [{'value': client_data.initial_salon_name}]},
                    {'field_id': 267157, 'values': [{'value': client_data.initial_salon_id}]},
                    {'field_id': 267159, 'values': [{'value': client_data.claimed_salon_name}]},
                    {'field_id': 267161, 'values': [{'value': client_data.claimed_salon_id}]},
                    {'field_id': 267163, 'values': [{'value': client_data.city}]}
                ]
            }
            response = await asyncio.get_event_loop().run_in_executor(
                None, lambda: requests.post(url, headers=headers, json=[lead_data])
            )
            if response.status_code == 200 or response.status_code == 204:
                logging.info(f"Сделка успешно создана и привязана к контакту в AmoCRM")
            else:
                logging.error(f"Ошибка при создании сделки в AmoCRM: {response.status_code} {response.text}")
    else:
        logging.error(
            f"Ошибка при получении списка сделок контакта: {contact_leads_response.status_code} {contact_leads_response.text}")


async def get_amocrm_contact_id(phone_number: str) -> Optional[int]:
    """Получает ID контакта из AmoCRM по номеру телефона."""
    url = f'https://{os.environ.get("AMOCRM_SUBDOMAIN")}.amocrm.ru/api/v4/contacts?query={phone_number}'
    headers = {
        'Authorization': f'Bearer {os.environ.get("AMOCRM_API_KEY")}'
    }
    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.get(url, headers=headers)
        )
        response.raise_for_status()
        data = response.json()
        if data['_embedded']['contacts']:
            return data['_embedded']['contacts'][0]['id']
        else:
            return None
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при получении ID контакта из AmoCRM: {e}")
        return None

async def create_partner_amocrm_contact(client_data: ClientsData, partner: Partner) -> Optional[int]:
    """Создает контакт в AmoCRM партнера и возвращает его ID."""

    url = f'https://{partner.amocrm_subdomain}.amocrm.ru/api/v4/contacts'
    headers = {
        'Authorization': f'Bearer {partner.amocrm_api_key}',
        'Content-Type': 'application/json'
    }

    # Используем partner.amocrm_field_mapping для определения ID полей
    contact_data = {
        'name': client_data.client_name,
        'custom_fields_values': []
    }


    # Преобразуем amocrm_field_mapping из строки JSON в словарь
    try:
        amocrm_field_mapping = json.loads(partner.amocrm_field_mapping)
    except json.JSONDecodeError as e:
        return None


    # Получаем amocrm_contacts_fields из строки JSON
    try:
        amocrm_contacts_fields = json.loads(partner.amocrm_contacts_fields)
    except json.JSONDecodeError as e:
        return None
        
    for field_name, amocrm_field_id in amocrm_field_mapping.items():
        # Получаем значение value по имени поля sarafan_field_name
        value = getattr(client_data, field_name, None)
        
        if value is not None:

            # Используем sarafan_field_name (ID поля AmoCRM) как ключ
            if amocrm_field_id in amocrm_contacts_fields: 
                contact_data['custom_fields_values'].append({
                    'field_id': int(amocrm_field_id),
                    'values': [{'value': value}]
                })

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(url, headers=headers, json=[contact_data])
        )
        response.raise_for_status()
        response_data = response.json()
        contact_id = response_data['_embedded']['contacts'][0]['id']
        return contact_id
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при создании контакта в AmoCRM партнера: {e}")
        return None


async def create_or_update_partner_amocrm_lead(client_data: ClientsData, contact_id: int, partner: Partner, chosen_salon: PartnerInfo):
    """Создает или обновляет сделку в AmoCRM партнера, привязанную к контакту."""
    url = f'https://{partner.amocrm_subdomain}.amocrm.ru/api/v4/leads'
    headers = {
        'Authorization': f'Bearer {partner.amocrm_api_key}',
        'Content-Type': 'application/json'
    }

    # Преобразуем amocrm_settings из строки JSON в словарь
    amocrm_settings = json.loads(partner.amocrm_settings)

    # Создаем новую сделку, привязанную к контакту
    lead_data = {
        'name': 'Лид из Сарафан',
        '_embedded': {
            'contacts': [{'id': contact_id}]
        },
        'custom_fields_values': [],
        'pipeline_id': int(amocrm_settings.get('pipeline_id')),
        'status_id': int(amocrm_settings.get('stage_id'))
    }

    # Преобразуем amocrm_field_mapping из строки JSON в словарь
    amocrm_field_mapping = json.loads(partner.amocrm_field_mapping)
    amocrm_leads_fields = json.loads(partner.amocrm_leads_fields)

    # Исправленный цикл
    for sarafan_field_name, amocrm_field_id in amocrm_field_mapping.items():
        if sarafan_field_name == 'city':
            value = client_data.city
        else:
            value = getattr(client_data, sarafan_field_name, None)

        if value is not None:
            # Проверяем, относится ли поле к сделке
            if str(amocrm_field_id) in amocrm_leads_fields:
                lead_data['custom_fields_values'].append({
                    'field_id': int(amocrm_field_id),
                    'values': [{'value': value}]
                })

    try:
        response = await asyncio.get_event_loop().run_in_executor(
            None, lambda: requests.post(url, headers=headers, json=[lead_data])
        )
        response.raise_for_status()
        logging.info(f"Сделка успешно создана в AmoCRM партнера")
    except requests.exceptions.RequestException as e:
        logging.error(f"Ошибка при создании сделки в AmoCRM партнера: {e}")
                   

async def set_salon_status(client_id: int, salon_id: str, status: str):
    """Устанавливает статус салона для клиента."""
    existing_status = ClientSalonStatus.query.filter_by(client_id=client_id, salon_id=salon_id).first()
    if existing_status:
        existing_status.status = status
    else:
        new_status = ClientSalonStatus(client_id=client_id, salon_id=salon_id, status=status, date=date.today())
        db.session.add(new_status)
    db.session.commit()


async def get_salon_status(client_id: int, salon_id: str) -> Optional[str]:
    """Возвращает статус салона для клиента."""
    status = ClientSalonStatus.query.filter_by(client_id=client_id, salon_id=salon_id).first()
    return status.status if status else None


async def send_telegram_notification(chat_id: int, message: str) -> Optional[bool]:
    """Отправляет сообщение в Telegram в личный чат и подключенную группу партнера."""

    logging.info(f"Отправка сообщения в Telegram на ID чата {chat_id}: {message}")
    bot = telegram.Bot(token=os.environ.get("TELEGRAM_BOT_TOKEN"))

    try:
        # Отправка сообщения партнеру
        await bot.send_message(chat_id=chat_id, text=message)

        # Получение ID группы партнера
        partner = Partner.query.filter_by(telegram_chat_id=chat_id).first()
        group_id = partner.telegram_group_id if partner else None

        # Отправка сообщения в группу, если она подключена
        if group_id:
            await bot.send_message(chat_id=group_id, text=message)

        logging.info("Сообщение успешно отправлено в Telegram.")
        return True

    except telegram.error.TelegramError as e:
        logging.error(f"Ошибка при отправке сообщения в Telegram: {e}")
        return False