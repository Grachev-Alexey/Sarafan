from functools import wraps
from urllib.parse import urlparse
import os
import qrcode
from io import BytesIO
import base64
from flask import Blueprint, render_template, redirect, url_for, flash, request, session, jsonify
from flask_login import current_user, login_user, logout_user
import asyncio
from sqlalchemy import text, func
from datetime import datetime, timedelta
from app import db
from app.admin.forms import SalonForm, PartnerForm, MessageTemplateForm, DiscountWeightSettingsForm, CategoryForm, \
    AdminLoginForm, TipForm, NewsForm, FAQForm, TelegramNotificationsForm
from app.models import PartnerInfo, MessageTemplate, Partner, User, DiscountWeightSettings, ClientsData, Category, Tip, \
    News, FAQ, PartnerAction, ClientSalonStatus, PartnerFAQStatus, partner_salons, AdminActionLog, ClientView, PartnerDailyStats
from telegram import Bot, error
from app.admin.services import get_data_from_partner_daily_stats, get_partners_invited_data

def log_admin_action(action):
    """Функция для логирования действий администратора."""
    log_entry = AdminActionLog(admin_id=current_user.id, action=action)
    db.session.add(log_entry)
    db.session.commit()

bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(func):
    @wraps(func)
    def decorated_view(*args, **kwargs):
        if not current_user.is_authenticated or current_user.username != 'admin':
            flash('У вас нет доступа к этой странице.', 'error')
            return redirect(url_for('admin.login'))
        return func(*args, **kwargs)

    return decorated_view


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('admin.index'))
    form = AdminLoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Неверный логин или пароль', 'danger')
            return redirect(url_for('admin.login'))
        login_user(user)
        next_page = request.args.get('next')
        if not next_page or urlparse(next_page).netloc != '':
            next_page = url_for('admin.index')
        return redirect(next_page)
    return render_template('admin/login.html', title='Вход', form=form)


@bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('admin.login'))


@bp.route('/')
@admin_required
def index():
    salon_count = PartnerInfo.query.count()
    partner_count = Partner.query.count()
    client_count = ClientsData.query.count()
    claimed_gifts_count = ClientSalonStatus.query.filter_by(status='claimed').count()

    # --- Получение данных для графиков ---
    clients_brought_data = get_data_from_partner_daily_stats(None, 'clients_brought', period='all')
    offers_shown_data = get_data_from_partner_daily_stats(None, 'offers_shown', period='all')
    offers_accepted_data = get_data_from_partner_daily_stats(None, 'offers_accepted', period='all')
    offers_rejected_data = get_data_from_partner_daily_stats(None, 'offers_rejected', period='all')
    partners_invited_data = get_partners_invited_data(None, period='all')

    # --- Топ 10 самых активных партнеров ---
    subquery = db.session.query(
        Partner.id,
        func.sum(PartnerInfo.clients_brought).label('total_clients_brought')
    ).join(partner_salons, Partner.id == partner_salons.c.partner_id) \
     .join(PartnerInfo, partner_salons.c.salon_id == PartnerInfo.id) \
     .group_by(Partner.id).subquery()

    top_active_partners = Partner.query.join(
        subquery, Partner.id == subquery.c.id
    ).order_by(
        subquery.c.total_clients_brought.desc(), Partner.partners_invited.desc()
    ).limit(10).all()

    # --- Топ 10 самых неактивных партнеров ---
    top_inactive_partners = Partner.query.outerjoin(
        subquery, Partner.id == subquery.c.id
    ).order_by(
        subquery.c.total_clients_brought.asc(),  # Сортировка по количеству приведенных клиентов
        Partner.partners_invited.asc()
    ).limit(10).all()

    # --- Топ 10 партнеров с отказами от скидок ---
    top_rejected_partners = db.session.query(Partner, func.count(ClientSalonStatus.id).label('rejections')) \
        .join(partner_salons, Partner.id == partner_salons.c.partner_id) \
        .join(ClientSalonStatus, partner_salons.c.salon_id == ClientSalonStatus.salon_id) \
        .filter(ClientSalonStatus.status == 'rejected') \
        .group_by(Partner.id) \
        .order_by(text('rejections DESC')) \
        .limit(10) \
        .all()

    return render_template('admin/dashboard.html',
                           salon_count=salon_count,
                           partner_count=partner_count,
                           client_count=client_count,
                           claimed_gifts_count=claimed_gifts_count,
                           top_active_partners=top_active_partners,
                           top_inactive_partners=top_inactive_partners,
                           top_rejected_partners=top_rejected_partners,
                           clients_brought_data=clients_brought_data,
                           offers_shown_data=offers_shown_data,
                           offers_accepted_data=offers_accepted_data,
                           offers_rejected_data=offers_rejected_data,
                           partners_invited_data=partners_invited_data)

