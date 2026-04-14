import time
import functools

DEBUG = True

def debug_log(message: str):
    if DEBUG:
        print(f"[DEBUG] {message}")

def timeit(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        if not DEBUG:
            return func(*args, **kwargs)
        start_time = time.perf_counter()
        debug_log(f"Starting {func.__name__}...")
        result = func(*args, **kwargs)
        end_time = time.perf_counter()
        duration = end_time - start_time
        debug_log(f"Finished {func.__name__} in {duration:.4f}s")
        return result
    return wrapper
