#!/usr/bin/env python3
"""Build the signed-repository payload from reviewed plugin declarations.

The builder deliberately separates ingestion URLs from published URLs. Source
packages are downloaded from their plugin repositories, validated, and copied
under ``v1/packages`` so Catalog v1 keeps its same-origin trust boundary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable


MAX_PACKAGE_BYTES = 512 * 1024 * 1024
PLUGIN_ID = re.compile(r"^[a-z0-9_-]+(?:\.[a-z0-9_-]+)+$")
PLATFORM_ID = re.compile(r"^[a-z0-9_-]+$")
SEMVER = re.compile(
    r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$"
)
DEFAULT_SOURCE_HOSTS = {"github.com"}
DEFAULT_REDIRECT_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
    "github-releases.githubusercontent.com",
}


class StoreError(RuntimeError):
    """A declaration or artifact cannot be published safely."""


def require_text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str):
        raise StoreError(f"{label} must be a string")
    value = value.strip()
    if not value or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise StoreError(f"{label} is empty, too long, or contains control characters")
    return value


def parse_semver(value: Any, label: str) -> tuple[int, int, int, int, tuple[tuple[int, Any], ...]]:
    value = require_text(value, label, 128)
    match = SEMVER.fullmatch(value)
    if match is None:
        raise StoreError(f"{label} must be a semantic version")
    prerelease = match.group(4)
    prerelease_key: list[tuple[int, Any]] = []
    if prerelease is not None:
        for identifier in prerelease.split("."):
            if identifier.isdigit():
                if len(identifier) > 1 and identifier.startswith("0"):
                    raise StoreError(f"{label} has a numeric prerelease identifier with a leading zero")
                prerelease_key.append((0, int(identifier)))
            else:
                prerelease_key.append((1, identifier))
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3)),
        1 if prerelease is None else 0,
        tuple(prerelease_key),
    )


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise StoreError(f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise StoreError(f"{path} must contain a JSON object")
    return value


def stream_to_file(source: BinaryIO, destination: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with destination.open("xb") as output:
        while chunk := source.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_PACKAGE_BYTES:
                raise StoreError(
                    f"artifact exceeds RackForge's {MAX_PACKAGE_BYTES}-byte package limit"
                )
            digest.update(chunk)
            output.write(chunk)
    if size == 0:
        raise StoreError("artifact is empty")
    return size, digest.hexdigest()


def download_artifact(
    url: str,
    destination: Path,
    source_hosts: set[str],
    redirect_hosts: set[str],
) -> tuple[int, str]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment:
        raise StoreError("source_url must be an HTTPS URL without credentials or fragments")
    if (parsed.hostname or "").lower() not in source_hosts:
        raise StoreError(f"source host {parsed.hostname!r} is not approved")
    request = urllib.request.Request(url, headers={"User-Agent": "RackForge-Store-Publisher/1"})
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            final = urllib.parse.urlparse(response.geturl())
            if final.scheme != "https" or (final.hostname or "").lower() not in redirect_hosts:
                raise StoreError(f"download redirected to unapproved destination {response.geturl()!r}")
            length = response.headers.get("Content-Length")
            if length is not None and int(length) > MAX_PACKAGE_BYTES:
                raise StoreError("artifact Content-Length exceeds RackForge's package limit")
            return stream_to_file(response, destination)
    except StoreError:
        raise
    except Exception as error:
        raise StoreError(f"could not download {url}: {error}") from error


def copy_local_artifact(source: Path, destination: Path, project_root: Path) -> tuple[int, str]:
    try:
        resolved = source.resolve(strict=True)
        resolved.relative_to(project_root.resolve(strict=True))
    except (OSError, ValueError) as error:
        raise StoreError(f"local artifact must stay inside the project: {source}") from error
    if not resolved.is_file():
        raise StoreError(f"local artifact is not a file: {source}")
    with resolved.open("rb") as input_file:
        return stream_to_file(input_file, destination)


def validate_package(
    validator: Path,
    package: Path,
    plugin_id: str,
    version: str,
    platform: str,
) -> None:
    with tempfile.TemporaryDirectory(prefix="rackforge-store-validate-") as temporary:
        store = Path(temporary) / "plugin-store"
        result = subprocess.run(
            [str(validator), "install-local", str(package), str(store)],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip()
            raise StoreError(f"RackForge rejected {package.name}: {detail}")
        record_path = store / "records" / plugin_id / f"{version}.json"
        record = load_json(record_path)
        for field, expected in {
            "plugin_id": plugin_id,
            "version": version,
            "platform": platform,
        }.items():
            if record.get(field) != expected:
                raise StoreError(
                    f"{package.name} reports {field}={record.get(field)!r}, expected {expected!r}"
                )


def checked_optional_expectation(artifact: dict[str, Any], key: str, actual: Any) -> None:
    expected = artifact.get(key)
    if expected is not None and expected != actual:
        raise StoreError(f"artifact {key} is {actual!r}, expected {expected!r}")


def artifact_source(
    artifact: dict[str, Any],
    destination: Path,
    project_root: Path,
    allow_local_sources: bool,
    source_hosts: set[str],
    redirect_hosts: set[str],
) -> tuple[int, str]:
    source_url = artifact.get("source_url")
    source_path = artifact.get("source_path")
    if (source_url is None) == (source_path is None):
        raise StoreError("each artifact needs exactly one of source_url or source_path")
    if source_url is not None:
        return download_artifact(
            require_text(source_url, "artifact source_url", 2048),
            destination,
            source_hosts,
            redirect_hosts,
        )
    if not allow_local_sources:
        raise StoreError("source_path is only accepted with --allow-local-sources")
    relative = Path(require_text(source_path, "artifact source_path", 512))
    if relative.is_absolute():
        raise StoreError("artifact source_path must be relative")
    return copy_local_artifact(project_root / relative, destination, project_root)


def build_store(
    project_root: Path,
    catalog_dir: Path,
    output: Path,
    generated_at: str,
    validator: Path | None,
    allow_local_sources: bool,
    source_hosts: set[str],
    redirect_hosts: set[str],
) -> dict[str, Any]:
    if output.exists():
        raise StoreError(f"output already exists: {output}")
    declarations = sorted(catalog_dir.glob("*.json"))
    stage = output.parent / f".{output.name}.stage-{os.getpid()}"
    if stage.exists():
        raise StoreError(f"staging path already exists: {stage}")
    packages_dir = stage / "v1" / "packages"
    packages_dir.mkdir(parents=True)
    published_plugins: list[dict[str, Any]] = []
    seen_plugins: set[str] = set()
    try:
        for declaration_path in declarations:
            source = load_json(declaration_path)
            if source.get("schema_version") != 1:
                raise StoreError(f"{declaration_path}: unsupported declaration schema")
            plugin_id = require_text(source.get("id"), "plugin id", 128)
            if PLUGIN_ID.fullmatch(plugin_id) is None or plugin_id in seen_plugins:
                raise StoreError(f"invalid or duplicate plugin id {plugin_id!r}")
            seen_plugins.add(plugin_id)
            releases = source.get("releases")
            if not isinstance(releases, list) or not releases:
                raise StoreError(f"{plugin_id} must publish at least one release")
            published_releases: list[dict[str, Any]] = []
            seen_versions: set[str] = set()
            for release in releases:
                if not isinstance(release, dict):
                    raise StoreError(f"{plugin_id} release must be an object")
                version = require_text(release.get("version"), "release version", 128)
                version_key = parse_semver(version, "release version")
                if version in seen_versions:
                    raise StoreError(f"duplicate {plugin_id} release {version}")
                seen_versions.add(version)
                artifacts = release.get("artifacts")
                if not isinstance(artifacts, list) or not artifacts:
                    raise StoreError(f"{plugin_id} {version} must contain artifacts")
                published_artifacts: list[dict[str, Any]] = []
                seen_platforms: set[str] = set()
                for artifact in artifacts:
                    if not isinstance(artifact, dict):
                        raise StoreError("artifact must be an object")
                    platform = require_text(artifact.get("platform"), "artifact platform", 64)
                    if PLATFORM_ID.fullmatch(platform) is None or platform in seen_platforms:
                        raise StoreError(f"invalid or duplicate platform {platform!r}")
                    seen_platforms.add(platform)
                    filename = f"{plugin_id}-{version}-{platform}.rfplugin"
                    destination = packages_dir / filename
                    size, sha256 = artifact_source(
                        artifact,
                        destination,
                        project_root,
                        allow_local_sources,
                        source_hosts,
                        redirect_hosts,
                    )
                    checked_optional_expectation(artifact, "expected_size", size)
                    checked_optional_expectation(artifact, "expected_sha256", sha256)
                    if validator is not None:
                        validate_package(validator, destination, plugin_id, version, platform)
                    published_artifacts.append(
                        {
                            "platform": platform,
                            "url": f"packages/{filename}",
                            "size": size,
                            "sha256": sha256,
                        }
                    )
                published_releases.append(
                    {
                        "version": version,
                        "published_at": require_text(
                            release.get("published_at"), "release published_at", 64
                        ),
                        "artifacts": sorted(
                            published_artifacts, key=lambda item: item["platform"]
                        ),
                        "_version_key": version_key,
                    }
                )
            published_releases.sort(key=lambda item: item.pop("_version_key"), reverse=True)
            plugin: dict[str, Any] = {
                "id": plugin_id,
                "name": require_text(source.get("name"), "plugin name", 128),
                "summary": require_text(source.get("summary"), "plugin summary", 1024),
                "license": require_text(source.get("license"), "plugin license", 128),
                "releases": published_releases,
            }
            if source.get("homepage") is not None:
                plugin["homepage"] = require_text(source["homepage"], "plugin homepage", 2048)
            published_plugins.append(plugin)
        index = {
            "schema_version": 1,
            "repository_id": "org.rackforge.official",
            "name": "RackForge Official",
            "generated_at": generated_at,
            "plugins": sorted(published_plugins, key=lambda item: item["id"]),
        }
        index_path = stage / "v1" / "index.json"
        index_path.write_text(
            json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        stage.replace(output)
        return index
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_args(arguments: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build RackForge Official Store")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--catalog-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--generated-at", default=utc_now())
    parser.add_argument("--validator", type=Path)
    parser.add_argument("--allow-local-sources", action="store_true")
    parser.add_argument(
        "--allowed-source-host",
        action="append",
        default=[],
        help="Additional HTTPS host accepted for reviewed source artifacts",
    )
    return parser.parse_args(arguments)


def main(arguments: Iterable[str] | None = None) -> int:
    args = parse_args(arguments)
    project_root = args.project_root.resolve()
    catalog_dir = (args.catalog_dir or project_root / "catalog" / "plugins").resolve()
    output = (args.output or project_root / "dist").resolve()
    source_hosts = DEFAULT_SOURCE_HOSTS | {host.lower() for host in args.allowed_source_host}
    redirect_hosts = DEFAULT_REDIRECT_HOSTS | source_hosts
    try:
        index = build_store(
            project_root,
            catalog_dir,
            output,
            args.generated_at,
            args.validator.resolve() if args.validator else None,
            args.allow_local_sources,
            source_hosts,
            redirect_hosts,
        )
    except StoreError as error:
        print(f"STORE_BUILD_ERROR {error}")
        return 1
    print(f"STORE_BUILT plugins={len(index['plugins'])} output={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
