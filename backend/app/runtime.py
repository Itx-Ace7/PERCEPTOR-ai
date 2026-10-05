from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.db import Database
from app.pipeline.retention import prune

settings: Settings | None = None
db: Database | None = None


def init() -> tuple[Settings, Database]:
    global settings, db
    settings = get_settings()
    db = Database(settings.database)
    db.fail_interrupted("Interrupted by a service restart. Start the analysis again.")
    try:
        prune(settings, db)
    except Exception:  # housekeeping must never stop the service from starting
        logging.getLogger(__name__).exception("startup retention failed")
    return settings, db
