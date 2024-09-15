from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, PasswordField, HiddenField, RadioField, IntegerField, \
    BooleanField
from wtforms.validators import DataRequired, Length, EqualTo, Optional, InputRequired, ValidationError, Regexp
from wtforms_sqlalchemy.fields import QuerySelectMultipleField, QuerySelectField

from app.models import Category, City


class RegistrationForm(FlaskForm):
    salon_name = StringField('Название салона/мастера', validators=[DataRequired()])
    categories = QuerySelectMultipleField(
        'Категории',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=False
    )
    city = QuerySelectField('Город', query_factory=lambda: City.query.all(), get_label='name', allow_blank=False)
    discount_text = TextAreaField('Текст оффера', validators=[DataRequired()])
    contacts = StringField('Контактные данные', validators=[DataRequired()])
    message_salon_name = StringField('Название салона/мастера для сообщений', validators=[DataRequired()])
    login = StringField('Номер телефона (WhatsApp)', validators=[DataRequired(message='Введите номер телефона')])
    password = PasswordField('Пароль', validators=[DataRequired(), Length(min=6, max=30),
                                                   EqualTo('confirm_password', message='Пароли должны совпадать')])
    confirm_password = PasswordField('Подтвердите пароль', validators=[DataRequired()])
    partner_type = RadioField('Тип партнера', choices=[('salon', 'Салон'), ('individual', 'Частный мастер')],
                              validators=[InputRequired()])
    agree_terms = BooleanField('Я согласен с условиями', validators=[DataRequired()])
    submit = SubmitField('Зарегистрироваться')


class LoginForm(FlaskForm):
    login = StringField('Логин', validators=[DataRequired()])
    password = PasswordField('Пароль', validators=[DataRequired()])
    submit = SubmitField('Войти')


class EditSalonForm(FlaskForm):
    salon_name = StringField('Название салона/мастера', validators=[DataRequired()])
    categories = QuerySelectMultipleField(
        'Категории',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=False
    )
    city = QuerySelectField('Город', query_factory=lambda: City.query.all(), get_label='name', allow_blank=False)
    discount = TextAreaField('Текст скидки', validators=[DataRequired()])
    contacts = StringField('Контактные данные', validators=[DataRequired()])
    message_salon_name = StringField('Название салона/мастера для сообщений', validators=[DataRequired()])
    partner_type = RadioField('Тип партнера', choices=[('salon', 'Салон'), ('individual', 'Частный мастер')],
                              validators=[InputRequired()])
    salon_id = HiddenField('salon_id')
    submit = SubmitField('Сохранить изменения')


class EditUserForm(FlaskForm):
    username = StringField('Номер телефона (WhatsApp)', validators=[DataRequired(), Regexp(r'^7\d{10}$',
                                                                                           message='Введите номер телефона в формате 7XXXXXXXXXX')])
    submit = SubmitField('Сохранить изменения')


class ResetPasswordForm(FlaskForm):
    password = PasswordField('Новый пароль', validators=[DataRequired(), Length(min=6, max=30),
                                                         EqualTo('confirm_password',
                                                                 message='Пароли должны совпадать')])
    confirm_password = PasswordField('Подтвердите пароль', validators=[DataRequired()])
    submit = SubmitField('Сбросить пароль')

class AddSalonForm(FlaskForm):
    salon_name = StringField('Название салона/мастера', validators=[DataRequired()])
    categories = QuerySelectMultipleField(
        'Категории',
        query_factory=lambda: Category.query.all(),
        get_label='name',
        allow_blank=False
    )
    city = QuerySelectField('Город', query_factory=lambda: City.query.all(), get_label='name', allow_blank=False)
    discount_text = TextAreaField('Текст оффера', validators=[DataRequired()])
    contacts = StringField('Контактные данные', validators=[DataRequired()])
    message_salon_name = StringField('Название салона/мастера для сообщений', validators=[DataRequired()])
    partner_type = RadioField('Тип партнера', choices=[('salon', 'Салон'), ('individual', 'Частный мастер')],
                              validators=[InputRequired()])
    submit = SubmitField('Добавить салон')