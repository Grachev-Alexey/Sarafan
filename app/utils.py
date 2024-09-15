import logging
import random
from typing import List, Optional, Tuple

from app.models import Partner, PartnerInfo, ClientsData, DiscountWeightSettings, Category, partner_salons


async def get_random_discount(client_data: ClientsData) -> Optional[Tuple[PartnerInfo, bool]]:
    """
    Возвращает случайную скидку, исключая:
     - категорию салона пользователя,
     - посещенные салоны,
     - салоны, от которых пользователь отказался,
     - все салоны партнеров, с которыми взаимодействовал клиент, включая изначальный салон.
    Учитывает приоритет салонов, соотношение "привел/получил" и количество приглашенных партнеров салоном.
    В первую очередь проверяет наличие приоритетного салона для этого города,
    затем наличие связанного салона.
    """
    logging.info(
        f"Получение случайной скидки с учетом связанного салона, приоритета, истории посещений, соотношения клиентов и приглашенных партнеров самим салоном")

    user_salon_id = client_data.initial_salon_id
    user_salon = PartnerInfo.query.get(user_salon_id)
    user_salon_city_id = user_salon.city_id

    # --- Собираем ID всех партнеров, с которыми взаимодействовал клиент ---
    interacted_partner_ids = set()
    for status in client_data.salon_statuses:
        salon = PartnerInfo.query.get(status.salon_id)
        if salon:
            for partner in salon.partners:
                interacted_partner_ids.add(partner.id)

    # --- Исключаем салоны всех взаимодействовавших партнеров ---
    excluded_salon_ids = [status.salon_id for status in client_data.salon_statuses.all()]
    for partner_id in interacted_partner_ids:
        partner = Partner.query.get(partner_id)
        if partner:
            excluded_salon_ids.extend([salon.id for salon in partner.salons])

    # --- Получаем список ID всех категорий, с которыми взаимодействовал клиент ---
    excluded_category_ids = list({
        category.id
        for salon_id in excluded_salon_ids
        for category in PartnerInfo.query.get(salon_id).categories
    })

    # --- 1. Приоритетный салон в том же городе ---
    priority_salons_city = PartnerInfo.query.filter(
        PartnerInfo.city_id == user_salon_city_id,
        ~PartnerInfo.id.in_(excluded_salon_ids),
        ~PartnerInfo.categories.any(Category.id.in_(excluded_category_ids)),
        PartnerInfo.priority == True
    ).all()

    if priority_salons_city:
        chosen_salon = random.choice(priority_salons_city)
        logging.info(f"Найден приоритетный салон в городе клиента: {chosen_salon.name}")
        return chosen_salon, True

    # --- 2. Связанный салон ---
    if user_salon.linked_partner_id and user_salon.linked_partner_id not in excluded_salon_ids:
        linked_salon = PartnerInfo.query.get(user_salon.linked_partner_id)
        if linked_salon and not any(category.id in excluded_category_ids for category in linked_salon.categories):
            logging.info(f"Найден связанный салон: {linked_salon.name}")
            return linked_salon, False

    # --- 3. Приоритетные салоны в любом городе ---
    priority_salons = PartnerInfo.query.filter(
        ~PartnerInfo.id.in_(excluded_salon_ids),
        ~PartnerInfo.categories.any(Category.id.in_(excluded_category_ids)),
        PartnerInfo.priority == True
    ).all()

    if priority_salons:
        chosen_salon = random.choice(priority_salons)
        return chosen_salon, True

    # --- 4. Доступные салоны с учетом города (только город клиента), весов и активности партнера ---
    available_salons = PartnerInfo.query.join(
        partner_salons, PartnerInfo.id == partner_salons.c.salon_id
    ).join(Partner, partner_salons.c.partner_id == Partner.id).filter(
        PartnerInfo.city_id == user_salon_city_id,  # Фильтр по городу клиента
        ~PartnerInfo.id.in_(excluded_salon_ids),
        ~PartnerInfo.categories.any(Category.id.in_(excluded_category_ids)),
        Partner.is_active == True
    ).all()

    if not available_salons:
        logging.error(f"Не удалось найти доступные салоны в городе клиента, кроме взаимодействовавших с клиентом")
        return None

    # --- Получаем настройки весов ---
    weight_settings = DiscountWeightSettings.query.get(1)
    if not weight_settings:
        logging.error("Настройки весов не найдены!")
        return None

    weighted_salons: List[PartnerInfo] = []
    for salon in available_salons:
        # --- Ratio с обработкой деления на ноль ---
        ratio = salon.clients_brought / salon.clients_received if salon.clients_received > 0 else float('inf')

        if ratio >= 1.5:
            weight = weight_settings.ratio_40_80_weight
        elif 1.1 <= ratio < 1.5:
            weight = weight_settings.ratio_30_40_weight
        else:
            weight = weight_settings.ratio_below_30_weight

        # --- Увеличиваем вес в зависимости от количества приглашенных партнеров ---
        partner = Partner.query.join(partner_salons).filter(partner_salons.c.salon_id == salon.id).first()
        if partner:
            weight += partner.partners_invited * weight_settings.partners_invited_weight

        weighted_salons.extend([salon] * weight)

    if weighted_salons:
        chosen_salon = random.choice(weighted_salons)
        return chosen_salon, False
    else:
        logging.error(f"Не удалось найти доступные салоны с учетом соотношения клиентов")
        return None