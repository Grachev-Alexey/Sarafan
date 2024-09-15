import asyncio
import base64
import io
import os
import logging
import random
import string
import requests
from datetime import date, datetime
from collections import defaultdict
from typing import Optional, Dict
from flask import render_template, redirect, url_for, flash, request, send_file, jsonify, session
from flask_login import login_user, logout_user, login_required, current_user
import json
from app import db
from app.models import Partner, PartnerInfo, User, PartnerInvitation, MessageTemplate, ClientSalonStatus, ClientsData, \
    FAQ, PartnerFAQStatus, PartnerAction, Tip, News, PartnerDailyStats
from app.partner import bp
from app.partner.forms import RegistrationForm, LoginForm, EditSalonForm, ResetPasswordForm, EditUserForm, AddSalonForm
from app.partner.services import (
    get_referral_stats,
    get_total_clients_brought_by_referrals,
    get_data_from_partner_daily_stats,
    get_partners_invited_data
)
from app.admin.routes import log_admin_action
from app.qr_code import generate_qr_code
from app.routes import get_template_or_default
from app.services import send_message, send_telegram_notification, create_or_update_partner_amocrm_lead, create_partner_amocrm_contact

def escape_handlebars_braces(text):
    text = text.replace('{', '{{')
    text = text.replace('}', '}}')
    return text


@bp.route('/login', methods=['GET', 'POST'])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.login.data).first()
        if user and user.check_password(form.password.data):
            login_user(user)
            flash('Вы вошли в систему!', 'success')
            return redirect(url_for('partner.dashboard'))
        else:
            flash('Неверный логин или пароль.', 'danger')
    return render_template('partner/login.html', form=form)


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Вы вышли из системы.', 'info')
    return redirect(url_for('partner.login'))


@bp.route('/')
def index():
    return redirect(url_for('partner.dashboard'))

@bp.route('/stop_impersonating')
def stop_impersonating():
    impersonated_user_id = session.pop('impersonated_user_id', None)
    if impersonated_user_id:
        logout_user()
        admin = User.query.filter_by(username='admin').first() # Получаем пользователя администратора
        login_user(admin) # Авторизуем администратора
        log_admin_action(f'Администратор {current_user.username} вышел из режима редактирования партнера')
        flash('Вы вернулись в админку.', 'success')
    return redirect(url_for('admin.partners'))

def generate_unique_code(length=8):
    """Генерирует уникальный код заданной длины, проверяя его уникальность в базе данных."""
    while True:
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))
        if not Partner.query.filter_by(unique_code=code).first():
            return code


