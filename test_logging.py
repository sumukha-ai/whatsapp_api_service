import logging
import os

from flask import Flask

from app.logging_config import setup_flask_logging


def main():
    app = Flask(__name__)
    setup_flask_logging(app)

    logger = logging.getLogger(__name__)
    logger.info('Test INFO log line')
    logger.warning('Test WARNING log line')

    try:
        raise RuntimeError('Intentional exception for logger.exception test')
    except Exception:
        logger.exception('Test exception log line')

    log_file_path = os.path.abspath(os.path.join(os.getenv('LOG_DIR', './logs'), 'app.log'))
    print(log_file_path)


if __name__ == '__main__':
    main()
