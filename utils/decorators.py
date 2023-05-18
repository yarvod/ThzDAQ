from utils.logger import logger


def exception(func):
    """Simple function exception decorator"""

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"[{func.__qualname__}] {e}")

    return wrapper