@bp.route('/register', methods=['GET', 'POST'])
def register():
    form = RegistrationForm()
    ref_id = request.args.get('ref')
    if form.validate_on_submit():
        existing_user = User.query.filter_by(username=form.login.data).first()
        if existing_user:
            flash('Пользователь с таким номером телефона уже зарегистрирован.', 'danger')
            return render_template('partner/register.html', form=form)

        try:
            partner_id = generate_unique_salon_id(form.city.data.name)
            new_user = User(username=form.login.data)
            new_user.set_password(form.password.data)
            db.session.add(new_user)
            db.session.flush()
            new_partner_info = PartnerInfo(
                id=partner_id,
                partner_type=form.partner_type.data,
                categories=form.categories.data,
                name=form.salon_name.data,
                discount=form.discount_text.data,
                city_id=form.city.data.id,
                contacts=form.contacts.data,
                message_partner_name=form.message_salon_name.data
            )
            db.session.add(new_partner_info)
            db.session.flush()
            db.session.commit()
            unique_code = generate_unique_code()
            new_partner = Partner(
                user_id=new_user.id,
                referral_link=f"https://sarafan.club/partner-register/?ref={new_user.id}",
                unique_code=unique_code
            )
            new_partner.salons.append(new_partner_info)
            db.session.add(new_partner)
            db.session.commit()
            login_user(new_user)
            if ref_id:
                inviting_partner = Partner.query.filter_by(user_id=ref_id).first()
                if inviting_partner:
                    new_partner_info.invited_by = inviting_partner.id
                    inviting_partner.partners_invited += 1
                    new_invitation = PartnerInvitation(inviting_partner_id=inviting_partner.id,
                                                       invited_partner_id=new_partner.id, invitation_date=date.today())
                    db.session.add(new_invitation)
                    db.session.commit()
            log_partner_action(new_partner.id, 'registration')
            flash(f'Регистрация прошла успешно! Ознакомьтесь с FAQ.', 'success')

            # Отправка уведомления администраторам
            admin = User.query.filter_by(username='admin').first()
            if admin and admin.telegram_chat_ids:
                for chat_id in admin.telegram_chat_ids:
                    message = f"🎉 Новый партнер зарегистрировался!\n\nНомер телефона: {new_user.username}\n\nНазвание салона: {new_partner_info.name}\n\nID: {new_partner_info.id}"
                    asyncio.run(send_telegram_notification(chat_id, message))

            return redirect(url_for('partner.faq'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при регистрации: {e}', 'danger')
            return render_template('partner/register.html', form=form)
    return render_template('partner/register.html', form=form)


def generate_unique_salon_id(city_name):
    while True:
        city_letter = city_name[0].lower()
        salon_id = f"{city_letter}{random.randint(100000, 999999)}"
        existing_salon = PartnerInfo.query.get(salon_id)
        if not existing_salon:
            return salon_id


@bp.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    # Получение данных для графиков (для первого салона по умолчанию)
    selected_salon_id = request.args.get('salon_id', partner.salons[0].id if partner.salons else None)
    period = request.args.get('period', 'month')

    total_clients_brought = partner.clients_brought
    total_clients_received = partner.clients_received
    total_partners_invited = partner.partners_invited
    # Получение данных о показах и отказах для всех салонов партнера
    total_offers_shown = 0
    total_offers_rejected = 0
    for salon in partner.salons:
        total_offers_shown += db.session.query(db.func.sum(PartnerDailyStats.offers_shown)).filter(PartnerDailyStats.salon_id == salon.id).scalar() or 0
        total_offers_rejected += db.session.query(db.func.sum(PartnerDailyStats.offers_rejected)).filter(PartnerDailyStats.salon_id == salon.id).scalar() or 0    
    
    # Проверяем, есть ли у партнера салоны
    if not partner.salons:
        flash('У вас нет салонов. Добавьте салон, чтобы продолжить.', 'danger')
        return redirect(url_for('partner.settings'))

    # Оптимизированная функция для получения данных для графиков
    def get_chart_data(chart_type, salon_id, period='month'):
        if chart_type == 'clients_brought':
            return get_data_from_partner_daily_stats(salon_id, 'clients_brought', period)
        elif chart_type == 'offers_shown':
            return get_data_from_partner_daily_stats(salon_id, 'offers_shown', period)
        elif chart_type == 'offers_accepted':
            return get_data_from_partner_daily_stats(salon_id, 'offers_accepted', period)
        elif chart_type == 'offers_rejected':
            return get_data_from_partner_daily_stats(salon_id, 'offers_rejected', period)
        elif chart_type == 'partners_invited':
            return get_partners_invited_data(partner.id, period)
        else:
            return {'labels': [], 'data': []}

    # Получение данных для графиков
    clients_brought_data = get_chart_data('clients_brought', selected_salon_id, period)
    offers_shown_data = get_chart_data('offers_shown', selected_salon_id, period)
    offers_accepted_data = get_chart_data('offers_accepted', selected_salon_id, period)
    offers_rejected_data = get_chart_data('offers_rejected', selected_salon_id, period)
    partners_invited_data = get_chart_data('partners_invited', selected_salon_id, period)

    def get_last_actions(partner_id):
        actions = []
        for salon in partner.salons:
            actions.extend(get_last_actions_for_salon(partner_id, salon.id))
        actions.extend(get_last_actions_for_partner(partner_id))
        actions.sort(key=lambda x: datetime.strptime(x.split(' - ')[-2], '%d-%m-%Y'), reverse=True) 
        return actions[:5]  # Возвращаем не более 5 последних действий

    def get_last_actions_for_salon(partner_id, salon_id):
        actions = []
        clients = ClientsData.query.filter_by(initial_salon_id=salon_id).order_by(
            ClientsData.date.desc()).all()
        for client in clients:
            salon = PartnerInfo.query.get(client.initial_salon_id)
            salon_name = salon.name if salon else 'Неизвестный салон'
            actions.append(
                f"Приведен клиент {client.client_name} ({client.chat_id}) - {client.date.strftime('%d-%m-%Y')} - {salon_name}")
        client_statuses = ClientSalonStatus.query.filter_by(salon_id=salon_id, status='claimed').order_by(
            ClientSalonStatus.date.desc()).all()
        for client_status in client_statuses:
            salon = PartnerInfo.query.get(client_status.salon_id)
            client = ClientsData.query.get(client_status.client_id)
            salon_name = salon.name if salon else 'Неизвестный салон'
            actions.append(
                f"Получен клиент {client.client_name} ({client.chat_id}) - {client_status.date.strftime('%d-%m-%Y')} - {salon_name}")
        return actions

    def get_last_actions_for_partner(partner_id):
        actions = []
        invitations = PartnerInvitation.query.filter_by(inviting_partner_id=partner_id).order_by(
            PartnerInvitation.invitation_date.desc()).limit(5).all()
        for invitation in invitations:
            invited_partner = Partner.query.get(invitation.invited_partner_id)
            actions.append(
                f"Приглашен партнер {invited_partner.salons[0].name if invited_partner.salons else '-'} ({invited_partner.salons[0].id if invited_partner.salons else '-'}) - {invitation.invitation_date.strftime('%d-%m-%Y')} - ")
        return actions

    last_actions = get_last_actions(partner.id) # <- Получаем действия для всех салонов
    tips_and_tricks = Tip.query.filter_by(is_active=True).all()
    news_and_updates = News.query.filter_by(is_active=True).all()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'clients_brought_data': clients_brought_data,
            'clients_received_data': offers_accepted_data,
            'offers_shown_data': offers_shown_data,
            'offers_accepted_data': offers_accepted_data,
            'offers_rejected_data': offers_rejected_data,
            'partners_invited_data': partners_invited_data
        })

    return render_template('partner/dashboard.html',
                           partner=partner,
                           selected_salon_id=selected_salon_id,
                           period=period,
                           clients_brought_data=clients_brought_data,
                           clients_received_data=offers_accepted_data,
                           offers_shown_data=offers_shown_data,
                           offers_accepted_data=offers_accepted_data,
                           offers_rejected_data=offers_rejected_data,
                           partners_invited_data=partners_invited_data,
                           last_actions=last_actions, # <- Передаем действия в шаблон
                           tips_and_tricks=tips_and_tricks,
                           news_and_updates=news_and_updates,                      
                           total_clients_brought=total_clients_brought,
                           total_clients_received=total_clients_received,
                           total_offers_shown=total_offers_shown,
                           total_offers_rejected=total_offers_rejected,
                           total_partners_invited=total_partners_invited
                           )


@bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    # Выбираем первый салон партнера, если он есть
    selected_salon_id = request.args.get('salon_id', partner.salons[0].id if partner.salons else None)
    salon = PartnerInfo.query.get(selected_salon_id) if selected_salon_id else None

    if not salon and partner.salons:
        flash('У вас нет салонов. Добавьте салон, чтобы продолжить.', 'danger')
        return redirect(url_for('partner.settings'))

    edit_form = EditSalonForm(obj=salon)
    if edit_form.validate_on_submit() and request.method == 'POST':
        edit_form.populate_obj(salon)
        salon.name = edit_form.salon_name.data
        salon.message_partner_name = edit_form.message_salon_name.data
        salon.city_id = edit_form.city.data.id
        salon.categories = edit_form.categories.data
        db.session.commit()
        flash('Данные партнера успешно обновлены!', 'success')
        return redirect(url_for('partner.settings'))

    sample_messages = {}
    if salon:
        for template_name in ['spinning_wheel_message', 'discount_offer', 'claim_discount']:
            sample_messages[template_name] = asyncio.run(get_template_or_default(
                template_name,
                discount=salon.discount,
                salon_name=salon.name,
                contacts=salon.contacts,
                message_salon_name=salon.message_partner_name,
                categories=", ".join([category.name for category in salon.categories]),
                attempts_left=1
            ))
            
        spinning_wheel_message_template = escape_handlebars_braces(
            MessageTemplate.query.filter_by(name='spinning_wheel_message').first().template).replace('\n', '\\n')
        discount_offer_template = escape_handlebars_braces(
            MessageTemplate.query.filter_by(name='discount_offer').first().template).replace('\n', '\\n')
        claim_discount_template = escape_handlebars_braces(
            MessageTemplate.query.filter_by(name='claim_discount').first().template).replace('\n', '\\n')

        # Генерация QR-кода для WhatsApp
        qr_code_data_whatsapp = f"https://wa.me/79933062088?text=Получить подарок ({salon.id})"
        qr_code_image_whatsapp = generate_qr_code(qr_code_data_whatsapp)
        qr_code_image_base64_whatsapp = base64.b64encode(qr_code_image_whatsapp).decode('utf-8')

    # Генерация QR-кода для Telegram
    qr_code_data_telegram = f"https://t.me/{os.environ.get('TELEGRAM_BOT_USERNAME')}?start={partner.unique_code}"
    qr_code_image_telegram = generate_qr_code(qr_code_data_telegram)
    qr_code_image_base64_telegram = base64.b64encode(qr_code_image_telegram).decode('utf-8')

    # Преобразуем строки, содержащие данные AmoCRM, в словари Python
    amocrm_contacts_fields = json.loads(partner.amocrm_contacts_fields) if partner.amocrm_contacts_fields else {}
    amocrm_leads_fields = json.loads(partner.amocrm_leads_fields) if partner.amocrm_leads_fields else {}
    amocrm_pipelines = json.loads(partner.amocrm_pipelines) if partner.amocrm_pipelines else {}
    amocrm_field_mapping = json.loads(partner.amocrm_field_mapping) if partner.amocrm_field_mapping else {}
    amocrm_settings = json.loads(partner.amocrm_settings) if partner.amocrm_settings else {}

    return render_template('partner/settings.html',
                           partner=partner,
                           salon=salon,
                           edit_form=edit_form,
                           PartnerInfo=PartnerInfo,
                           sample_messages=sample_messages,
                           spinning_wheel_message_template=spinning_wheel_message_template,
                           discount_offer_template=discount_offer_template,
                           claim_discount_template=claim_discount_template,
                           qr_code_image_base64_whatsapp=qr_code_image_base64_whatsapp,
                           qr_code_image_base64_telegram=qr_code_image_base64_telegram,
                           telegram_chat_id=partner.telegram_chat_id,
                           selected_salon_id=selected_salon_id,
                           amocrm_contacts_fields=amocrm_contacts_fields,
                           amocrm_leads_fields=amocrm_leads_fields,
                           amocrm_pipelines=amocrm_pipelines,
                           amocrm_field_mapping=amocrm_field_mapping, 
                           amocrm_settings=amocrm_settings
                           )


