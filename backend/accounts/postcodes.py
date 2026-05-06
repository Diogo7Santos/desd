from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen

from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import ValidationError

UK_POSTCODE_RE = re.compile(r"^(GIR 0AA|[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2})$")
POSTCODE_ERROR_MESSAGE = "Enter a valid UK postcode, for example BS1 3TB."
POSTCODE_NOT_FOUND_ERROR_MESSAGE = "We couldn't find that postcode. Please enter a real UK postcode."
POSTCODE_LOOKUP_CACHE_PREFIX = "postcodes_io"
POSTCODE_LOOKUP_CACHE_TIMEOUT = 60 * 60 * 24
NOT_FOUND_SENTINEL = "__postcode_not_found__"


class PostcodeLookupUnavailable(Exception):
    pass


def normalize_uk_postcode(value: str) -> str:
    cleaned = "".join((value or "").upper().split())
    if not cleaned:
        return ""
    return f"{cleaned[:-3]} {cleaned[-3:]}"


def _cache_key(normalized_postcode: str) -> str:
    return f"{POSTCODE_LOOKUP_CACHE_PREFIX}:{normalized_postcode}"


def _cache_get(normalized_postcode: str):
    try:
        return cache.get(_cache_key(normalized_postcode))
    except Exception:
        return None


def _cache_set(normalized_postcode: str, value):
    try:
        cache.set(
            _cache_key(normalized_postcode),
            value,
            getattr(settings, "POSTCODES_IO_CACHE_TIMEOUT", POSTCODE_LOOKUP_CACHE_TIMEOUT),
        )
    except Exception:
        return


def postcode_format_is_valid(value: str) -> bool:
    normalized = normalize_uk_postcode(value)
    return bool(normalized and UK_POSTCODE_RE.fullmatch(normalized))


def lookup_postcode(postcode: str):
    normalized = normalize_uk_postcode(postcode)
    if not normalized or not postcode_format_is_valid(normalized):
        return None

    cached = _cache_get(normalized)
    if cached == NOT_FOUND_SENTINEL:
        return None
    if isinstance(cached, dict):
        return cached

    if not getattr(settings, "POSTCODES_IO_ENABLED", True):
        return None

    base_url = getattr(settings, "POSTCODES_IO_BASE_URL", "https://api.postcodes.io").rstrip("/")
    timeout = getattr(settings, "POSTCODES_IO_TIMEOUT", 3)
    url = f"{base_url}/postcodes/{quote(normalized)}"

    try:
        with urlopen(url, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 404:
            _cache_set(normalized, NOT_FOUND_SENTINEL)
            return None
        raise PostcodeLookupUnavailable from exc
    except (URLError, TimeoutError, ValueError, OSError) as exc:
        raise PostcodeLookupUnavailable from exc

    result = payload.get("result") or {}
    if not result:
        return None

    lookup_result = {
        "postcode": result.get("postcode", normalized),
        "latitude": result.get("latitude"),
        "longitude": result.get("longitude"),
        "outcode": result.get("outcode"),
        "country": result.get("country"),
        "region": result.get("region"),
    }
    _cache_set(normalized, lookup_result)
    return lookup_result


def clean_uk_postcode(value: str, *, require_live_lookup: bool = True) -> str:
    normalized = normalize_uk_postcode(value)
    if not normalized:
        return ""

    if not UK_POSTCODE_RE.fullmatch(normalized):
        raise ValidationError(POSTCODE_ERROR_MESSAGE)

    if require_live_lookup and getattr(settings, "POSTCODES_IO_ENABLED", True):
        try:
            result = lookup_postcode(normalized)
        except PostcodeLookupUnavailable:
            return normalized

        if result is None:
            raise ValidationError(POSTCODE_NOT_FOUND_ERROR_MESSAGE)

    return normalized
