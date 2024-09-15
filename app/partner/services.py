from collections import defaultdict
from datetime import timedelta, date

from app.models import ClientsData, ClientSalonStatus, Partner, PartnerInvitation, PartnerDailyStats


# Оптимизированная функция для получения данных из PartnerDailyStats
def get_data_from_partner_daily_stats(salon_id, field, period='month'):
    data = defaultdict(int)
    today = date.today()

    start_date, end_date = get_date_range(period, today)

    stats_data = PartnerDailyStats.query.filter(
        PartnerDailyStats.salon_id == salon_id,
        PartnerDailyStats.date >= start_date,
        PartnerDailyStats.date <= end_date
    ).all()

    for stats in stats_data:
        data[stats.date.strftime('%Y-%m-%d')] += getattr(stats, field)

    labels = sorted(data.keys())
    data = [data[label] for label in labels]

    return {'labels': labels, 'data': data}


def get_partners_invited_data(partner_id, period='month'):
    data = defaultdict(int)
    today = date.today()

    start_date, end_date = get_date_range(period, today)

    partner = Partner.query.get(partner_id)
    for invited_partner in partner.invited_partners:
        invitation_date = PartnerInvitation.query.filter_by(
            inviting_partner_id=partner.id, invited_partner_id=invited_partner.id
        ).first().invitation_date
        if start_date <= invitation_date <= end_date:
            data[invitation_date.strftime('%Y-%m-%d')] += 1

    labels = sorted(data.keys())
    data = [data[label] for label in labels]

    return {'labels': labels, 'data': data}


def get_referral_stats(partner_id):
    """Возвращает статистику по рефералам для партнера."""
    partner = Partner.query.get(partner_id)
    invited_partners_count = partner.partners_invited
    return {
        'invited_partners_count': invited_partners_count
    }


def get_total_clients_brought_by_referrals(partner_id):
    """Возвращает общее количество клиентов, приведенных всеми приглашенными партнерами."""
    partner = Partner.query.get(partner_id)
    total_clients_brought = 0
    for invited_partner in partner.invited_partners:
        total_clients_brought += invited_partner.clients_brought
    return total_clients_brought


# Функция для определения диапазона дат
def get_date_range(period, today):
    if period == 'week':
        end_date = today
        start_date = end_date - timedelta(days=6)
    elif period == 'month':
        end_date = today
        start_date = end_date - timedelta(days=30)
    elif period == 'year':
        end_date = today
        start_date = end_date - timedelta(days=364)
    else:
        start_date = end_date = today
    return start_date, end_date