@bp.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    form = EditUserForm(obj=current_user)
    if form.validate_on_submit():
        # Проверяем, не пытается ли пользователь изменить номер на уже существующий
        existing_user = User.query.filter_by(username=form.username.data).first()
        if existing_user and existing_user.id != current_user.id:
            flash('Пользователь с таким номером телефона уже зарегистрирован.', 'danger')
            return render_template('partner/profile.html', form=form)

        current_user.username = form.username.data
        db.session.commit()
        flash('Данные профиля успешно обновлены!', 'success')
        return redirect(url_for('partner.profile'))
    return render_template('partner/profile.html', form=form)


@bp.route('/referrals')
@login_required
def referrals():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))
    referral_stats = get_referral_stats(partner.id)
    total_clients_brought = get_total_clients_brought_by_referrals(partner.id)
    return render_template('partner/referrals.html',
                           partner=partner,
                           referral_stats=referral_stats,
                           total_clients_brought=total_clients_brought)


@bp.route('/qr_code_whatsapp/<salon_id>')
@login_required
def qr_code_whatsapp(salon_id):
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    salon = PartnerInfo.query.get_or_404(salon_id)
    if salon not in partner.salons:
        flash('У вас нет доступа к этому салону.', 'danger')
        return redirect(url_for('partner.dashboard'))

    data = f"https://wa.me/79933062088?text=Получить подарок ({salon.id})"
    img = generate_qr_code(data)
    return send_file(
        io.BytesIO(img),
        mimetype='image/png',
        as_attachment=True,
        download_name=f'qr_code_whatsapp_{salon.id}.png'
    )


