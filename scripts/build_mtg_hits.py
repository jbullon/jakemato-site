#!/usr/bin/env python3
"""Build product-accurate, daily MTG $20+ hits for Jakemato.

MTGJSON identifies the *actual product sheets*, including cross-set cards and
foil/nonfoil slots. Scryfall supplies prices, images, and exact-print purchase
links. No card is included simply because it shares a set name.
"""
import argparse
import datetime as dt
import json
import os
import pathlib
import time
import urllib.error
import urllib.request

BASE = "https://mtgjson.com/api/v5"
SCRYFALL = "https://api.scryfall.com/cards/collection"
ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "tools/mtg-hits/data/hits.json"
MIN_PRICE = 20.0
USER_AGENT = "JakematoMTGHits/1.0 (https://jakemato.com)"
PACK_TYPES = {"PLAY": "Play Booster", "COLLECTOR": "Collector Booster",
              "DRAFT": "Draft Booster", "SET": "Set Booster"}
TYPES = {"expansion", "core", "masters", "draft_innovation", "remastered",
         "funny", "premium_deck"}
# Include the requested set, even after it passes the rolling release window.
ALWAYS_INCLUDE = {"MH3"}
EARLIEST_RELEASE = "2024-01-01"


def request_json(url, payload=None):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(
                url, data=body, headers=headers, method="POST" if body else "GET"
            ), timeout=75) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            if attempt == 2:
                raise
            print("Retrying", url, str(error), flush=True)
            time.sleep(2 ** attempt)


def set_data(code, cache):
    code = code.upper()
    if code not in cache:
        payload = request_json(BASE + "/" + code + ".json")
        cache[code] = payload["data"]
    return cache[code]


def pack_type_by_config(set_record):
    """Use sealed product-to-config mappings, not assumptions about set membership."""
    result = {}
    for product in set_record.get("sealedProduct", []):
        if (product.get("category") or "").upper() != "BOOSTER_PACK":
            continue
        subtype = (product.get("subtype") or "").upper()
        name = (product.get("name") or "").lower()
        if subtype not in PACK_TYPES:
            subtype = next((key for key in PACK_TYPES
                            if key.lower() + " booster" in name), "")
        if subtype not in PACK_TYPES:
            continue
        for linked in (product.get("contents") or {}).get("pack", []):
            if linked.get("set", "").upper() == set_record["code"].upper():
                result[linked.get("code")] = subtype
    return result


def finish_for_sheet(card, sheet_name, is_foil):
    """Never attach a price for a finish the particular printing cannot have."""
    finishes = set(card.get("finishes") or [])
    if not is_foil:
        return "nonfoil" if "nonfoil" in finishes else None
    if "etched" in sheet_name.lower() and "etched" in finishes:
        return "etched"
    if "foil" in finishes:
        return "foil"
    if "etched" in finishes:
        return "etched"
    return None


def collect_boosters(record, cache):
    products = []
    mapping = pack_type_by_config(record)
    for config_id, config in (record.get("booster") or {}).items():
        kind = mapping.get(config_id)
        # MH3's default configuration is the Play Booster, as confirmed by WotC.
        if record["code"].upper() == "MH3" and config_id == "default":
            kind = "PLAY"
        if not kind and config_id.upper() in PACK_TYPES:
            kind = config_id.upper()
        if kind not in PACK_TYPES:
            continue

        # Only sheets with at least one nonzero slot in a pack configuration.
        active = {key for pack in config.get("boosters", [])
                  if pack.get("weight", 1) > 0
                  for key, count in pack.get("contents", {}).items() if count > 0}
        if not active:
            continue
        card_by_uuid = {}
        for code in set([record["code"]] + config.get("sourceSetCodes", [])):
            try:
                for card in set_data(code, cache).get("cards", []):
                    card_by_uuid[card["uuid"]] = card
            except Exception as error:
                print("Missing source set", code, error, flush=True)

        entries = set()
        missing = 0
        for sheet_name in active:
            sheet = config.get("sheets", {}).get(sheet_name)
            if not sheet:
                missing += 1
                continue
            for uuid, weight in sheet.get("cards", {}).items():
                if weight <= 0:
                    continue
                card = card_by_uuid.get(uuid)
                if not card or not (card.get("identifiers") or {}).get("scryfallId"):
                    missing += 1
                    continue
                finish = finish_for_sheet(card, sheet_name, bool(sheet.get("foil")))
                if finish:
                    entries.add((card["identifiers"]["scryfallId"], finish))
                else:
                    missing += 1
        products.append({
            "id": "booster:" + record["code"].upper() + ":" + str(config_id),
            "set": record["code"].upper(),
            "setName": record["name"],
            "name": PACK_TYPES[kind],
            "type": kind.lower(),
            "_entries": entries,
            "_unresolved": missing,
        })
    return products