@bp.route('/chart_data')
@admin_required
def chart_data():
    period = request.args.get('period', 'month')

    # Получаем данные для всех графиков
    clients_brought_data = get_data_from_partner_daily_stats(None, 'clients_brought', period)
    offers_shown_data = get_data_from_partner_daily_stats(None, 'offers_shown', period)
    offers_accepted_data = get_data_from_partner_daily_stats(None, 'offers_accepted', period)
    offers_rejected_data = get_data_from_partner_daily_stats(None, 'offers_rejected', period)
    partners_invited_data = get_partners_invited_data(None, period)

    return jsonify({
        'clients_brought': clients_brought_data,
        'offers_shown': offers_shown_data,
        'offers_accepted': offers_accepted_data,
        'offers_rejected': offers_rejected_data,
        'partners_invited': partners_invited_data
    })

@bp.route('/salons')
@admin_required
def salons():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    salons = PartnerInfo.query.all()
    return render_template('admin/salons.html', salons=salons)

@bp.route('/salons/<salon_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_salon(salon_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    salon = PartnerInfo.query.get_or_404(salon_id)
    form = SalonForm(obj=salon)
    if form.validate_on_submit():
        new_salon_id = form.id.data

        # Проверяем, нужно ли изменять ID салона
        if new_salon_id != salon_id:
            # Проверяем, существует ли уже PartnerInfo с новым ID
            existing_salon = PartnerInfo.query.get(new_salon_id)
            if existing_salon:
                flash(f'Ошибка при обновлении салона: Салон с ID "{new_salon_id}" уже существует.', 'error')
                return redirect(url_for('admin.edit_salon', salon_id=salon_id))

            try:
                with db.session.begin_nested():
                    # 1. Создаем новый объект PartnerInfo с новым ID
                    new_salon = PartnerInfo(id=new_salon_id)

                    # 2. Заполняем новый объект данными из формы
                    form.populate_obj(new_salon)

                    # 3. Копируем категории из старого объекта
                    new_salon.categories = salon.categories

                    # 4. Копируем связанные объекты ClientSalonStatus
                    new_salon.clients_brought = salon.clients_brought
                    new_salon.clients_received = salon.clients_received
                    new_salon.client_statuses = salon.client_statuses

                    # 5. Добавляем новый объект в сессию
                    db.session.add(new_salon)

                    # 6. Синхронизируем изменения с базой данных, не закрывая транзакцию
                    db.session.flush()

                    # 7. Обновляем salon_id в связанных записях partner_salons
                    db.session.query(partner_salons).filter_by(salon_id=salon_id).update({partner_salons.c.salon_id: new_salon.id})
                    db.session.query(PartnerDailyStats).filter_by(salon_id=salon_id).update({PartnerDailyStats.salon_id: new_salon.id})

                    # 8. Удаляем старый объект PartnerInfo
                    db.session.delete(salon)

                    # 9. Фиксируем изменения
                    db.session.commit()
                flash('Салон успешно обновлен!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка при обновлении салона: {e}', 'error')
            return redirect(url_for('admin.salons'))
        else:
            # ID салона не меняется, обновляем существующий объект
            try:
                with db.session.begin_nested():
                    # Обновляем данные салона
                    form.populate_obj(salon)
                    db.session.commit()
                flash('Салон успешно обновлен!', 'success')
            except Exception as e:
                db.session.rollback()
                flash(f'Ошибка при обновлении салона: {e}', 'error')
            return redirect(url_for('admin.salons'))
    return render_template('admin/edit_salon.html', form=form, title='Редактировать салон', enumerate=enumerate, salon=salon)

@bp.route('/salons/<salon_id>/delete', methods=['POST'])
@admin_required
def delete_salon(salon_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))

    # 1. Удаляем связанные записи в ClientSalonStatus
    ClientSalonStatus.query.filter_by(salon_id=salon_id).delete()  

    # 2. Удаляем связанные записи в partner_daily_stats
    PartnerDailyStats.query.filter_by(salon_id=salon_id).delete()

    # 3. Удаляем салон
    salon = PartnerInfo.query.get_or_404(salon_id)
    db.session.delete(salon)
    db.session.commit()
    flash('Салон успешно удален!', 'success')
    return redirect(url_for('admin.salons'))