@bp.route('/detailed_stats/<stat_type>')
@login_required
def detailed_stats(stat_type):
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    if stat_type == 'brought':
        clients = ClientsData.query.filter(ClientsData.initial_salon_id.in_([salon.id for salon in partner.salons])).all()
    elif stat_type == 'received':
        clients = ClientsData.query.filter(ClientsData.claimed_salon_id.in_([salon.id for salon in partner.salons])).all()
    elif stat_type == 'invited':
        clients = partner.invited_partners.all()
    else:
        flash('Неверный тип статистики.', 'danger')
        return redirect(url_for('partner.dashboard'))

    return render_template('partner/detailed_stats.html',
                           stat_type=stat_type,
                           clients=clients,
                           PartnerInvitation=PartnerInvitation)


@bp.route('/faq')
@login_required
def faq():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))
    faqs = FAQ.query.all()
    return render_template('partner/faq.html', faqs=faqs, partner=partner)


@bp.route('/faq/confirm', methods=['POST'])
@login_required
def confirm_faq():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))
    if not partner.faq_status:
        partner.faq_status = PartnerFAQStatus(has_read_faq=True)
    else:
        partner.faq_status.has_read_faq = True
    db.session.commit()
    flash('Вы подтвердили ознакомление с FAQ.', 'success')
    return redirect(url_for('partner.dashboard'))


