import logging
import functools

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s - %(levelname)s - %(message)s")

def log_function(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        logging.info(f"Вызов функции '{func.__name__}' с аргументами: args={args}, kwargs={kwargs}")
        try:
            result = func(*args, **kwargs)
            logging.info(f"Функция '{func.__name__}' успешно вернула: {result}")
            return result
        except Exception as err:
            logging.error(f"В функции '{func.__name__}' произошла ошибка:\n{type(err).__name__}: {err}")
            raise
    return wrapper