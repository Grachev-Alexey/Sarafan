from flask import Blueprint

bp = Blueprint('partner', __name__, url_prefix='/partner')

from app.partner import routes  # Импортируем маршруты после определения bp
