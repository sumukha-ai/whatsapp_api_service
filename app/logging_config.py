import logging
import os
from logging.handlers import WatchedFileHandler

from celery.signals import after_setup_logger, after_setup_task_logger

LOG_DIR = os.getenv('LOG_DIR', './logs')
LOG_FORMAT = '%(asctime)s [%(process)d] [%(levelname)s] %(name)s: %(message)s'

_celery_signals_registered = False


def _ensure_log_dir():
    os.makedirs(LOG_DIR, exist_ok=True)


def _has_watched_file_handler(logger, logfile_path):
    target_path = os.path.abspath(logfile_path)
    for handler in logger.handlers:
        if isinstance(handler, WatchedFileHandler):
            base_filename = getattr(handler, 'baseFilename', '')
            if os.path.abspath(base_filename) == target_path:
                return True
    return False


def _attach_watched_file_handler(logger, logfile_path):
    if _has_watched_file_handler(logger, logfile_path):
        logger.setLevel(logging.INFO)
        return

    handler = WatchedFileHandler(logfile_path)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter(LOG_FORMAT))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def setup_flask_logging(app):
    _ensure_log_dir()
    app_log_path = os.path.join(LOG_DIR, 'app.log')

    _attach_watched_file_handler(app.logger, app_log_path)
    _attach_watched_file_handler(logging.getLogger(), app_log_path)


def setup_celery_logging():
    global _celery_signals_registered
    if _celery_signals_registered:
        return

    _ensure_log_dir()
    celery_log_path = os.path.join(LOG_DIR, 'celery.log')

    def _configure_logger(logger, *args, **kwargs):
        _attach_watched_file_handler(logger, celery_log_path)

    after_setup_logger.connect(
        _configure_logger,
        weak=False,
        dispatch_uid='app.logging_config.setup_celery_logging.after_setup_logger',
    )
    after_setup_task_logger.connect(
        _configure_logger,
        weak=False,
        dispatch_uid='app.logging_config.setup_celery_logging.after_setup_task_logger',
    )

    _celery_signals_registered = True