def collect_secret_lair(cache):
    """Include only named drops with explicitly enumerated contents.

    Some SLD product records are incomplete; those cannot be certified and are
    deliberately excluded, including mystery bonus cards.
    """
    record = set_data("SLD", cache)
    lookup = {}
    for item in record.get("sealedProduct", []):
        contents = item.get("contents") or {}
        for included in contents.get("card", []):
            lookup.setdefault(included.get("set", "SLD").upper(), set()).add(
                included.get("uuid"))
    cards = {}
    for code in lookup:
        try:
            for card in set_data(code, cache).get("cards", []):
                cards[card["uuid"]] = card
        except Exception as error:
            print("Could not read Secret Lair source", code, error, flush=True)

    drops = []
    for product in record.get("sealedProduct", []):
        included = (product.get("contents") or {}).get("card") or []
        if not included:
            continue
        entries, missing = set(), 0
        for ref in included:
            card = cards.get(ref.get("uuid"))
            sid = (card or {}).get("identifiers", {}).get("scryfallId")
            if not sid:
                missing += 1
                continue
            if ref.get("etched"):
                finish = "etched"
            else:
                finish = "foil" if ref.get("foil") else "nonfoil"
            if finish in (card.get("finishes") or []):
                entries.add((sid, finish))
            else:
                missing += 1
        # Don't claim all contents verified if the underlying product is incomplete.
        if not entries:
            continue
        drops.append({
            "id": "sld:" + product["uuid"],
            "set": "SLD",
            "setName": "Secret Lair",
            "name": product["name"],
            "type": "secret-lair",
            "_entries": entries,
            "_unresolved": missing
        })
    return drops


def fetch_scryfall(ids):
    results = {}
    ids = sorted(set(ids))
    for start in range(0, len(ids), 75):
        chunk = ids[start:start + 75]
        response = request_json(SCRYFALL, {
            "identifiers": [{"id": sid} for sid in chunk]
        })
        for card in response.get("data", []):
            results[card["id"]] = card
        if response.get("not_found"):
            print("Scryfall unmatched:", len(response["not_found"]), flush=True)
        # Scryfall asks callers to average fewer than ten requests per second.
        time.sleep(0.17)
    return results


def public_hit(card, finish):
    price_field = {"nonfoil": "usd", "foil": "usd_foil",
                   "etched": "usd_etched"}[finish]
    raw = (card.get("prices") or {}).get(price_field)
    try:
        price = float(raw)
    except (ValueError, TypeError):
        return None  # Do not invent a price for unlisted/serialized cards.
    if price <= MIN_PRICE:
        return None
    image = (card.get("image_uris") or {}).get("normal")
    if not image:
        faces = card.get("card_faces") or []
        image = ((faces[0].get("image_uris") or {}).get("normal")
                 if faces else None)
    return {
        "id": card["id"],
        "name": card["name"],
        "set": card.get("set", "").upper(),
        "number": card.get("collector_number", ""),
        "finish": finish,
        "price": round(price, 2),
        "image": image,
        # Scryfall links directly to the matching printing, not a search result.
        "tcgplayer": (card.get("purchase_uris") or {}).get("tcgplayer"),
    }


def make_catalog(products, cards):
    published = []
    for product in products:
        seen, hits = set(), []
        for sid, finish in product.pop("_entries"):
            card = cards.get(sid)
            if not card:
                product["_unresolved"] += 1
                continue
            hit = public_hit(card, finish)
            if hit and (sid, finish) not in seen:
                seen.add((sid, finish))
                hits.append(hit)
        hits.sort(key=lambda hit: (-hit["price"], hit["name"], hit["finish"]))
        product["hits"] = hits
        product["unresolved"] = product.pop("_unresolved")
        published.append(product)
    published.sort(key=lambda p: (p["set"] == "SLD", p["setName"].lower(),
                                  p["type"] != "play", p["name"].lower()))
    return published


def build():
    cache = {}
    listing = request_json(BASE + "/SetList.json").get("data", [])
    now = dt.datetime.now(dt.timezone.utc).date().isoformat()
    selected = [s for s in listing if
                (s.get("code", "").upper() in ALWAYS_INCLUDE or
                 (EARLIEST_RELEASE <= (s.get("releaseDate") or "") <= now and
                  s.get("type") in TYPES and not s.get("isOnlineOnly")))]
    codes = set(s["code"].upper() for s in selected) | ALWAYS_INCLUDE
    products = []
    for code in sorted(codes):
        if code == "SLD":
            continue
        try:
            record = set_data(code, cache)
            products.extend(collect_boosters(record, cache))
        except Exception as error:
            print("Skipping unavailable set", code, error, flush=True)
    try:
        products.extend(collect_secret_lair(cache))
    except Exception as error:
        print("Secret Lair data unavailable", error, flush=True)
    ids = {sid for p in products for sid, _ in p["_entries"]}
    print("Products", len(products), "unique printings", len(ids), flush=True)
    if not ids:
        raise RuntimeError("No verified product sheets found; refusing empty output")
    cards = fetch_scryfall(ids)
    if len(cards) < len(ids) * 0.9:
        raise RuntimeError("Too many missing Scryfall matches; preserving old data")
    catalog = make_catalog(products, cards)
    # A missing source card means the listing may be incomplete. Make it visible.
    payload = {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "minimumPriceExclusive": MIN_PRICE,
        "pricingSource": "Scryfall daily USD market estimates",
        "products": catalog,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temp = OUTPUT.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                    encoding="utf-8")
    temp.replace(OUTPUT)
    print("Wrote", OUTPUT, "with", len(catalog), "products", flush=True)


if __name__ == "__main__":
    build()
