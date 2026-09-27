"""
main.py
---------
Starts the web/API server (stdlib wsgiref) and, if Telegram is
configured, the Telegram listener in a background thread.

Run with:
    python main.py
"""

import logging
import threading
import time
from wsgiref.simple_server import make_server

from app.http_app import application
from app.admin import expire_stale_access
from config import settings
from database.db import get_conn, init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")


def _start_telegram_listener():
    try:
        from integrations import telegram_listener
        telegram_listener.start()
    except Exception as e:
        # Telegram going down (or never being configured) must never
        # take down the web app - this thread just logs and stops.
        logger.error("Telegram listener stopped: %s", e)


def _access_expiry_loop():
    while True:
        try:
            expire_stale_access(get_conn())
        except Exception as e:
            logger.error("access expiry sweep failed: %s", e)
        time.sleep(3600)


def main():
    init_db()
    logger.info("Database ready at %s", settings.DB_PATH)

    threading.Thread(target=_start_telegram_listener, daemon=True).start()
    threading.Thread(target=_access_expiry_loop, daemon=True).start()

    logger.info("Starting web server on http://%s:%s (DRY_RUN=%s)", settings.HTTP_HOST, settings.HTTP_PORT, settings.DRY_RUN)
    with make_server(settings.HTTP_HOST, settings.HTTP_PORT, application) as httpd:
        httpd.serve_forever()


if __name__ == "__main__":
    main()
