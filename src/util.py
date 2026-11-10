import functools
import logging
import time

log = logging.getLogger("shorts")


def retry(times: int = 3, delay: float = 4.0, exceptions=(Exception,)):
    """Retry with exponential backoff - free API tiers rate-limit often."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            for attempt in range(1, times + 1):
                try:
                    return fn(*a, **kw)
                except exceptions as e:
                    if attempt == times:
                        raise
                    wait = delay * (2 ** (attempt - 1))
                    log.warning(
                        "%s failed (%s). Retry %d/%d in %.0fs",
                        fn.__name__,
                        e,
                        attempt,
                        times - 1,
                        wait,
                    )
                    time.sleep(wait)

        return wrapper

    return deco
