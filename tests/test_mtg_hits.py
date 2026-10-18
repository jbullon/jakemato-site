"""Offline tests: price cutoff and product-specific printing/finish eligibility."""
import pathlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from scripts import build_mtg_hits as hits


def sample_card(uuid, sid, finishes):
    return {"uuid": uuid, "identifiers": {"scryfallId": sid},
            "finishes": finishes}


class ProductAccuracyTests(unittest.TestCase):
    def test_mh3_collector_only_foil_never_in_play(self):
        source = {
            "code": "MH3", "name": "Modern Horizons 3",
            "cards": [
                sample_card("regular", "id-regular", ["nonfoil", "foil"]),
                sample_card("textured", "id-textured", ["foil"])
            ],
            "sealedProduct": [
                {"name": "MH3 Play Booster", "category": "BOOSTER_PACK",
                 "subtype": "PLAY", "contents": {"pack": [{"set": "MH3", "code": "default"}]}},
                {"name": "MH3 Collector Booster", "category": "BOOSTER_PACK",
                 "subtype": "COLLECTOR", "contents": {"pack": [{"set": "MH3", "code": "collector"}]}}
            ],
            "booster": {
                "default": {
                    "sourceSetCodes": ["MH3"],
                    "boosters": [{"contents": {"normal": 1}, "weight": 1}],
                    "sheets": {"normal": {"foil": False, "cards": {"regular": 1}}}
                },
                "collector": {
                    "sourceSetCodes": ["MH3"],
                    "boosters": [{"contents": {"textured": 1, "regular": 1}, "weight": 1}],
                    "sheets": {
                        "textured": {"foil": True, "cards": {"textured": 1}},
                        "regular": {"foil": True, "cards": {"regular": 1}}
                    }
                }
            }
        }
        products = hits.collect_boosters(source, {"MH3": source})
        self.assertEqual(len(products), 2)
        by_type = {p["type"]: p for p in products}
        self.assertEqual(by_type["play"]["_entries"], {("id-regular", "nonfoil")})
        self.assertIn(("id-textured", "foil"), by_type["collector"]["_entries"])
        self.assertNotIn(("id-textured", "foil"), by_type["play"]["_entries"])

    def test_exact_price_and_printing_links(self):
        card = {
            "id": "printing-123", "name": "Test Card",
            "set": "mh3", "collector_number": "468",
            "prices": {"usd": "20.00", "usd_foil": "25.50"},
            "image_uris": {"normal": "https://cards.scryfall.io/example.jpg"},
            "purchase_uris": {"tcgplayer": "https://www.tcgplayer.com/product/1234"}
        }
        self.assertIsNone(hits.public_hit(card, "nonfoil"))
        foil = hits.public_hit(card, "foil")
        self.assertEqual(foil["price"], 25.50)
        self.assertEqual(foil["finish"], "foil")
        self.assertEqual(foil["number"], "468")
        self.assertEqual(foil["tcgplayer"], "https://www.tcgplayer.com/product/1234")
        self.assertIsNone(hits.public_hit(card, "etched"))

    def test_unlisted_treatments_not_guessed(self):
        card = sample_card("a", "id-a", ["etched"])
        self.assertIsNone(hits.finish_for_sheet(card, "normal", False))
        self.assertEqual(hits.finish_for_sheet(card, "etched", True), "etched")
        self.assertEqual(hits.finish_for_sheet(
            sample_card("b", "id-b", ["nonfoil", "foil"]),
            "normal", True
        ), "foil")

    def test_sld_only_with_itemized_contents(self):
        record = {
            "cards": [sample_card("sld-card", "id-sld", ["foil", "nonfoil"])],
            "sealedProduct": [
                {"uuid": "drop-1", "name": "Secret Lair Drop: Test (Foil)",
                 "contents": {"card": [{"uuid": "sld-card", "set": "SLD", "foil": True}]}},
                {"uuid": "drop-2", "name": "Secret Lair Drop: Unknown",
                 "contents": None}
            ]
        }
        with patch.object(hits, "set_data", return_value=record):
            products = hits.collect_secret_lair({})
        self.assertEqual(len(products), 1)
        self.assertEqual(products[0]["_entries"], {("id-sld", "foil")})


if __name__ == "__main__":
    unittest.main()
