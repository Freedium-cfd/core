import hashlib
import secrets
import difflib
import urllib.parse
from datetime import datetime
from functools import lru_cache
from urllib.parse import urlparse

import aiohttp
import string
import minify_html as mh
import tld
from bs4 import BeautifulSoup
from loguru import logger

from . import TIMEOUT

VALID_ID_CHARS = set(string.ascii_letters + string.digits)

KNOWN_MEDIUM_NETLOC = ("javascript.plainenglish.io", "python.plainenglish.io", "levelup.gitconnected.com")
KNOWN_MEDIUM_DOMAINS = ("medium.com", "towardsdatascience.com", "eand.co", "betterprogramming.pub", "curiouse.co", "betterhumans.pub")

NOT_MEDIUM_DOMAINS = ("github.com", "yandex.ru", "google.com", "yandex.kz")


def is_valid_url(url):
    fld = get_fld(url)
    if not fld:
        return False

    parsed_url = urlparse(url)
    return bool(parsed_url.scheme and parsed_url.netloc)


def getting_percontage_of_match(string: str, matched_string: str) -> int:
    return difflib.SequenceMatcher(None, string, matched_string).ratio() * 100


def generate_random_sha256_hash():
    # Encode the input string to bytes before hashing
    random_input_bytes = secrets.token_bytes()
    # Create the SHA-256 hash object
    sha256_hash = hashlib.sha256()
    # Update the hash object with the input bytes
    sha256_hash.update(random_input_bytes)
    # Get the hexadecimal representation of the hash
    sha256_hex = sha256_hash.hexdigest()
    return sha256_hex


def get_unix_ms() -> int:
    # Get the current date and time
    current_date_time = datetime.now()

    # Convert to the number of milliseconds since January 1, 1970 (Unix Epoch time)
    milliseconds_since_epoch = int(current_date_time.timestamp() * 1000)

    return milliseconds_since_epoch


def sanitize_url(url):
  """
  Sanitizes a URL by removing all query parameters.

  Args:
    url: The URL to sanitize.

  Returns:
    A sanitized URL.
  """

  parsed_url = urllib.parse.urlparse(url)
  query = parsed_url.query
  if query:
    parsed_url = parsed_url._replace(query='')
  sanitized_url = urllib.parse.urlunparse(parsed_url)
  return sanitized_url.removesuffix("/")


def is_valid_medium_post_id_hexadecimal(hex_string: str) -> bool:
        # Check if the string is a valid hexadecimal string
        # isalnum()
        for char in hex_string:
            if char not in VALID_ID_CHARS:
                return False

        # Check if the string contains only lowercase hexadecimal characters
        # if not hex_string.islower():
        #     return False

        # Check if the length of the string is correct for a hexadecimal string (e.g., 10, 11 or 12 characters)
        if len(hex_string) not in range(8, 13):
            return False

        return True


async def resolve_medium_short_link_v1(short_url_id: str) -> str:
    async with aiohttp.ClientSession() as client:
        request = await client.get(
            f"https://rsci.app.link/{short_url_id}",
            timeout=TIMEOUT,
            headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/83.0.4103.116 Safari/537.36"},
            allow_redirects=False,
        )
        post_url = request.headers["Location"]
    return await get_medium_post_id_by_url(post_url)


async def get_medium_post_id_by_url(url: str) -> str:
    parsed_url = urlparse(url)
    if parsed_url.path.startswith("/p/"):
        post_id = parsed_url.path.rsplit("/p/")[1]
    elif parsed_url.netloc == "link.medium.com":
        short_url_id = parsed_url.path.removeprefix("/")
        return await resolve_medium_short_link_v1(short_url_id)
    else:
        post_url = parsed_url.path.split("/")[-1]
        post_id = post_url.split("-")[-1]

    if not is_valid_medium_post_id_hexadecimal(post_id):
        return False

    return post_id


async def get_medium_post_id_by_url_old(url: str) -> str:
    async with aiohttp.ClientSession() as client:
        request = await client.get(url, timeout=TIMEOUT)
        response = await request.text()
    soup = BeautifulSoup(response, "html.parser")
    type_meta_tag = soup.head.find("meta", property="og:type")
    if not type_meta_tag or type_meta_tag.get("content") != "article":
        return False
    url_meta_tag = soup.head.find("meta", property="al:android:url")
    if not url_meta_tag or not url_meta_tag.get("content"):
        return False
    parsed_url = urlparse(url_meta_tag["content"])
    path = parsed_url.path.strip("/")
    parsed_value = path.split("/")[-1]
    return parsed_value


def minify_html(html: str) -> str:
    return mh.minify(html, remove_processing_instructions=True)


@lru_cache(maxsize=200)
def get_fld(url: str):
    try:
        fld = tld.get_fld(url)
    except Exception as ex:
        logger.trace(ex)
        return None
    else:
        return fld


async def is_valid_medium_url(url: str) -> bool:
    """
    Check if the url is a valid medium.com url

    First stage of url validation is checking if the domain is in the known medium.com url list. If the domain is in the list, then the url is valid
    Second stage is checking if the url is valid Medium site by performing a GET request to the url and checking the site name meta tag. If the site name meta tag is Medium, then the url is valid
    """
    # First stage
    domain = get_fld(url)
    parsed_url = urlparse(url)

    if domain in NOT_MEDIUM_DOMAINS:
        return False

    if domain in KNOWN_MEDIUM_DOMAINS or parsed_url.netloc in KNOWN_MEDIUM_NETLOC:
        return True
    else:
        logger.warning(f"url '{url}' wasn't detected in known medium domains")

    # Second stage
    async with aiohttp.ClientSession() as client:
        request = await client.get(url, timeout=TIMEOUT)
        response = await request.text()

    soup = BeautifulSoup(response, "html.parser")

    if not soup.head:
        return False

    site_name_meta_tag = soup.head.find("meta", property="og:site_name")

    if not site_name_meta_tag or site_name_meta_tag.get("content") != "Medium":
        return False

    return True
