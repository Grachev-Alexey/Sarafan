from datetime import datetime, timezone
from flask import current_app
from flask_login import UserMixin
from itsdangerous import URLSafeTimedSerializer as Serializer
from sqlalchemy.orm import relationship, backref
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from sqlalchemy import JSON, UniqueConstraint, func

salon_categories = db.Table('salon_categories',
                            db.Column('salon_id', db.String(255), db.ForeignKey('partner_info.id')),
                            db.Column('category_id', db.Integer, db.ForeignKey('category.id'))
                            )

partner_salons = db.Table('partner_salons',
    db.Column('partner_id', db.Integer, db.ForeignKey('partners.id'), primary_key=True),
    db.Column('salon_id', db.String(255), db.ForeignKey('partner_info.id'), primary_key=True)
)

class ClientSalonStatus(db.Model):
    __tablename__ = 'client_salon_status'
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('clients_data.id'), nullable=False)
    salon_id = db.Column(db.String(64), db.ForeignKey('partner_info.id', ondelete='CASCADE'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    status = db.Column(db.String(255), nullable=False)

    __table_args__ = (
        db.UniqueConstraint('client_id', 'salon_id', name='unique_client_salon_status'),
    )

    def __repr__(self):
        return f"<ClientSalonStatus(client_id='{self.client_id}', salon_id='{self.salon_id}', status='{self.status}')>"


class ClientsData(db.Model):
    __tablename__ = 'clients_data'

    id = db.Column(db.Integer, primary_key=True)
    chat_id = db.Column(db.String(255), nullable=False, unique=True)
    initial_salon_name = db.Column(db.String(255), nullable=False)
    initial_salon_id = db.Column(db.String(255), nullable=False)
    claimed_salon_name = db.Column(db.String(255), nullable=True)
    claimed_salon_id = db.Column(db.String(255), nullable=True)
    chosen_salon_name = db.Column(db.String(255), nullable=True)
    chosen_salon_id = db.Column(db.String(255), nullable=True)
    first_offered_salon_id = db.Column(db.String(255), nullable=True)    
    client_name = db.Column(db.String(255), nullable=False)
    city = db.Column(db.String(255), nullable=True)
    discount_claimed = db.Column(db.Boolean, default=False)
    attempts_left = db.Column(db.Integer, default=1)
    salon_statuses = relationship('ClientSalonStatus', backref='client', lazy='dynamic')
    date = db.Column(db.Date, nullable=False)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=True)
    partner = relationship('Partner', backref='clients_data', lazy=True)

    def __repr__(self):
        return f"<ClientsData(chat_id='{self.chat_id}', initial_salon_name='{self.initial_salon_name}', claimed_salon_name='{self.claimed_salon_name}')>"


class PartnerInfo(db.Model):
    __tablename__ = 'partner_info'

    id = db.Column(db.String(255), primary_key=True)
    partner_type = db.Column(db.String(255), nullable=False)
    categories = db.relationship('Category', secondary=salon_categories, backref=db.backref('partners', lazy=True))
    name = db.Column(db.String(255), nullable=False)
    discount = db.Column(db.Text, nullable=False)
    city_id = db.Column(db.Integer, db.ForeignKey('city.id'), nullable=False)
    city = db.relationship('City', backref=db.backref('partners', lazy=True))
    contacts = db.Column(db.String(255), nullable=False)
    clients_brought = db.Column(db.Integer, default=0)
    clients_received = db.Column(db.Integer, default=0)
    priority = db.Column(db.Boolean, default=False)
    linked_partner_id = db.Column(db.String(255), nullable=True)
    message_partner_name = db.Column(db.String(255), nullable=True)
    client_statuses = relationship('ClientSalonStatus', backref='salon', lazy='dynamic')
    invited_by = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=True)

    def __repr__(self):
        return f"<PartnerInfo(id='{self.id}', name='{self.name}', categories='{self.categories}', city='{self.city}', linked_partner_id='{self.linked_partner_id}', message_partner_name='{self.message_partner_name}')>"

class PartnerDailyStats(db.Model):
    """Модель для хранения ежедневной статистики партнеров."""
    __tablename__ = 'partner_daily_stats'

    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
    salon_id = db.Column(db.String(255), db.ForeignKey('partner_info.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    clients_brought = db.Column(db.Integer, default=0)
    offers_shown = db.Column(db.Integer, default=0)
    offers_accepted = db.Column(db.Integer, default=0)
    offers_rejected = db.Column(db.Integer, default=0)

    __table_args__ = (
        UniqueConstraint('partner_id', 'salon_id', 'date', name='unique_daily_stats'),
    )

    partner = db.relationship('Partner', backref='daily_stats')
    salon = db.relationship('PartnerInfo', backref='daily_stats')

class Category(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)

    def __str__(self):
        return self.name


class MessageTemplate(db.Model):
    """Модель для хранения шаблонов сообщений."""
    __tablename__ = 'message_templates'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)
    template = db.Column(db.Text, nullable=False)

    def __str__(self):
        return self.name


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), index=True, unique=True, nullable=False)
    telegram_chat_ids = db.Column(JSON, nullable=True, default=[])
    is_active = db.Column(db.Boolean, default=True)
    password_hash = db.Column(db.String(255), nullable=False)

    def get_id(self):
        return str(self.id)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_reset_password_token(self):
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id}, salt='reset-password-salt')

    @staticmethod
    def verify_reset_password_token(token, expires_in=600):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            data = s.loads(token, salt='reset-password-salt', max_age=expires_in)
        except:
            return None
        return User.query.get(data['user_id'])

    def __repr__(self):
        return f'<User {self.username}>'


