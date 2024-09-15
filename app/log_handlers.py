# log_handlers.py

import logging
from app.models import AdminActionLog
from datetime import datetime

class SQLAlchemyHandler(logging.Handler):
    async def emit(self, record):
        from app import db  # Импортируем db здесь
        source = record.name if hasattr(record, 'name') else None 
        log_record = AdminActionLog(
            source=source,
            action=record.getMessage(),
            timestamp=datetime.utcfromtimestamp(record.created)
        )
        db.session.add(log_record)
        try:
            await db.session.async_commit()
        except Exception as e:
            db.session.rollback()
            self.handleError(record)