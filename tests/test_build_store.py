from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools.build_store import (
    DEFAULT_REDIRECT_HOSTS,
    DEFAULT_SOURCE_HOSTS,
    StoreError,
    build_store,
)


GENERATED_AT = "2026-08-20T00:00:00Z"


class StoreBuilderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="rackforge-store-test-")
        self.root = Path(self.temporary.name)
        self.catalog = self.root / "catalog" / "plugins"
        self.artifacts = self.root / "artifacts"
        self.catalog.mkdir(parents=True)
        self.artifacts.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def declaration(self, releases: list[dict] | None = None) -> dict:
        return {
            "schema_version": 1,
            "id": "org.rackforge.test-synth",
            "name": "RF-Test",
            "summary": "Test instrument",
            "license": "MIT",
            "homepage": "https://example.invalid/rf-test",
            "releases": releases
            or [
                {
                    "version": "1.2.3",
                    "published_at": GENERATED_AT,
                    "artifacts": [
                        {
                            "platform": "wasm-v1",
                            "source_path": "artifacts/test.rfplugin",
                        }
                    ],
                }
            ],
        }

    def write_declaration(self, value: dict) -> None:
        (self.catalog / "test.json").write_text(json.dumps(value), encoding="utf-8")

    def build(self) -> dict:
        return build_store(
            self.root,
            self.catalog,
            self.root / "dist",
            GENERATED_AT,
            validator=None,
            allow_local_sources=True,
            source_hosts=DEFAULT_SOURCE_HOSTS,
            redirect_hosts=DEFAULT_REDIRECT_HOSTS,
        )

    def test_builds_a_deterministic_same_origin_catalog(self) -> None:
        package = b"portable-rfplugin-fixture"
        (self.artifacts / "test.rfplugin").write_bytes(package)
        self.write_declaration(self.declaration())

        index = self.build()

        artifact = index["plugins"][0]["releases"][0]["artifacts"][0]
        self.assertEqual(artifact["url"], "packages/org.rackforge.test-synth-1.2.3-wasm-v1.rfplugin")
        self.assertEqual(artifact["size"], len(package))
        self.assertEqual(artifact["sha256"], hashlib.sha256(package).hexdigest())
        self.assertEqual(
            json.loads((self.root / "dist" / "v1" / "index.json").read_text(encoding="utf-8")),
            index,
        )

    def test_orders_semantic_versions_newest_first(self) -> None:
        (self.artifacts / "test.rfplugin").write_bytes(b"release")
        releases = []
        for version in [
            "1.2.0",
            "1.10.0",
            "2.0.0-beta.1",
            "2.0.0-beta.2",
            "2.0.0-beta.10",
            "2.0.0",
        ]:
            releases.append(
                {
                    "version": version,
                    "published_at": GENERATED_AT,
                    "artifacts": [
                        {
                            "platform": "wasm-v1",
                            "source_path": "artifacts/test.rfplugin",
                        }
                    ],
                }
            )
        self.write_declaration(self.declaration(releases))

        index = self.build()

        self.assertEqual(
            [release["version"] for release in index["plugins"][0]["releases"]],
            [
                "2.0.0",
                "2.0.0-beta.10",
                "2.0.0-beta.2",
                "2.0.0-beta.1",
                "1.10.0",
                "1.2.0",
            ],
        )

    def test_rejects_local_sources_without_explicit_development_permission(self) -> None:
        (self.artifacts / "test.rfplugin").write_bytes(b"release")
        self.write_declaration(self.declaration())

        with self.assertRaisesRegex(StoreError, "--allow-local-sources"):
            build_store(
                self.root,
                self.catalog,
                self.root / "dist",
                GENERATED_AT,
                validator=None,
                allow_local_sources=False,
                source_hosts=DEFAULT_SOURCE_HOSTS,
                redirect_hosts=DEFAULT_REDIRECT_HOSTS,
            )

    def test_rejects_local_path_traversal(self) -> None:
        outside = self.root.parent / "outside.rfplugin"
        outside.write_bytes(b"outside")
        declaration = self.declaration()
        declaration["releases"][0]["artifacts"][0]["source_path"] = "../outside.rfplugin"
        self.write_declaration(declaration)
        try:
            with self.assertRaisesRegex(StoreError, "stay inside the project"):
                self.build()
        finally:
            outside.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