@bp.route('/partners')
@admin_required
def partners():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    partners = Partner.query.all()
    return render_template('admin/partners.html', partners=partners)

@bp.route('/partners/<partner_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_partner(partner_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    partner = Partner.query.get_or_404(partner_id)
    user = User.query.get(partner.user_id)
    form = PartnerForm(obj=partner)
    if form.validate_on_submit():
        partner.is_active = form.is_active.data

        db.session.commit()  # Сохраняем все изменения
        flash('Партнер успешно обновлен!', 'success')
        return redirect(url_for('admin.partners'))
    return render_template('admin/edit_partner.html', form=form, user=user, title='Редактировать партнера')


@bp.route('/partners/<partner_id>/delete', methods=['POST'])
@admin_required
def delete_partner(partner_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))

    partner = Partner.query.get_or_404(partner_id)
    user = User.query.get(partner.user_id)

    # 1. Удаляем связанные записи в PartnerFAQStatus
    PartnerFAQStatus.query.filter_by(partner_id=partner_id).delete()
    # 2. Удаляем связанные записи в PartnerAction
    PartnerAction.query.filter_by(partner_id=partner_id).delete()

    # 3. Удаляем связанные записи в client_salon_status для всех салонов партнера
    for salon in partner.salons:
        ClientSalonStatus.query.filter_by(salon_id=salon.id).delete()

    # 4. Удаляем связанные записи в PartnerDailyStats для всех салонов партнера
    for salon in partner.salons:
        PartnerDailyStats.query.filter_by(salon_id=salon.id).delete()

    # 5. Удаляем салоны партнера
    for salon in partner.salons:
        db.session.delete(salon)

    # 6. Удаляем партнера и пользователя
    db.session.delete(partner)
    db.session.delete(user)
    db.session.commit()

    flash('Партнер успешно удален!', 'success')
    return redirect(url_for('admin.partners'))

