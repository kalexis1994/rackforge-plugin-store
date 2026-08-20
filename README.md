# RackForge Official Plugin Store

This repository is the publication source for the single official plugin
store supported by RackForge's first store release. It does not contain plugin
source code and it never builds instruments. Each plugin remains in its own
repository and publishes immutable `.rfplugin` Release assets.

The store pipeline:

1. reads reviewed declarations from `catalog/plugins`;
2. downloads the declared GitHub Release assets;
3. validates every package with a pinned RackForge `rackforge-store` build;
4. recomputes package size and SHA-256;
5. mirrors packages below `v1/packages` for Catalog v1 same-origin delivery;
6. emits `v1/index.json`, ready for protected Ed25519 signing.

## Repository layout

```text
catalog/plugins/       Reviewed official catalog declarations
catalog/examples/      Declaration templates, never published
tools/build_store.py   Deterministic downloader and catalog builder
tests/                 Publisher safety and ordering tests
docs/PUBLISHING.md     Signing, review, and release procedure
RACKFORGE_REF          Exact RackForge validator commit used by CI
dist/                  Generated repository payload (ignored)
```

## Local validation

Requirements:

- Python 3.11 or newer;
- the sibling RackForge repository and its Rust toolchain.

From this directory on Windows:

```powershell
python -m unittest discover -s tests -v
cargo build --locked --release -p rackforge-store `
  --manifest-path ..\rackforge\Cargo.toml
python tools\build_store.py `
  --validator ..\rackforge\target\release\rackforge-store.exe
```

`dist` must not already exist: publisher builds are write-once so a stale
package cannot survive into a new catalog accidentally.

For isolated tests only, declarations may use `source_path` together with
`--allow-local-sources`. Official catalog declarations must use reviewed HTTPS
`source_url` values.

## Signing

The private Ed25519 key is not part of this repository. CI currently generates
an ephemeral key to exercise the complete sign/verify contract without
creating production trust material. See [Publishing](docs/PUBLISHING.md) before
creating the official key or deployment workflow.

## Current scope

- one built-in repository identity: `org.rackforge.official`;
- free plugins curated by the RackForge project;
- static signed Catalog v1;
- no accounts, purchases, telemetry, ratings, or custom repository UI;
- package activation remains an explicit host lifecycle step after install.
