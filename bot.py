import logging
import os

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler
from sqlalchemy import text
import json
from app import db, create_app
from app.models import Partner, User

basedir = os.path.abspath(os.path.dirname(__file__))
load_dotenv(os.path.join(basedir, '.env'))


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        code = context.args[0]
        if code == "admin_notifications":
            await connect_admin(update, context)
        else:
            await connect(update, context, code)
    else:
        await context.bot.send_message(chat_id=update.message.chat_id,
                                       text="Привет! Я бот для оповещений Сарафан. Отсканируйте QR-код в личном кабинете, чтобы подключить уведомления.")


async def connect(update: Update, context: ContextTypes.DEFAULT_TYPE, code: str):
    app = create_app()
    app.app_context().push()

    chat_id = update.message.chat_id
    logging.info(f"Получено сообщение от chat_id: {chat_id}")

    partner = Partner.query.filter_by(unique_code=code).first()
    if partner:
        logging.info(f"Найден партнер: {partner}")
        partner.telegram_chat_id = chat_id
        db.session.commit()
        await context.bot.send_message(chat_id=update.message.chat_id, text='Telegram-оповещения успешно подключены!')
    else:
        logging.info(f"Партнер с кодом {code} не найден")
        await context.bot.send_message(chat_id=update.message.chat_id,
                                       text='Неверный код. Пожалуйста, проверьте код и попробуйте снова.')


async def connect_this_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app = create_app()
    app.app_context().push()

    chat_id = update.effective_chat.id
    user_id = update.effective_user.id  # Получаем ID пользователя Telegram
    logging.info(f"Получен запрос на подключение группы {chat_id} от пользователя {user_id}")

    # Проверяем, отправлена ли команда в группе
    if update.effective_chat.type not in ['group', 'supergroup']:
        await context.bot.send_message(chat_id, "Пожалуйста, используйте эту команду в группе.")
        return

    try:
        # Проверяем, является ли бот администратором группы
        chat_member = await context.bot.get_chat_member(chat_id, context.bot.id)

        # Проверяем наличие атрибута перед использованием
        if hasattr(chat_member, 'can_send_messages') and not chat_member.can_send_messages:
            await context.bot.send_message(chat_id, "Боту нужны права администратора для отправки сообщений в группу.")
            return

        # Ищем партнера по telegram_chat_id
        partner = Partner.query.filter_by(telegram_chat_id=user_id).first()
        if partner:
            partner.telegram_group_id = str(chat_id)  # Преобразование в строку
            db.session.commit()
            await context.bot.send_message(chat_id, "Группа успешно подключена!")
        else:
            await context.bot.send_message(chat_id, "Вы не зарегистрированы как партнер.")

    except Exception as e:
        logging.error(f"Ошибка при подключении группы: {e}")
        await context.bot.send_message(chat_id, "Произошла ошибка при подключении группы.")


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app = create_app()
    app.app_context().push()

    partner = Partner.query.filter_by(telegram_chat_id=update.message.chat_id).first()
    if partner:
        message = f"Ваша статистика:\n" \
                  f"Приведено клиентов: {partner.clients_brought}\n" \
                  f"Получено клиентов: {partner.clients_received}\n" \
                  f"Приглашено партнеров: {partner.partners_invited}"
    else:
        message = "Вы не зарегистрированы как партнер."
    await context.bot.send_message(chat_id=update.message.chat_id, text=message)


async def settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app = create_app()
    app.app_context().push()

    partner = Partner.query.filter_by(telegram_chat_id=update.message.chat_id).first()
    if partner:
        settings = partner.telegram_settings
        if settings:
            message = f"Ваши настройки уведомлений:\n" \
                      f"Новые клиенты: {'Включено' if settings.new_client_notification else 'Выключено'}\n" \
                      f"Новые партнеры: {'Включено' if settings.new_partner_notification else 'Выключено'}\n" \
                      f"Время отправки: {settings.notification_time.strftime('%H:%M') if settings.notification_time else 'Не установлено'}"
        else:
            message = "У вас не настроены уведомления. Перейдите в личный кабинет для настройки."
    else:
        message = "Вы не зарегистрированы как партнер."
    await context.bot.send_message(chat_id=update.message.chat_id, text=message)


async def connect_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    app = create_app()
    app.app_context().push()

    chat_id = update.message.chat_id
    logging.info(f"Получено сообщение от chat_id: {chat_id} для подключения администратора")

    admin = User.query.filter_by(username='admin').first()
    if not admin:
        await context.bot.send_message(chat_id=chat_id, text="Администратор не найден.")
        return

    if admin.telegram_chat_ids is None:
        admin.telegram_chat_ids = []

    if chat_id not in admin.telegram_chat_ids:
        admin.telegram_chat_ids.append(chat_id)

        try:
            # Преобразуем список в JSON-строку
            chat_ids_json = json.dumps(admin.telegram_chat_ids)

            db.session.execute(
                text("UPDATE users SET telegram_chat_ids=:chat_ids WHERE id=:admin_id"),
                {"chat_ids": chat_ids_json, "admin_id": admin.id}
            )
            db.session.commit()
            await context.bot.send_message(chat_id=chat_id, text="Вы успешно подключили уведомления для администратора.")
        except Exception as e:
            db.session.rollback()
            print(f"Error during update: {e}")
            await context.bot.send_message(chat_id=chat_id, text=f"Произошла ошибка: {e}")
    else:
        await context.bot.send_message(chat_id=chat_id, text="Вы уже подключены к уведомлениям администратора.")


def main():
    logging.basicConfig(
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        level=logging.INFO
    )
    application = ApplicationBuilder().token(os.environ.get("TELEGRAM_BOT_TOKEN")).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("connect_group", connect_this_group))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(CommandHandler("settings", settings))
    application.add_handler(CommandHandler("connect_admin", connect_admin))

    logging.info("Бот запущен и опрашивает обновления...")
    application.run_polling()


if __name__ == '__main__':
    main()