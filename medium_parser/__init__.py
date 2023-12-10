
import os
from aiohttp_retry import ExponentialRetry

import jinja2
from dotenv import load_dotenv
from .cache_db import SQLiteCacheBackend

cache = SQLiteCacheBackend('medium_db_cache.sqlite')
retry_options = ExponentialRetry(attempts=3)

from . import exceptions as exceptions
from . import exceptions as medium_parser_exceptions

jinja_env = jinja2.Environment(enable_async=True)

load_dotenv()

MEDIUM_AUTH_COOKIES = os.getenv("MEDIUM_AUTH_COOKIES")

if not MEDIUM_AUTH_COOKIES:
    raise ValueError("No auth cookies for Medium was found. Paywalled content doesn't will be available!!! Check MEDIUM_AUTH_COOKIES variable")
