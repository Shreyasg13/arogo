"""
food_barcode.py — Barcode → nutrition lookup via Open Food Facts.

Server-side so the browser never talks to a third party (keeps the
strict CSP intact) and no API key is needed. Returns a dict normalized
to MedEasy's food schema (per-100g, sodium in mg), or None if the
product isn't found.
"""
from __future__ import annotations

import re

import requests

OFF_URL = "https://world.openfoodfacts.org/api/v2/product/{}.json"
OFF_FIELDS = "product_name,brands,nutriments,serving_size"
TIMEOUT_S = 8
# Open Food Facts asks callers to identify themselves
HEADERS = {"User-Agent": "MedEasy/1.0 (health tracker; contact via app)"}


def _num(nutriments: dict, *keys) -> float:
    """First present numeric value among keys, else 0.0."""
    for k in keys:
        v = nutriments.get(k)
        if isinstance(v, (int, float)):
            return round(float(v), 2)
        if isinstance(v, str):
            try:
                return round(float(v), 2)
            except ValueError:
                continue
    return 0.0


def valid_barcode(code: str) -> bool:
    """UPC/EAN codes are 8–14 digits."""
    return bool(re.fullmatch(r"\d{8,14}", (code or "").strip()))


def lookup_barcode(code: str) -> dict | None:
    """Fetch and normalize a product. Returns None on not-found/error."""
    code = (code or "").strip()
    if not valid_barcode(code):
        return None
    try:
        r = requests.get(OFF_URL.format(code), params={"fields": OFF_FIELDS},
                         headers=HEADERS, timeout=TIMEOUT_S)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except ValueError:
        return None
    # status 0 = product not found
    if data.get("status") == 0:
        return None
    product = data.get("product") or {}
    if not product:
        return None

    n = product.get("nutriments") or {}
    brand = (product.get("brands") or "").split(",")[0].strip()
    name = (product.get("product_name") or "").strip()
    label = f"{brand} {name}".strip() if brand and brand.lower() not in name.lower() else name
    label = label or f"Product {code}"

    return {
        "barcode": code,
        "name": label[:120],
        "serving_g": 100,                      # OFF nutriments are per 100g
        "calories": _num(n, "energy-kcal_100g", "energy-kcal"),
        "protein":  _num(n, "proteins_100g"),
        "carbs":    _num(n, "carbohydrates_100g"),
        "fat":      _num(n, "fat_100g"),
        "fiber":    _num(n, "fiber_100g"),
        "sugar":    _num(n, "sugars_100g"),
        "sodium":   round(_num(n, "sodium_100g") * 1000, 1),  # g → mg
        "source":   "openfoodfacts",
    }
