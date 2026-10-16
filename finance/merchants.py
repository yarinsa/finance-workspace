"""Merchant keys: one counterparty name per raw ledger description.

Shared by data/spending.py (the /spending breakdown) and the ledger API
(`Merchant` in api/schema), so both group transactions the same way.
"""
import re

# Trailing ISO-ish country codes that card processors append after the city.
_COUNTRY = re.compile(r"\s+(?:[A-Z]{3}|[A-Z]{2})$")
_TRAILING_DIGITS = re.compile(r"[\s\-*#]*\d{3,}[\d\-/ ]*$")


def merchant_name(description):
    """Collapse a raw ledger description into a merchant key.

    Card processors pad fields with runs of spaces ("APPLE.COM/BILL     CORK    IRL"),
    so a run of 2+ spaces splits name from city/country and only the first field is
    kept. When the city is single-spaced ("APPLE.COM/BILL CUPERTINO USA") a trailing
    country code and one trailing all-caps Latin city token are stripped. Bank rows
    carry comma-separated memo fields ("העברה מירין ששון,חשבון ...") — only the
    first is the counterparty. Trailing reference numbers are dropped.
    """
    s = (description or "").strip()
    if not s:
        return "ללא תיאור"
    s = s.split(",")[0]
    parts = [p for p in re.split(r"\s{2,}", s) if p.strip()]
    if len(parts) > 1 and not any("\u0590" <= ch <= "\u05ff" for ch in " ".join(parts[1:])):
        s = parts[0]   # padded Latin city/country fields follow the name
    s = " ".join(s.split())
    if len(parts) == 1 and not s.count("  ") and re.search(r"[A-Za-z]", s):
        stripped = _COUNTRY.sub("", s)
        tokens = stripped.split()
        if stripped != s and len(tokens) >= 3 and re.fullmatch(r"[A-Z.]+", tokens[-1]):
            tokens = tokens[:-1]
        s = " ".join(tokens)
    s = _TRAILING_DIGITS.sub("", s).strip()
    return s or "ללא תיאור"
