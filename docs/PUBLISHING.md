# Publishing model

## Trust boundary

`org.rackforge.official` is the only repository identity supported by the
initial RackForge product integration. RackForge releases embed its Ed25519
public key. Plugin repositories and their workflows never receive the official
private signing key.

The official store publisher downloads each reviewed release asset, validates
the package with the pinned RackForge `rackforge-store` binary, recomputes size
and SHA-256, and mirrors it below `v1/packages`. The signed `v1/index.json`
therefore contains only same-origin published URLs supported by Catalog v1.

## Production key setup

Do not generate the production key in an ordinary CI run. Generate it on a
controlled machine with:

```text
rackforge-store keygen official.secret official.public
```

Keep `official.secret` offline and backed up. The CI copy is stored only as the
`RACKFORGE_STORE_SIGNING_KEY` secret in the `production-store` GitHub
Environment. `keys/official.public` is intentionally committed and must be
embedded in RackForge before the store is enabled in a product release.

The validation workflow uses an ephemeral key and never receives the
production secret. The production workflow can only be dispatched explicitly
from `main`, signs the generated catalog, verifies the signature with the
committed public key, and then uploads the exact verified directory to GitHub
Pages.

## Production publication

1. Merge a reviewed catalog change into `main` and wait for `Validate official
   store` to pass.
2. Open **Actions -> Publish official store -> Run workflow** and select
   `main`.
3. Approve the `production-store` deployment if environment approval is
   enabled.
4. Confirm that both build and `github-pages` deployment jobs succeed.
5. Verify `v1/index.json` and `v1/index.json.sig` from
   `https://kalexis1994.github.io/rackforge-plugin-store/` with the released
   RackForge public key.

Publishing is write-once per workflow run: packages are rebuilt from reviewed
immutable GitHub Release URLs. The generated `dist` directory is never reused
between runs.

## Adding a plugin

1. Publish an immutable `.rfplugin` as a Release asset in its source repo.
2. Copy `catalog/examples/plugin.json.example` to `catalog/plugins/<id>.json`.
3. Fill in the stable HTTPS Release URL, expected byte size, and SHA-256.
4. Open a pull request.
5. Let the central workflow download and validate the package.
6. Approve and publish the newly signed catalog from the protected environment.

Open-source code does not automatically make every bundled sample, firmware,
or commercial data file redistributable. Review both the plugin code license
and every packaged asset license before adding an entry.
