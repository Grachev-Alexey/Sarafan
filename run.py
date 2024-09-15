from flask_migrate import upgrade
import logging
from app import create_app, db
from app.models import PartnerInfo, ClientsData, ClientSalonStatus, MessageTemplate, DiscountWeightSettings, User, \
    partner_salons

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {'db': db, 'PartnerInfo': PartnerInfo, 'ClientsData': ClientsData,
            'ClientSalonStatus': ClientSalonStatus, 'MessageTemplate': MessageTemplate,
            'DiscountWeightSettings': DiscountWeightSettings, 'User': User, 'partner_salons': partner_salons}

if __name__ == '__main__':
    with app.app_context():
        upgrade()
        db.create_all()

        # Создание записей для шаблонов сообщений
        templates = [
            {'name': 'start_message', 'template': "👋 Привет! Добро пожаловать в сервис «Сарафан»! 🎉"},
            {'name': 'spinning_wheel_message', 'template': "🎰 Крутим колесо фортуны..."},
            {'name': 'get_discount_message',
             'template': "✨ И вам выпадает {discount} в {message_salon_name}🤩\n\n Салон оказывает следующие услуги: {categories}! \n\nХотите забрать подарок?\n\n1 - Да / 2 - Нет (попыток больше нет)"},
            {'name': 'claim_discount',
             'template': "🥳 Поздравляем! Вы получили скидку в {message_salon_name}! 🎉\n\nВ ближайшее время с вами свяжется администратор.\n\n📞 Контакты: {contacts}"},
            {'name': 'discount_offer',
             'template': "✨ И вам выпадает {discount} в {message_salon_name}🤩\n\n Салон оказывает следующие услуги: {categories}! \n\nХотите забрать подарок?\n\n1 - Да / 2 - Нет (осталось {attempts_left} попытка)"},
            {'name': 'invalid_salon_id',
             'template': "⛔️ Упс, неверный формат ID салона. ID должен состоять только из цифр."},
            {'name': 'salon_not_found', 'template': "😔 К сожалению, салон с таким ID не найден."},
            {'name': 'already_visited', 'template': "🤔 Вы уже получали скидку в этом салоне."},
            {'name': 'welcome_back', 'template': "😊 Рады видеть вас снова! 👋"},
            {'name': 'data_loading_error', 'template': "⚠️ Ошибка при загрузке данных. Пожалуйста, начните сначала."},
            {'name': 'spin_wheel_first',
             'template': "🎰 Чтобы получить скидку, сначала нужно крутануть колесо фортуны. Напишите 'Да', чтобы начать."},
            {'name': 'user_declined', 'template': "👌 Хорошо. "},
            {'name': 'accept_terms',
             'template': "😔 Извините, но для участия в акции необходимо принять условия использования сервиса. Без этого мы не можем предоставить вам скидку. Пожалуйста, ознакомьтесь с условиями и дайте согласие, чтобы продолжить."},
            {'name': 'no_discounts_available', 'template': "😔 Извините, сейчас нет доступных скидок."},
            {'name': 'general_error', 'template': "⚠️ Произошла ошибка. Пожалуйста, начните сначала."}
        ]
        for data in templates:
            if not MessageTemplate.query.filter_by(name=data['name']).first():
                template = MessageTemplate(**data)
                db.session.add(template)
        db.session.commit()

        # Создание записи для настроек весов скидок
        if not DiscountWeightSettings.query.first():
            settings = DiscountWeightSettings(
                ratio_40_80_weight=3,
                ratio_30_40_weight=2,
                ratio_below_30_weight=1,
                partners_invited_weight=1
            )
            db.session.add(settings)
            db.session.commit()

        # Создание пользователя-администратора
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            admin_user = User(username='admin')
            admin_user.set_password('admin')
            db.session.add(admin_user)
            db.session.commit()
            print('Пользователь-администратор создан!')            

    app.run(host='0.0.0.0', debug=True)