@bp.route('/partners/<partner_id>/impersonate')
@admin_required
def impersonate_partner(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    if not partner:
        flash('Партнер не найден.', 'danger')
        return redirect(url_for('admin.partners'))

    # Логирование действия администратора
    log_admin_action(f'Администратор {current_user.username} вошел как партнер {partner.user.username}')

    # Создание сессии для партнера
    session['impersonated_user_id'] = partner.user_id 
    logout_user() # Выходим из сессии администратора
    login_user(partner.user) # Входим как партнер

    flash('Вы вошли как партнер {}.'.format(partner.user.username), 'success')
    return redirect(url_for('partner.dashboard'))

@bp.route('/message_templates')
@admin_required
def message_templates():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    message_templates = MessageTemplate.query.all()
    return render_template('admin/message_templates.html', message_templates=message_templates)


@bp.route('/message_templates/create', methods=['GET', 'POST'])
@admin_required
def create_message_template():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    form = MessageTemplateForm()
    if form.validate_on_submit():
        template = MessageTemplate(
            name=form.name.data,
            template=form.template.data
        )
        db.session.add(template)
        db.session.commit()
        flash('Шаблон сообщения успешно добавлен!', 'success')
        return redirect(url_for('admin.message_templates'))
    return render_template('admin/edit_message_template.html', form=form, title='Добавить шаблон сообщения')


@bp.route('/message_templates/<template_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_message_template(template_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    template = MessageTemplate.query.get_or_404(template_id)
    form = MessageTemplateForm(obj=template)
    if form.validate_on_submit():
        form.populate_obj(template)
        db.session.commit()
        flash('Шаблон сообщения успешно обновлен!', 'success')
        return redirect(url_for('admin.message_templates'))
    return render_template('admin/edit_message_template.html', form=form, title='Редактировать шаблон сообщения')


@bp.route('/message_templates/<template_id>/delete', methods=['POST'])
@admin_required
def delete_message_template(template_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    template = MessageTemplate.query.get_or_404(template_id)
    db.session.delete(template)
    db.session.commit()
    flash('Шаблон сообщения успешно удален!', 'success')
    return redirect(url_for('admin.message_templates'))


@bp.route('/discount_weight_settings', methods=['GET', 'POST'])
@admin_required
def discount_weight_settings():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    settings = DiscountWeightSettings.query.get_or_404(1)
    form = DiscountWeightSettingsForm(obj=settings)
    if form.validate_on_submit():
        form.populate_obj(settings)
        db.session.commit()
        flash('Настройки весов успешно сохранены!', 'success')
        return redirect(url_for('admin.discount_weight_settings'))
    return render_template('admin/edit_discount_weight_settings.html', form=form, title='Настройки весов скидок')


@bp.route('/categories')
@admin_required
def categories():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    categories = Category.query.all()
    return render_template('admin/categories.html', categories=categories)


@bp.route('/categories/create', methods=['GET', 'POST'])
@admin_required
def create_category():
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    form = CategoryForm()
    if form.validate_on_submit():
        category = Category(name=form.name.data)
        db.session.add(category)
        db.session.commit()
        flash('Категория успешно добавлена!', 'success')
        return redirect(url_for('admin.categories'))
    return render_template('admin/edit_category.html', form=form, title='Добавить категорию')


@bp.route('/categories/<int:category_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_category(category_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    category = Category.query.get_or_404(category_id)
    form = CategoryForm(obj=category)
    if form.validate_on_submit():
        form.populate_obj(category)
        db.session.commit()
        flash('Категория успешно обновлена!', 'success')
        return redirect(url_for('admin.categories'))
    return render_template('admin/edit_category.html', form=form, title='Редактировать категорию')


@bp.route('/categories/<int:category_id>/delete', methods=['POST'])
@admin_required
def delete_category(category_id):
    if current_user.username != 'admin':
        flash('У вас нет доступа к этой странице.', 'error')
        return redirect(url_for('admin.login'))
    category = Category.query.get_or_404(category_id)
    db.session.delete(category)
    db.session.commit()
    flash('Категория успешно удалена!', 'success')
    return redirect(url_for('admin.categories'))


@bp.route('/tips')
@admin_required
def tips():
    tips = Tip.query.all()
    return render_template('admin/tips.html', tips=tips)


@bp.route('/tips/create', methods=['GET', 'POST'])
@admin_required
def create_tip():
    form = TipForm()
    if form.validate_on_submit():
        tip = Tip(text=form.text.data, is_active=form.is_active.data)
        db.session.add(tip)
        db.session.commit()
        flash('Совет успешно добавлен!', 'success')
        return redirect(url_for('admin.tips'))
    return render_template('admin/edit_tip.html', form=form, title='Добавить совет')


@bp.route('/tips/<int:tip_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_tip(tip_id):
    tip = Tip.query.get_or_404(tip_id)
    form = TipForm(obj=tip)
    if form.validate_on_submit():
        form.populate_obj(tip)
        db.session.commit()
        flash('Совет успешно обновлен!', 'success')
        return redirect(url_for('admin.tips'))
    return render_template('admin/edit_tip.html', form=form, title='Редактировать совет')


@bp.route('/tips/<int:tip_id>/delete', methods=['POST'])
@admin_required
def delete_tip(tip_id):
    tip = Tip.query.get_or_404(tip_id)
    db.session.delete(tip)
    db.session.commit()
    flash('Совет успешно удален!', 'success')
    return redirect(url_for('admin.tips'))


@bp.route('/news')
@admin_required
def news():
    news_list = News.query.all()
    return render_template('admin/news.html', news=news_list)


@bp.route('/news/create', methods=['GET', 'POST'])
@admin_required
def create_news():
    form = NewsForm()
    if form.validate_on_submit():
        news = News(text=form.text.data, is_active=form.is_active.data)
        db.session.add(news)
        db.session.commit()
        flash('Новость успешно добавлена!', 'success')
        return redirect(url_for('admin.news'))
    return render_template('admin/edit_news.html', form=form, title='Добавить новость')


@bp.route('/news/<int:news_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_news(news_id):
    news = News.query.get_or_404(news_id)
    form = NewsForm(obj=news)
    if form.validate_on_submit():
        form.populate_obj(news)
        db.session.commit()
        flash('Новость успешно обновлена!', 'success')
        return redirect(url_for('admin.news'))
    return render_template('admin/edit_news.html', form=form, title='Редактировать новость')


@bp.route('/news/<int:news_id>/delete', methods=['POST'])
@admin_required
def delete_news(news_id):
    news = News.query.get_or_404(news_id)
    db.session.delete(news)
    db.session.commit()
    flash('Новость успешно удалена!', 'success')
    return redirect(url_for('admin.news'))

@bp.route('/admin/clients')
def clients():
    clients_data = ClientsData.query.all()
    clients = [ClientView(client_data) for client_data in clients_data]
    return render_template('admin/clients.html', clients=clients)

@bp.route('/faqs')
@admin_required
def faqs():
    faqs = FAQ.query.all()
    return render_template('admin/faqs.html', faqs=faqs)


@bp.route('/faqs/create', methods=['GET', 'POST'])
@admin_required
def create_faq():
    form = FAQForm()
    if form.validate_on_submit():
        faq = FAQ(question=form.question.data, answer=form.answer.data)
        db.session.add(faq)
        db.session.commit()
        flash('Вопрос FAQ успешно добавлен!', 'success')
        return redirect(url_for('admin.faqs'))
    return render_template('admin/edit_faq.html', form=form, title='Добавить вопрос FAQ')


@bp.route('/faqs/<int:faq_id>/edit', methods=['GET', 'POST'])
@admin_required
def edit_faq(faq_id):
    faq = FAQ.query.get_or_404(faq_id)
    form = FAQForm(obj=faq)
    if form.validate_on_submit():
        form.populate_obj(faq)
        db.session.commit()
        flash('Вопрос FAQ успешно обновлен!', 'success')
        return redirect(url_for('admin.faqs'))
    return render_template('admin/edit_faq.html', form=form, title='Редактировать вопрос FAQ')


@bp.route('/faqs/<int:faq_id>/delete', methods=['POST'])
@admin_required
def delete_faq(faq_id):
    faq = FAQ.query.get_or_404(faq_id)
    db.session.delete(faq)
    db.session.commit()
    flash('Вопрос FAQ успешно удален!', 'success')
    return redirect(url_for('admin.faqs'))


@bp.route('/partner_actions/<int:partner_id>')
@admin_required
def partner_actions(partner_id):
    partner = Partner.query.get_or_404(partner_id)
    actions = PartnerAction.query.filter_by(partner_id=partner_id).order_by(PartnerAction.timestamp.desc()).all()
    return render_template('admin/partner_actions.html', partner=partner, actions=actions)


@bp.route('/partner_actions')
@admin_required
def all_partner_actions():
    actions = PartnerAction.query.order_by(PartnerAction.timestamp.desc()).all()
    return render_template('admin/all_partner_actions.html', actions=actions)
    
@bp.route('/profile/telegram', methods=['GET', 'POST'])
@admin_required
def edit_telegram_notifications():
    return asyncio.run(edit_telegram_notifications_async())  # <<<--- ВЫЗЫВАЕМ АСИНХРОННУЮ ФУНКЦИЮ

async def edit_telegram_notifications_async(): # <<<--- СОЗДАЕМ АСИНХРОННУЮ ФУНКЦИЮ
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        flash('Администратор не найден.', 'danger')
        return redirect(url_for('admin.index'))

    # Генерация QR-кода
    qr = qrcode.QRCode(version=1, box_size=10, border=5)
    qr.add_data(f"https://t.me/{os.environ.get('TELEGRAM_BOT_USERNAME')}?start=admin_notifications")
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    qr_code_image = base64.b64encode(buffer.getvalue()).decode('utf-8')

    connected_admins = []
    if admin.telegram_chat_ids:
        bot = Bot(token=os.environ.get('TELEGRAM_BOT_TOKEN'))
        for chat_id in admin.telegram_chat_ids:
            try:
                chat = await bot.get_chat(chat_id=chat_id)
                connected_admins.append({'chat_id': chat_id, 'name': chat.first_name or chat.username or chat.title})
            except error.TelegramError:
                # Обработка ошибок, например, если чат не найден или бот заблокирован
                connected_admins.append({'chat_id': chat_id, 'name': 'Не удалось получить имя'})

    return render_template('admin/edit_telegram_notifications.html', 
                           title='Telegram-уведомления', 
                           qr_code_image=qr_code_image,
                           connected_admins=connected_admins)
                       
@bp.route('/profile/telegram/disconnect/<int:chat_id>', methods=['POST'])
@admin_required
def disconnect_admin(chat_id):
    admin = User.query.filter_by(username='admin').first()
    if not admin:
        flash('Администратор не найден.', 'danger')
        return redirect(url_for('admin.index'))

    print(f"Before removing: admin.telegram_chat_ids = {admin.telegram_chat_ids}")
    if chat_id in admin.telegram_chat_ids:
        try:
            admin.telegram_chat_ids.remove(chat_id)
            
            # Используем text() для объявления SQL запроса как текста
            db.session.execute(
                text("UPDATE users SET telegram_chat_ids=:chat_ids WHERE id=:admin_id"),
                {"chat_ids": admin.telegram_chat_ids, "admin_id": admin.id}
            )
            db.session.commit()

            print(f"After removing: admin.telegram_chat_ids = {admin.telegram_chat_ids}")
            flash('Уведомления для администратора успешно отключены!', 'success')
        except Exception as e:
            db.session.rollback()
            print(f"Error during disconnect: {e}")
            flash(f'Ошибка при отключении уведомлений: {e}', 'danger')
    else:
        print(f"Chat ID {chat_id} not found in admin.telegram_chat_ids")
        flash('Этот администратор не подключен к уведомлениям.', 'warning')

    return redirect(url_for('admin.edit_telegram_notifications'))         
    
@bp.route('/logs')
@admin_required
def view_logs():
    logs = AdminActionLog.query.order_by(AdminActionLog.timestamp.desc()).all()
    return render_template('admin/view_logs.html', logs=logs)    