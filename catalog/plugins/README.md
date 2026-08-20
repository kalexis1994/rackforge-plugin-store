# Plugin declarations

This directory contains the reviewed JSON declarations included in the
RackForge Official Store. One file represents one plugin ID. Store builds
download every declared release artifact, validate it with `rackforge-store`,
calculate its size and SHA-256, and publish a same-origin immutable copy.

Local paths are rejected by the publishing workflow. They exist only for
isolated tests through the explicit `--allow-local-sources` development flag.
