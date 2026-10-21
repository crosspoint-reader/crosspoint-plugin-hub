import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from check_release_metadata import validate


class ReleaseMetadataTests(unittest.TestCase):
    def setUp(self):
        self.manifest = {"name": "pluginhub", "title": "Plugin Hub", "version": "0.1.8"}
        self.device = {"title": "Plugin Hub", "version": "0.1.8"}

    def test_correct_title_and_version(self):
        validate(self.manifest, self.device, "v0.1.8")

    def test_bad_titles_rejected_on_new_releases(self):
        for metadata in (self.manifest, self.device):
            metadata["title"] = "Plugin Hub v0.1.8"
            with self.assertRaisesRegex(ValueError, "no version suffix"):
                validate(self.manifest, self.device, "v0.1.8")
            metadata["title"] = "Plugin Hub"

    def test_mismatched_versions_rejected(self):
        self.device["version"] = "0.1.7"
        with self.assertRaisesRegex(ValueError, "match release tag"):
            validate(self.manifest, self.device, "v0.1.8")

    def test_bad_id_or_tag_rejected(self):
        self.manifest["name"] = "wrong"
        with self.assertRaisesRegex(ValueError, "plugin ID"):
            validate(self.manifest, self.device, "v0.1.8")
        self.manifest["name"] = "pluginhub"
        with self.assertRaisesRegex(ValueError, "invalid release tag"):
            validate(self.manifest, self.device, "0.1.8")

    def test_legacy_tag_remains_repackageable(self):
        self.manifest.update(title="Plugin Hub v0.1.7", version="0.1.7")
        self.device.update(title="Plugin Hub v0.1.7")
        self.device.pop("version", None)
        validate(self.manifest, self.device, "v0.1.7")
