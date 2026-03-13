import logging
from functools import wraps
from typing import Callable

from flask import jsonify


def catch_internal_error(f: Callable) -> Callable:
    @wraps(f)
    def wrapper(*args, **kwargs):
        try:
            # Execute the wrapped function
            return f(*args, **kwargs)
        except Exception as e:
            # Handle exception by logging and returning a custom error message
            method_name = f.__name__
            logging.getLogger("__name__").error(f"Internal error in {method_name}: {e}")
            return jsonify({
                "error": f"Internal error occurred in method '{method_name}'"
            }), 500

    return wrapper
