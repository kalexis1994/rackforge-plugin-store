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

Keep `official.secret` offline and backed up. If online signing is enabled,
store it only in a protected GitHub Environment requiring approval. Commit
only the public key after it has also been embedded in RackForge.

The current workflow intentionally uses an ephemeral key only to prove that
the generated catalog conforms to RackForge's signing and verification
contract. A production deployment workflow should be added after the remote
repository, protected environment, public URL, and recovery procedure exist.

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
