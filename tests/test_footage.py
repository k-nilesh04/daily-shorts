import unittest

from src.footage import _candidate, _usable_license


def field(value: str) -> dict[str, str]:
    return {"value": value}


class WikimediaFootageTests(unittest.TestCase):
    def test_allows_public_domain_cc0_and_attribution_only(self):
        for label in ("Public domain", "CC0 1.0", "CC BY 4.0"):
            with self.subTest(label=label):
                result = _usable_license({
                    "LicenseShortName": field(label),
                    "LicenseUrl": field("https://example.org/license"),
                })
                self.assertIsNotNone(result)

    def test_rejects_noncommercial_sharealike_and_noderivatives(self):
        for label in ("CC BY-SA 4.0", "CC BY-NC 4.0", "CC BY-ND 4.0"):
            with self.subTest(label=label):
                self.assertIsNone(_usable_license({
                    "LicenseShortName": field(label),
                    "LicenseUrl": field("https://example.org/license"),
                }))

    def test_candidate_includes_creator_license_and_source(self):
        candidate = _candidate({
            "pageid": 123,
            "title": "File:Blue Planet.webm",
            "imageinfo": [{
                "mime": "video/webm",
                "url": "https://upload.wikimedia.org/blue_planet.webm",
                "extmetadata": {
                    "Artist": field('<a href="/wiki/User:Example">A. Creator</a>'),
                    "LicenseShortName": field("CC BY 4.0"),
                    "LicenseUrl": field("https://creativecommons.org/licenses/by/4.0/"),
                },
            }],
        })
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["creator"], "A. Creator")
        self.assertEqual(candidate["license"], "CC BY 4.0")
        self.assertIn("File:Blue_Planet.webm", candidate["page_url"])

    def test_rejects_images_and_cc_by_without_creator(self):
        base = {
            "pageid": 123,
            "title": "File:Not reusable.mp4",
            "imageinfo": [{
                "mime": "video/mp4",
                "url": "https://upload.wikimedia.org/video.mp4",
                "extmetadata": {
                    "LicenseShortName": field("CC BY 4.0"),
                    "LicenseUrl": field("https://creativecommons.org/licenses/by/4.0/"),
                },
            }],
        }
        self.assertIsNone(_candidate(base))
        base["imageinfo"][0]["mime"] = "image/jpeg"
        base["imageinfo"][0]["extmetadata"]["Artist"] = field("A. Creator")
        self.assertIsNone(_candidate(base))


if __name__ == "__main__":
    unittest.main()