class PartnerInvitation(db.Model):
    __tablename__ = 'partner_invitations'
    inviting_partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), primary_key=True)
    invited_partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), primary_key=True)
    invitation_date = db.Column(db.Date, nullable=False)


class Partner(db.Model):
    __tablename__ = 'partners'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    referral_link = db.Column(db.String(255), unique=True, nullable=False)
    partners_invited = db.Column(db.Integer, default=0)
    unique_code = db.Column(db.String(255), nullable=True)
    telegram_chat_id = db.Column(db.Integer, nullable=True)
    telegram_group_id = db.Column(db.String(255), nullable=True)
    user = relationship('User', backref='partner', uselist=False)
    amocrm_subdomain = db.Column(db.Text, nullable=True)
    amocrm_api_key = db.Column(db.Text, nullable=True)
    amocrm_account_info = db.Column(db.Text, nullable=True)
    amocrm_contacts_fields = db.Column(db.Text, nullable=True)
    amocrm_leads_fields = db.Column(db.Text, nullable=True)
    amocrm_pipelines = db.Column(db.Text, nullable=True)
    amocrm_field_mapping = db.Column(db.Text, nullable=True)
    amocrm_settings = db.Column(db.Text, nullable=True) 
    is_active = db.Column(db.Boolean, default=False)
    invited_partners = relationship("Partner",
                                    secondary="partner_invitations",
                                    primaryjoin="Partner.id==PartnerInvitation.inviting_partner_id",
                                    secondaryjoin="Partner.id==PartnerInvitation.invited_partner_id",
                                    backref=backref("invited_by", lazy="dynamic"),
                                    lazy="dynamic")
    salons = db.relationship('PartnerInfo', secondary=partner_salons, 
                             backref=db.backref('partners', lazy='dynamic'), cascade="all,")                             

    def __repr__(self):
        return f"<Partner(id='{self.id}', user_id='{self.user_id}')>"
        
    @property
    def clients_brought(self):
        return sum(salon.clients_brought for salon in self.salons)

    @property
    def clients_received(self):
        return sum(salon.clients_received for salon in self.salons)        


class DiscountWeightSettings(db.Model):
    __tablename__ = 'discount_weight_settings'

    id = db.Column(db.Integer, primary_key=True)
    ratio_40_80_weight = db.Column(db.Integer, default=3)
    ratio_30_40_weight = db.Column(db.Integer, default=2)
    ratio_below_30_weight = db.Column(db.Integer, default=1)
    partners_invited_weight = db.Column(db.Integer, default=1)


class Tip(db.Model):
    __tablename__ = 'tips'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)


class News(db.Model):
    __tablename__ = 'news'
    id = db.Column(db.Integer, primary_key=True)
    text = db.Column(db.Text, nullable=False)
    is_active = db.Column(db.Boolean, default=True)


class FAQ(db.Model):
    __tablename__ = 'faqs'
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)


class PartnerFAQStatus(db.Model):
    __tablename__ = 'partner_faq_statuses'
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), primary_key=True)
    has_read_faq = db.Column(db.Boolean, default=False)
    partner = db.relationship('Partner', backref=db.backref('faq_status', uselist=False))


class PartnerAction(db.Model):
    __tablename__ = 'partner_actions'
    id = db.Column(db.Integer, primary_key=True)
    partner_id = db.Column(db.Integer, db.ForeignKey('partners.id'), nullable=False)
    action_type = db.Column(db.String(255), nullable=False)
    details = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.now(timezone.utc))
    partner = db.relationship('Partner', backref=db.backref('actions', lazy='dynamic'))


class City(db.Model):
    __tablename__ = 'city'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False, unique=True)

    def __str__(self):
        return self.name
        
class AdminActionLog(db.Model):
    __tablename__ = 'admin_action_logs'
    id = db.Column(db.Integer, primary_key=True)
    admin_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    source = db.Column(db.String(255), nullable=True) 
    action = db.Column(db.String(255), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    admin = db.relationship('User', backref='admin_actions')

    def __repr__(self):
        return f'<AdminActionLog {self.id}: {self.action} by {self.admin.username if self.admin else "System"}>'    
        
class ClientView:
    def __init__(self, client_data: ClientsData):
        self.id = client_data.id
        self.chat_id = client_data.chat_id
        self.client_name = client_data.client_name
        self.city = client_data.city
        self.initial_salon_name = client_data.initial_salon_name
        self.chosen_salon_name = client_data.chosen_salon_name
        self.date = client_data.date
        self.attempts_left = client_data.attempts_left
        self.discount_claimed = client_data.discount_claimed
        self.last_interaction = (db.session.query(func.max(ClientSalonStatus.date))
                                 .filter(ClientSalonStatus.client_id == client_data.id)
                                 .scalar())
        self.rejected_salons = ', '.join([status.salon.name for status in client_data.salon_statuses if status.status == 'rejected'])
        self.visited_salons = ', '.join([status.salon.name for status in client_data.salon_statuses if status.status == 'visited'])
        self.chosen_salons = ', '.join([status.salon.name for status in client_data.salon_statuses if status.status == 'claimed'])        