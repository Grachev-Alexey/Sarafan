from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, BooleanField, PasswordField, RadioField, IntegerField, FieldList, FormField
from wtforms.validators import DataRequired, Length, EqualTo, Optional, InputRequired
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField

from app.models import Category, City


class SalonForm(FlaskForm):
    id = StringField('ID', validators=[DataRequired()])
    partner_type = RadioField('Тип партнера', choices=[('salon', 'Салон'), ('individual', 'Частный мастер')],
                              validators=[InputRequired()])
    categories = QuerySelectMultipleField(
        'Категории',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=False
    )
    name = StringField('Название', validators=[DataRequired()])
    discount = TextAreaField('Оффер', validators=[DataRequired()])
    city = QuerySelectField('Город', query_factory=lambda: City.query.all(), get_label='name', allow_blank=False)
    contacts = StringField('Контакты', validators=[DataRequired()])
    priority = BooleanField('Приоритет')
    linked_partner_id = StringField('ID связанного партнера')
    message_partner_name = StringField('Название для сообщений')
    submit = SubmitField('Сохранить')


class PartnerForm(FlaskForm):
    is_active = BooleanField('Активен')
    submit = SubmitField('Сохранить')


class MessageTemplateForm(FlaskForm):
    name = StringField('Название', validators=[DataRequired()])
    template = TextAreaField('Шаблон', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class DiscountWeightSettingsForm(FlaskForm):
    ratio_40_80_weight = IntegerField('Вес для соотношения 40-80%', validators=[DataRequired()])
    ratio_30_40_weight = IntegerField('Вес для соотношения 30-40%', validators=[DataRequired()])
    ratio_below_30_weight = IntegerField('Вес для соотношения менее 30%', validators=[DataRequired()])
    partners_invited_weight = IntegerField('Вес за каждого приглашенного партнера', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class CategoryForm(FlaskForm):
    name = StringField('Название', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class AdminLoginForm(FlaskForm):
    username = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')


class TipForm(FlaskForm):
    text = TextAreaField('Текст совета', validators=[DataRequired()])
    is_active = BooleanField('Активен')
    submit = SubmitField('Сохранить')


class NewsForm(FlaskForm):
    text = TextAreaField('Текст новости', validators=[DataRequired()])
    is_active = BooleanField('Активен')
    submit = SubmitField('Сохранить')


class FAQForm(FlaskForm):
    question = TextAreaField('Вопрос', validators=[DataRequired()])
    answer = TextAreaField('Ответ', validators=[DataRequired()])
    submit = SubmitField('Сохранить')


class TelegramChatIDForm(FlaskForm):
    chat_id = IntegerField('Telegram Chat ID', validators=[Optional()])

class TelegramNotificationsForm(FlaskForm):
    telegram_chat_ids = FieldList(FormField(TelegramChatIDForm), min_entries=1)
    add_chat_id = SubmitField('Добавить ID')
    submit = SubmitField('Сохранить')

    def validate_telegram_chat_ids(self, field):
        # Проверка на уникальность ID
        chat_ids = [chat_id_form.chat_id.data for chat_id_form in field.entries if chat_id_form.chat_id.data]
        if len(chat_ids) != len(set(chat_ids)):
            raise ValidationError('Telegram Chat ID должны быть уникальными.')