@bp.route('/reset_password', methods=['GET', 'POST'])
async def reset_password():  # async перед def
    if current_user.is_authenticated:
        return redirect(url_for('partner.dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form['login']).first()
        if user:
            # Генерация токена для сброса пароля
            token = user.get_reset_password_token()
            # Отправка ссылки для сброса пароля в WhatsApp
            reset_link = url_for('partner.reset_password_with_token', token=token, _external=True)
            message = f'Чтобы сбросить пароль, перейдите по ссылке: {reset_link}'
            await send_message(user.username, message)  # await перед send_message
            flash('Инструкции по сбросу пароля отправлены в WhatsApp.', 'info')
            return redirect(url_for('partner.login'))
        else:
            flash('Пользователь с таким логином не найден.', 'danger')
    return render_template('partner/reset_password.html')


@bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_with_token(token):
    if current_user.is_authenticated:
        return redirect(url_for('partner.dashboard'))
    user = User.verify_reset_password_token(token)
    if not user:
        flash('Неверный или устаревший токен.', 'danger')
        return redirect(url_for('partner.reset_password'))
    form = ResetPasswordForm()
    if form.validate_on_submit():
        user.set_password(form.password.data)
        db.session.commit()
        flash('Ваш пароль успешно изменен!', 'success')
        return redirect(url_for('partner.login'))
    return render_template('partner/reset_password_with_token.html', form=form)


def log_partner_action(partner_id, action_type, details=None):
    action = PartnerAction(partner_id=partner_id, action_type=action_type, details=details)
    db.session.add(action)
    db.session.commit()


@bp.route('/invite_partner', methods=['POST'])
@login_required
def invite_partner():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    phone_number = request.form.get('phone_number')
    salon_name = request.form.get('salon_name')

    if not phone_number or not salon_name:
        flash('Необходимо указать номер телефона и название салона.', 'danger')
        return redirect(url_for('partner.referrals'))

    # Отправка приглашения через WhatsApp
    message = f"Привет! Присоединяйтесь к сервису «Сарафан»! {partner.salons[0].name if partner.salons else ''} приглашает вас стать партнером. Перейдите по ссылке: {partner.referral_link}"
    asyncio.run(send_message(phone_number, message))

    flash('Приглашение успешно отправлено!', 'success')
    return redirect(url_for('partner.referrals'))

@bp.route('/salons/<salon_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_salon(salon_id):
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    salon = PartnerInfo.query.get_or_404(salon_id)

    if salon not in partner.salons:
        flash('У вас нет доступа к этому салону.', 'danger')
        return redirect(url_for('partner.dashboard'))

    form = EditSalonForm(obj=salon)
    if form.validate_on_submit():
        salon.name = form.salon_name.data
        salon.partner_type = form.partner_type.data
        salon.categories = form.categories.data
        salon.city_id = form.city.data.id
        salon.discount = form.discount.data
        salon.contacts = form.contacts.data
        salon.message_partner_name = form.message_salon_name.data
        db.session.commit()
        flash('Данные салона успешно обновлены!', 'success')
        return redirect(url_for('partner.settings', salon_id=salon.id))

    return render_template('partner/edit_salon.html', form=form, salon=salon)

@bp.route('/salons/<salon_id>/delete', methods=['POST'])
@login_required
def delete_salon(salon_id):
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    salon = PartnerInfo.query.get_or_404(salon_id)

    # Проверяем, принадлежит ли салон текущему партнеру
    if salon not in partner.salons:
        flash('У вас нет доступа к этому салону.', 'danger')
        return redirect(url_for('partner.dashboard'))

    try:
        partner.salons.remove(salon)
        # Если у салона больше нет партнеров, удаляем его
        if not salon.partners:
            db.session.delete(salon)
        db.session.commit()
        flash('Салон успешно удален!', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка при удалении салона: {e}', 'danger')

    return redirect(url_for('partner.settings'))

@bp.route('/salon_stats/<salon_id>')
@login_required
def salon_stats(salon_id):
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        return jsonify({'error': 'Partner not found'}), 404

    salon = PartnerInfo.query.get_or_404(salon_id)
    if salon not in partner.salons:
        return jsonify({'error': 'Access denied'}), 403

    period = request.args.get('period', 'month')

    # Используем функции для получения статистики из PartnerDailyStats
    clients_brought_data = get_data_from_partner_daily_stats(salon_id, 'clients_brought', period)
    offers_shown_data = get_data_from_partner_daily_stats(salon_id, 'offers_shown', period)
    offers_accepted_data = get_data_from_partner_daily_stats(salon_id, 'offers_accepted', period)
    offers_rejected_data = get_data_from_partner_daily_stats(salon_id, 'offers_rejected', period)
    partners_invited_data = get_partners_invited_data(partner.id, period)

    return jsonify({
        'clients_brought_data': clients_brought_data,
        'offers_shown_data': offers_shown_data,
        'offers_accepted_data': offers_accepted_data,
        'offers_rejected_data': offers_rejected_data,
        'partners_invited_data': partners_invited_data
    })

@bp.route('/salons/create', methods=['GET', 'POST'])
@login_required
def create_salon():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    form = AddSalonForm()
    if form.validate_on_submit():
        try:
            partner_id = generate_unique_salon_id(form.city.data.name)
            new_salon = PartnerInfo(
                id=partner_id,
                partner_type=form.partner_type.data,
                categories=form.categories.data,
                name=form.salon_name.data,
                discount=form.discount_text.data,
                city_id=form.city.data.id,
                contacts=form.contacts.data,
                message_partner_name=form.message_salon_name.data
            )
            db.session.add(new_salon)
            partner.salons.append(new_salon)
            db.session.commit()
            flash('Салон успешно добавлен!', 'success')
            return redirect(url_for('partner.settings'))
        except Exception as e:
            db.session.rollback()
            flash(f'Ошибка при добавлении салона: {e}', 'danger')

    return render_template('partner/create_salon.html', form=form)

@bp.route('/disable_telegram_notifications', methods=['POST'])
@login_required
def disable_telegram_notifications():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    partner.telegram_chat_id = None
    db.session.commit()
    flash('Telegram-уведомления отключены.', 'success')
    return redirect(url_for('partner.settings'))
    
@bp.route('/amocrm/connect', methods=['POST'])
@login_required
def connect_amocrm():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    subdomain = request.form.get('subdomain')
    api_key = request.form.get('api_key')

    # Проверка подлинности данных
    try:
        url = f'https://{subdomain}.amocrm.ru/api/v4/account'
        headers = {'Authorization': f'Bearer {api_key}'}
        response = requests.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        flash(f'Ошибка при подключении к AmoCRM: {e}', 'danger')
        return redirect(url_for('partner.settings'))

    # Получение данных о полях, воронках и этапах
    try:
        account_info = get_amocrm_account_info(subdomain, api_key)
        contacts_fields = get_amocrm_fields(subdomain, api_key, 'contacts')
        leads_fields = get_amocrm_fields(subdomain, api_key, 'leads')
        pipelines = get_amocrm_pipelines(subdomain, api_key)

        # Добавляем этапы к информации о воронках
        for pipeline in pipelines['_embedded']['pipelines']:
            pipeline['stages'] = get_amocrm_pipeline_stages(subdomain, api_key, pipeline['id'])

        partner.amocrm_subdomain = subdomain
        partner.amocrm_api_key = api_key
        partner.amocrm_account_info = json.dumps(account_info)
        partner.amocrm_contacts_fields = json.dumps(contacts_fields)
        partner.amocrm_leads_fields = json.dumps(leads_fields)
        partner.amocrm_pipelines = json.dumps(pipelines)
        db.session.commit()

    except requests.exceptions.RequestException as e:
        flash(f'Ошибка при получении данных из AmoCRM: {e}', 'danger')
        return redirect(url_for('partner.settings'))

    flash('Подключение к AmoCRM успешно выполнено!', 'success')
    return redirect(url_for('partner.settings', tab='integrationsSettings'))


@bp.route('/amocrm/disconnect', methods=['POST'])
@login_required
def disconnect_amocrm():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    partner.amocrm_subdomain = None
    partner.amocrm_api_key = None
    partner.amocrm_account_info = None
    partner.amocrm_contacts_fields = None
    partner.amocrm_leads_fields = None
    partner.amocrm_pipelines = None
    partner.amocrm_field_mapping = None
    partner.amocrm_settings = None
    db.session.commit()

    flash('AmoCRM отключен.', 'success')
    return redirect(url_for('partner.settings'))


@bp.route('/amocrm/save_field_mapping', methods=['POST'])
@login_required
def save_amocrm_field_mapping():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        flash('Вы не зарегистрированы как партнер.', 'danger')
        return redirect(url_for('partner.register'))

    amocrm_field_mapping = {}
    for key, value in request.form.items():
        if (key.startswith('amocrm_contact_field_') or key.startswith('amocrm_lead_field_')) and value:
            key = key.replace('amocrm_contact_field_', '').replace('amocrm_lead_field_', '')
            amocrm_field_mapping[key] = str(value)

    # Загружаем существующие настройки
    amocrm_settings = json.loads(partner.amocrm_settings) if partner.amocrm_settings else {}

    # Обновляем настройки новыми значениями
    amocrm_settings['pipeline_id'] = request.form.get('amocrm_pipeline')
    amocrm_settings['stage_id'] = request.form.get('amocrm_stage')

    partner.amocrm_field_mapping = json.dumps(amocrm_field_mapping)
    partner.amocrm_settings = json.dumps(amocrm_settings)
    db.session.commit()

    flash('Настройки соответствия полей успешно сохранены!', 'success')
    return redirect(url_for('partner.settings', tab='integrationsSettings'))


def get_amocrm_account_info(subdomain, api_key):
    url = f'https://{subdomain}.amocrm.ru/api/v4/account'
    headers = {'Authorization': f'Bearer {api_key}'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()


def get_amocrm_fields(subdomain, api_key, entity_type):
    url = f'https://{subdomain}.amocrm.ru/api/v4/{entity_type}/custom_fields'
    headers = {'Authorization': f'Bearer {api_key}'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()

    fields_data = response.json()

    # Формируем словарь с информацией о полях
    fields_info = {}
    for field in fields_data['_embedded']['custom_fields']:
        fields_info[str(field['id'])] = {
            'name': field['name']  # Удален 'field_name_format'
        }
    return fields_info


def get_amocrm_pipelines(subdomain, api_key):
    url = f'https://{subdomain}.amocrm.ru/api/v4/leads/pipelines'
    headers = {'Authorization': f'Bearer {api_key}'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()    
    
def get_amocrm_pipeline_stages(subdomain, api_key, pipeline_id):
    url = f'https://{subdomain}.amocrm.ru/api/v4/leads/pipelines/{pipeline_id}/statuses'
    headers = {'Authorization': f'Bearer {api_key}'}
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()    
    
@bp.route('/amocrm/test_integration', methods=['POST'])
@login_required
async def test_amocrm_integration():
    partner = Partner.query.filter_by(user_id=current_user.id).first()
    if not partner:
        return jsonify({'success': False, 'message': 'Партнер не найден.'})

    # Получаем тестовые данные из запроса
    test_client_name = request.form.get('testClientName')
    test_client_phone = request.form.get('testClientPhone')
    test_client_city = request.form.get('testClientCity')

    # Создаем тестовые данные клиента
    test_client_data = ClientsData(
        chat_id=test_client_phone or '79991234567',
        client_name=test_client_name or 'Тестовый клиент',
        city=test_client_city or 'Москва',
        initial_salon_name=partner.salons[0].name if partner.salons else 'Тестовый салон',
        initial_salon_id=partner.salons[0].id if partner.salons else 'test_salon_id',
        claimed_salon_name=partner.salons[0].name if partner.salons else 'Тестовый салон',
        claimed_salon_id=partner.salons[0].id if partner.salons else 'test_salon_id'
    )

    try:
        contact_id = await create_partner_amocrm_contact(test_client_data, partner)
        if contact_id:
            await create_or_update_partner_amocrm_lead(test_client_data, contact_id, partner, partner.salons[0])
            return jsonify({'success': True, 'message': 'Тест пройден успешно! Тестовый контакт и сделка созданы в AmoCRM.'})
        else:
            return jsonify({'success': False, 'message': 'Ошибка при тестировании интеграции: не удалось создать контакт.'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'Ошибка при тестировании интеграции: {str(e)}'})