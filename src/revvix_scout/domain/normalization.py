"""Deterministic identity normalization."""

import hashlib
import re
import unicodedata
from urllib.parse import urlsplit

import tldextract

_EXTRACTOR = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)
_SPACE_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s-]", flags=re.UNICODE)


class InvalidDomainError(ValueError):
    """Raised when a non-empty domain cannot be normalized safely."""


def normalize_company_name(value: str) -> str:
    """Normalize a company name for deterministic matching, not display."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    normalized = _NON_WORD_RE.sub(" ", normalized)
    return _SPACE_RE.sub(" ", normalized).strip()


def normalize_domain(value: str | None) -> str | None:
    """Return an ASCII registrable domain using the bundled public-suffix snapshot."""

    if value is None or not value.strip():
        return None

    candidate = value.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    host = parsed.hostname
    if host is None:
        raise InvalidDomainError("domain does not contain a valid hostname")

    host = host.rstrip(".").casefold()
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise InvalidDomainError("domain contains invalid international characters") from exc

    extracted = _EXTRACTOR(ascii_host)
    if not extracted.domain or not extracted.suffix:
        raise InvalidDomainError("domain must have a recognized public suffix")
    return f"{extracted.domain}.{extracted.suffix}"


def fallback_company_fingerprint(
    *, normalized_name: str, country_code: str | None, source_record_id: str
) -> str:
    """Create a stable import identity when a domain is unavailable.

    Source record ID is deliberately included: two same-name, same-country businesses
    remain distinct and require future review rather than being merged automatically.
    """

    material = "|".join((normalized_name, (country_code or "").upper(), source_record_id.strip()))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
