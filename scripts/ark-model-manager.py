#!/usr/bin/env python3
# Copyright 2026 Arkapravo Ghosh
"""Search, plan, download, verify, and organize Ark Browser GGUF models.

This is developer/bootstrap and verification tooling for Ark's native
in-browser Model Manager. It deliberately uses only Python's standard library
and the same canonical layout and SQLite concepts as the browser.
"""

from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import re
import shutil
import sqlite3
import sys
import time
from typing import Any, BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import uuid4


HF_ORIGIN = "https://huggingface.co"
CHUNK_SIZE = 8 * 1024 * 1024
PROGRESS_INTERVAL_SECONDS = 1.0
MIN_DISK_RESERVE_BYTES = 1024 * 1024 * 1024
HF_REPOSITORY_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*$"
)
SAFE_COMPONENT_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

PRESETS: dict[str, dict[str, Any]] = {
    "qwen2.5-vl-7b-instruct": {
        "display_name": "Qwen2.5-VL 7B Instruct",
        "repository": "ggml-org/Qwen2.5-VL-7B-Instruct-GGUF",
        "revision": "main",
        "license": "apache-2.0",
        "runtime_compatibility": "verified_compatible",
        "projector": "mmproj-Qwen2.5-VL-7B-Instruct-Q8_0.gguf",
        "variants": {
            "Q4_K_M": "Qwen2.5-VL-7B-Instruct-Q4_K_M.gguf",
        },
        "recommended_variant": "Q4_K_M",
        "capabilities": ["text", "image_input"],
    },
    "llama-3.2-vision-11b": {
        "display_name": "Llama 3.2 Vision 11B Instruct",
        "repository": "leafspark/Llama-3.2-11B-Vision-Instruct-GGUF",
        "revision": "main",
        "license": "llama3.2",
        "runtime_compatibility": "pending_upstream_llama_cpp_mllama_support",
        "projector": "Llama-3.2-11B-Vision-Instruct-mmproj.f16.gguf",
        "variants": {
            "Q4_K_M": "Llama-3.2-11B-Vision-Instruct.Q4_K_M.gguf",
            "Q8_0": "Llama-3.2-11B-Vision-Instruct.Q8_0.gguf",
            "F16": "Llama-3.2-11B-Vision-Instruct.f16.gguf",
        },
        "recommended_variant": "Q4_K_M",
        "capabilities": ["text", "image_input"],
    }
}


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    raise AssertionError("unreachable")


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def validate_repository(repository: str) -> str:
    if not HF_REPOSITORY_PATTERN.fullmatch(repository):
        raise RuntimeError("Repository must use the Hugging Face owner/name format")
    return repository


def validate_component(value: str, label: str) -> str:
    if not SAFE_COMPONENT_PATTERN.fullmatch(value):
        raise RuntimeError(f"Unsafe {label}: {value}")
    return value


def validate_model_filename(filename: str) -> str:
    path = PurePosixPath(filename)
    if (
        not filename
        or "\\" in filename
        or path.is_absolute()
        or any(part in ("", ".", "..") for part in path.parts)
        or any(not SAFE_COMPONENT_PATTERN.fullmatch(part) for part in path.parts)
        or not filename.lower().endswith(".gguf")
    ):
        raise RuntimeError(f"Unsafe GGUF filename: {filename}")
    return filename


class SafeHuggingFaceRedirectHandler(HTTPRedirectHandler):
    """Rejects non-HTTPS/non-Hugging-Face redirects and strips credentials."""

    @staticmethod
    def _allowed(url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        return parsed.scheme == "https" and (
            host == "huggingface.co"
            or host.endswith(".huggingface.co")
            or host == "hf.co"
            or host.endswith(".hf.co")
        )

    def redirect_request(
        self,
        request: Request,
        fp: BinaryIO,
        code: int,
        message: str,
        headers: Any,
        new_url: str,
    ) -> Request | None:
        if not self._allowed(new_url):
            raise RuntimeError(f"Blocked unsafe Hugging Face redirect: {new_url}")
        redirected = super().redirect_request(
            request, fp, code, message, headers, new_url
        )
        if redirected is not None:
            old_host = (urlparse(request.full_url).hostname or "").lower()
            new_host = (urlparse(new_url).hostname or "").lower()
            if old_host != new_host:
                redirected.remove_header("Authorization")
        return redirected


class ArkModelManager:
    def __init__(self, root: Path, token: str | None = None) -> None:
        self.root = Path(os.path.abspath(os.path.expanduser(root)))
        self.token = token
        self.opener = build_opener(SafeHuggingFaceRedirectHandler())
        self.config_dir = self.root / "config"
        self.data_dir = self.root / "data"
        self.models_dir = self.root / "models"
        self.installed_dir = self.models_dir / "installed" / "huggingface"
        self.staging_dir = self.models_dir / "staging"
        self.trash_dir = self.models_dir / "trash"
        self.database_path = self.data_dir / "models.sqlite3"

    def initialize(self) -> None:
        directories = (
            self.root,
            self.config_dir,
            self.data_dir,
            self.installed_dir,
            self.staging_dir,
            self.trash_dir,
            self.root / "cache" / "hub",
            self.root / "cache" / "context",
            self.root / "cache" / "thumbnails",
            self.root / "artifacts",
            self.root / "logs",
            self.root / "runtime",
        )
        for directory in directories:
            self._make_private_directory(directory)

        with self._database() as database:
            database.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_meta(
                  key TEXT PRIMARY KEY NOT NULL,
                  value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_meta(key,value)
                  VALUES('schema_version','1');

                CREATE TABLE IF NOT EXISTS download_jobs(
                  id TEXT PRIMARY KEY NOT NULL,
                  repository TEXT NOT NULL,
                  requested_revision TEXT NOT NULL,
                  resolved_revision TEXT NOT NULL,
                  variant TEXT NOT NULL,
                  state TEXT NOT NULL,
                  bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                  bytes_total INTEGER NOT NULL,
                  stage_path TEXT NOT NULL,
                  error TEXT NOT NULL DEFAULT '',
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  UNIQUE(repository,resolved_revision,variant)
                );

                CREATE TABLE IF NOT EXISTS installed_models(
                  id TEXT PRIMARY KEY NOT NULL,
                  source TEXT NOT NULL,
                  repository TEXT NOT NULL,
                  requested_revision TEXT NOT NULL,
                  resolved_revision TEXT NOT NULL,
                  variant TEXT NOT NULL,
                  display_name TEXT NOT NULL,
                  license TEXT NOT NULL,
                  runtime_compatibility TEXT NOT NULL,
                  manifest_path TEXT NOT NULL,
                  installed_at TEXT NOT NULL,
                  UNIQUE(repository,resolved_revision,variant)
                );

                CREATE TABLE IF NOT EXISTS model_files(
                  model_id TEXT NOT NULL REFERENCES installed_models(id)
                    ON DELETE CASCADE,
                  role TEXT NOT NULL,
                  filename TEXT NOT NULL,
                  size_bytes INTEGER NOT NULL,
                  sha256 TEXT NOT NULL,
                  PRIMARY KEY(model_id,role)
                );
                """
            )
        self.database_path.chmod(0o600)

    def _make_private_directory(self, path: Path) -> None:
        try:
            relative = path.relative_to(self.root)
        except ValueError as error:
            raise RuntimeError(f"Path escapes Ark data root: {path}") from error

        current = self.root
        for component in (Path(), *relative.parents[::-1], relative):
            candidate = self.root if component == Path() else self.root / component
            if candidate.exists() and candidate.is_symlink():
                raise RuntimeError(f"Refusing symlink in Ark data path: {candidate}")
            candidate.mkdir(exist_ok=True, mode=0o700)
            candidate.chmod(0o700)
            current = candidate
        if current != path:
            raise RuntimeError(f"Failed to resolve Ark data directory: {path}")

    def _connect(self) -> sqlite3.Connection:
        self._make_private_directory(self.data_dir)
        database = sqlite3.connect(self.database_path)
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA journal_mode=WAL")
        database.row_factory = sqlite3.Row
        return database

    @contextmanager
    def _database(self):
        database = self._connect()
        try:
            with database:
                yield database
        finally:
            database.close()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Ark-Browser-Model-Manager/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _read_json(self, url: str) -> dict[str, Any] | list[Any]:
        request = Request(url, headers=self._headers())
        with closing(self.opener.open(request, timeout=30)) as response:
            if not SafeHuggingFaceRedirectHandler._allowed(response.geturl()):
                raise RuntimeError(f"Unexpected response origin: {response.geturl()}")
            payload = response.read(16 * 1024 * 1024 + 1)
            if len(payload) > 16 * 1024 * 1024:
                raise RuntimeError("Hugging Face metadata response exceeded 16 MiB")
            return json.loads(payload)

    def search(self, query: str, limit: int) -> list[dict[str, Any]]:
        params = urlencode(
            {
                "search": query,
                "filter": "gguf",
                "sort": "downloads",
                "direction": "-1",
                "limit": limit,
            }
        )
        result = self._read_json(f"{HF_ORIGIN}/api/models?{params}")
        if not isinstance(result, list):
            raise RuntimeError("Unexpected Hugging Face search response")
        return [item for item in result if isinstance(item, dict)]

    def inspect_repository(
        self, repository: str, revision: str = "main"
    ) -> dict[str, Any]:
        validate_repository(repository)
        validate_component(revision, "revision")
        safe_repository = quote(repository, safe="/")
        safe_revision = quote(revision, safe="")
        result = self._read_json(
            f"{HF_ORIGIN}/api/models/{safe_repository}/revision/"
            f"{safe_revision}?blobs=true"
        )
        if not isinstance(result, dict) or not result.get("sha"):
            raise RuntimeError("Repository metadata did not include a revision SHA")
        return result

    @staticmethod
    def _file_metadata(metadata: dict[str, Any], filename: str) -> dict[str, Any]:
        validate_model_filename(filename)
        for sibling in metadata.get("siblings", []):
            if sibling.get("rfilename") != filename:
                continue
            lfs = sibling.get("lfs") or {}
            size = lfs.get("size") or sibling.get("size")
            digest = lfs.get("sha256")
            if not isinstance(size, int) or size <= 0 or not isinstance(digest, str):
                raise RuntimeError(
                    f"{filename} lacks authoritative LFS size/SHA-256 metadata"
                )
            if not re.fullmatch(r"[0-9a-fA-F]{64}", digest):
                raise RuntimeError(f"{filename} has an invalid SHA-256 digest")
            return {
                "filename": filename,
                "size_bytes": size,
                "sha256": digest.lower(),
                "etag": sibling.get("blobId", ""),
            }
        raise RuntimeError(f"Repository does not contain {filename}")

    def build_plan(
        self,
        target: str,
        variant: str | None,
        weights: str | None,
        projector: str | None,
        revision: str,
    ) -> dict[str, Any]:
        preset = PRESETS.get(target)
        if preset:
            selected_variant = variant or preset["recommended_variant"]
            if selected_variant not in preset["variants"]:
                choices = ", ".join(preset["variants"])
                raise RuntimeError(f"Unknown variant {selected_variant}; choose {choices}")
            repository = preset["repository"]
            requested_revision = preset["revision"]
            weights_filename = preset["variants"][selected_variant]
            projector_filename = preset["projector"]
            display_name = preset["display_name"]
            runtime_compatibility = preset["runtime_compatibility"]
            capabilities = preset["capabilities"]
            expected_license = preset["license"]
        else:
            if not weights:
                raise RuntimeError(
                    "A repository target requires --weights and optional --mmproj"
                )
            repository = target
            requested_revision = revision
            weights_filename = weights
            projector_filename = projector
            selected_variant = variant or "custom"
            display_name = repository.rsplit("/", 1)[-1]
            runtime_compatibility = "unverified"
            capabilities = ["text"] + (["image_input"] if projector else [])
            expected_license = "unknown"

        validate_repository(repository)
        validate_component(requested_revision, "revision")
        validate_component(selected_variant, "variant")
        metadata = self.inspect_repository(repository, requested_revision)
        card_data = metadata.get("cardData") or {}
        license_id = card_data.get("license") or expected_license
        if not isinstance(license_id, str):
            raise RuntimeError("Repository metadata returned an invalid license")
        files = [
            {
                "role": "weights",
                **self._file_metadata(metadata, weights_filename),
            }
        ]
        if projector_filename:
            files.append(
                {
                    "role": "projector",
                    **self._file_metadata(metadata, projector_filename),
                }
            )
        resolved_revision = metadata["sha"]
        if not re.fullmatch(r"[0-9a-fA-F]{40,64}", resolved_revision):
            raise RuntimeError("Repository metadata returned an invalid revision SHA")
        total_size = sum(item["size_bytes"] for item in files)
        installation_seed = (
            f"huggingface:{repository}:{resolved_revision}:{selected_variant}"
        )
        installation_id = "mdl_" + hashlib.sha256(
            installation_seed.encode("utf-8")
        ).hexdigest()[:24]
        return {
            "schema_version": 1,
            "installation_id": installation_id,
            "display_name": display_name,
            "source": "huggingface",
            "repository": repository,
            "requested_revision": requested_revision,
            "resolved_revision": resolved_revision,
            "variant": selected_variant,
            "license": license_id,
            "runtime_compatibility": runtime_compatibility,
            "capabilities": capabilities,
            "files": files,
            "total_size_bytes": total_size,
            "created_at": utc_now(),
        }

    def _download_url(self, plan: dict[str, Any], filename: str) -> str:
        repository = quote(plan["repository"], safe="/")
        revision = quote(plan["resolved_revision"], safe="")
        file_path = quote(filename, safe="/")
        return f"{HF_ORIGIN}/{repository}/resolve/{revision}/{file_path}"

    def _download_one(
        self, plan: dict[str, Any], file_info: dict[str, Any], stage: Path
    ) -> Path:
        final_path = stage / file_info["filename"]
        partial_path = final_path.with_name(final_path.name + ".part")
        expected_size = file_info["size_bytes"]

        if final_path.is_symlink() or partial_path.is_symlink():
            raise RuntimeError(f"Refusing symlink in model staging area: {final_path}")
        self._make_private_directory(final_path.parent)

        if final_path.exists():
            if self._verify_file(final_path, file_info):
                return final_path
            raise RuntimeError(f"Existing staged file failed verification: {final_path}")

        offset = partial_path.stat().st_size if partial_path.exists() else 0
        if offset > expected_size:
            raise RuntimeError(f"Partial file is larger than expected: {partial_path}")

        headers = self._headers()
        headers["Accept"] = "application/octet-stream"
        if offset:
            headers["Range"] = f"bytes={offset}-"
        request = Request(
            self._download_url(plan, file_info["filename"]), headers=headers
        )

        with closing(self.opener.open(request, timeout=120)) as response:
            final_url = response.geturl()
            if not SafeHuggingFaceRedirectHandler._allowed(final_url):
                raise RuntimeError(f"Unexpected download origin: {final_url}")
            status = getattr(response, "status", response.getcode())
            if offset and status == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith(f"bytes {offset}-"):
                    raise RuntimeError(
                        f"Invalid resume Content-Range for {file_info['filename']}"
                    )
                mode = "ab"
            elif status == 200:
                offset = 0
                mode = "wb"
            else:
                raise RuntimeError(
                    f"Unexpected HTTP {status} for {file_info['filename']}"
                )

            downloaded = offset
            last_report = 0.0
            with partial_path.open(mode) as output:
                while True:
                    chunk = response.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    downloaded += len(chunk)
                    now = time.monotonic()
                    if now - last_report >= PROGRESS_INTERVAL_SECONDS:
                        percent = downloaded * 100 / expected_size
                        print(
                            f"  {file_info['role']}: {human_bytes(downloaded)} / "
                            f"{human_bytes(expected_size)} ({percent:.1f}%)",
                            flush=True,
                        )
                        last_report = now
                output.flush()
                os.fsync(output.fileno())

        if partial_path.stat().st_size != expected_size:
            raise RuntimeError(
                f"Size mismatch for {file_info['filename']}: "
                f"expected {expected_size}, got {partial_path.stat().st_size}"
            )
        print(f"  verifying {file_info['role']} SHA-256...", flush=True)
        if not self._verify_file(partial_path, file_info):
            raise RuntimeError(f"SHA-256 mismatch for {file_info['filename']}")
        os.replace(partial_path, final_path)
        final_path.chmod(0o400)
        return final_path

    @staticmethod
    def _verify_file(path: Path, file_info: dict[str, Any]) -> bool:
        if not path.is_file() or path.stat().st_size != file_info["size_bytes"]:
            return False
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest().lower() == file_info["sha256"].lower()

    def install(self, plan: dict[str, Any], accepted_license: str) -> Path:
        self.initialize()
        license_id = plan["license"]
        if license_id == "unknown" or accepted_license != license_id:
            raise RuntimeError(
                f"License acknowledgement required. Re-run with "
                f"--accept-license {license_id} after reviewing the repository."
            )

        required = plan["total_size_bytes"] + max(
            MIN_DISK_RESERVE_BYTES, plan["total_size_bytes"] // 20
        )
        free = shutil.disk_usage(self.root).free
        if free < required:
            raise RuntimeError(
                f"Not enough free space: need {human_bytes(required)}, "
                f"have {human_bytes(free)}"
            )

        destination = (
            self.installed_dir
            / plan["repository"]
            / plan["resolved_revision"]
            / plan["variant"]
        )
        if destination.exists():
            manifest = destination / "manifest.json"
            if manifest.is_file():
                print(f"Already installed: {destination}")
                return destination
            raise RuntimeError(f"Installation directory exists without manifest: {destination}")

        with self._database() as database:
            row = database.execute(
                "SELECT id,stage_path FROM download_jobs WHERE repository=? "
                "AND resolved_revision=? AND variant=?",
                (plan["repository"], plan["resolved_revision"], plan["variant"]),
            ).fetchone()
            job_id = row["id"] if row else "dl_" + uuid4().hex
            stage = Path(row["stage_path"]) if row else self.staging_dir / job_id
            self._make_private_directory(stage)
            now = utc_now()
            database.execute(
                "INSERT INTO download_jobs(id,repository,requested_revision,"
                "resolved_revision,variant,state,bytes_total,stage_path,"
                "created_at,updated_at) VALUES(?,?,?,?,?,'downloading',?,?,?,?) "
                "ON CONFLICT(repository,resolved_revision,variant) DO UPDATE SET "
                "state='downloading',error='',updated_at=excluded.updated_at",
                (
                    job_id,
                    plan["repository"],
                    plan["requested_revision"],
                    plan["resolved_revision"],
                    plan["variant"],
                    plan["total_size_bytes"],
                    str(stage),
                    now,
                    now,
                ),
            )

        write_json_atomic(stage / "download.json", {"job_id": job_id, **plan})
        try:
            downloaded = 0
            for file_info in plan["files"]:
                downloaded_path = self._download_one(plan, file_info, stage)
                downloaded += downloaded_path.stat().st_size
                with self._database() as database:
                    database.execute(
                        "UPDATE download_jobs SET bytes_downloaded=?,updated_at=? "
                        "WHERE id=?",
                        (downloaded, utc_now(), job_id),
                    )

            manifest = {
                **plan,
                "installed_at": utc_now(),
                "model_root": ".",
            }
            write_json_atomic(stage / "manifest.json", manifest)
            self._make_private_directory(destination.parent)
            os.replace(stage, destination)
            (destination / "manifest.json").chmod(0o600)

            with self._database() as database:
                database.execute("BEGIN IMMEDIATE")
                database.execute(
                    "INSERT OR REPLACE INTO installed_models(id,source,repository,"
                    "requested_revision,resolved_revision,variant,display_name,"
                    "license,runtime_compatibility,manifest_path,installed_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        plan["installation_id"],
                        plan["source"],
                        plan["repository"],
                        plan["requested_revision"],
                        plan["resolved_revision"],
                        plan["variant"],
                        plan["display_name"],
                        plan["license"],
                        plan["runtime_compatibility"],
                        str(destination / "manifest.json"),
                        manifest["installed_at"],
                    ),
                )
                database.execute(
                    "DELETE FROM model_files WHERE model_id=?",
                    (plan["installation_id"],),
                )
                database.executemany(
                    "INSERT INTO model_files(model_id,role,filename,size_bytes,sha256) "
                    "VALUES(?,?,?,?,?)",
                    [
                        (
                            plan["installation_id"],
                            item["role"],
                            item["filename"],
                            item["size_bytes"],
                            item["sha256"],
                        )
                        for item in plan["files"]
                    ],
                )
                database.execute(
                    "UPDATE download_jobs SET state='completed',"
                    "bytes_downloaded=bytes_total,stage_path=?,updated_at=? "
                    "WHERE id=?",
                    (str(destination), utc_now(), job_id),
                )
            return destination
        except KeyboardInterrupt as error:
            with self._database() as database:
                database.execute(
                    "UPDATE download_jobs SET state=?,error=?,updated_at=? WHERE id=?",
                    ("paused", str(error)[:1000], utc_now(), job_id),
                )
            raise
        except Exception as error:
            with self._database() as database:
                database.execute(
                    "UPDATE download_jobs SET state=?,error=?,updated_at=? WHERE id=?",
                    ("failed", str(error)[:1000], utc_now(), job_id),
                )
            raise

    def list_installed(self) -> list[sqlite3.Row]:
        self.initialize()
        with self._database() as database:
            return database.execute(
                "SELECT id,display_name,repository,resolved_revision,variant,"
                "runtime_compatibility,manifest_path,installed_at "
                "FROM installed_models ORDER BY installed_at DESC"
            ).fetchall()

    def verify(self, model_id: str | None) -> bool:
        self.initialize()
        with self._database() as database:
            query = (
                "SELECT id,manifest_path FROM installed_models WHERE id=?"
                if model_id
                else "SELECT id,manifest_path FROM installed_models ORDER BY installed_at"
            )
            rows = database.execute(query, (model_id,) if model_id else ()).fetchall()
        if model_id and not rows:
            raise RuntimeError(f"Unknown model installation: {model_id}")
        all_valid = True
        for row in rows:
            manifest_path = Path(row["manifest_path"])
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            valid = all(
                self._verify_file(manifest_path.parent / item["filename"], item)
                for item in manifest["files"]
            )
            print(f"{row['id']}: {'verified' if valid else 'FAILED'}")
            all_valid = all_valid and valid
        return all_valid


def print_plan(plan: dict[str, Any], root: Path) -> None:
    print(f"Model:       {plan['display_name']}")
    print(f"Repository:  {plan['repository']}")
    print(f"Revision:    {plan['resolved_revision']}")
    print(f"Variant:     {plan['variant']}")
    print(f"License:     {plan['license']}")
    print(f"Compatibility: {plan['runtime_compatibility']}")
    for item in plan["files"]:
        print(
            f"  {item['role']:9} {human_bytes(item['size_bytes']):>10}  "
            f"{item['filename']}"
        )
        print(f"             sha256 {item['sha256']}")
    print(f"Total:       {human_bytes(plan['total_size_bytes'])}")
    print(f"Install root:{root / 'models' / 'installed' / 'huggingface'}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path.home() / ".arkbrowser",
        help="Ark data root (default: $HOME/.arkbrowser; intended for tests only)",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("init", help="Create Ark's owner-only data layout and DB")

    search = subcommands.add_parser("search", help="Search Hugging Face GGUF models")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10, choices=range(1, 51))

    inspect = subcommands.add_parser("inspect", help="List GGUF files in a repository")
    inspect.add_argument("repository")
    inspect.add_argument("--revision", default="main")

    for name, help_text in (
        ("plan", "Resolve a download plan without downloading model bytes"),
        ("install", "Download, verify, and atomically install a model"),
    ):
        command = subcommands.add_parser(name, help=help_text)
        command.add_argument("target", help="Preset name or owner/repository")
        command.add_argument("--variant")
        command.add_argument("--weights")
        command.add_argument("--mmproj")
        command.add_argument("--revision", default="main")
        if name == "install":
            command.add_argument(
                "--accept-license",
                required=True,
                help="Exact license identifier shown by the plan command",
            )

    subcommands.add_parser("list", help="List installed models")
    verify = subcommands.add_parser("verify", help="Verify installed file digests")
    verify.add_argument("model_id", nargs="?")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    manager = ArkModelManager(args.root, os.environ.get("HF_TOKEN"))
    try:
        if args.command == "init":
            manager.initialize()
            print(f"Initialized {manager.root}")
        elif args.command == "search":
            results = manager.search(args.query, args.limit)
            for item in results:
                print(
                    f"{item.get('id', '(unknown)')}  "
                    f"downloads={item.get('downloads', 0)}  "
                    f"private={item.get('private', False)}  "
                    f"gated={item.get('gated', False)}"
                )
        elif args.command == "inspect":
            metadata = manager.inspect_repository(args.repository, args.revision)
            print(f"Repository: {metadata.get('id', args.repository)}")
            print(f"Revision:   {metadata['sha']}")
            print(f"License:    {(metadata.get('cardData') or {}).get('license', 'unknown')}")
            for sibling in metadata.get("siblings", []):
                if str(sibling.get("rfilename", "")).lower().endswith(".gguf"):
                    lfs = sibling.get("lfs") or {}
                    print(
                        f"  {human_bytes(lfs.get('size') or sibling.get('size') or 0):>10}  "
                        f"{sibling['rfilename']}"
                    )
        elif args.command in ("plan", "install"):
            plan = manager.build_plan(
                args.target,
                args.variant,
                args.weights,
                args.mmproj,
                args.revision,
            )
            print_plan(plan, manager.root)
            if args.command == "install":
                print("Downloading and verifying model files...")
                destination = manager.install(plan, args.accept_license)
                print(f"Installed successfully: {destination}")
        elif args.command == "list":
            rows = manager.list_installed()
            if not rows:
                print("No models installed.")
            for row in rows:
                print(
                    f"{row['id']}  {row['display_name']}  {row['variant']}  "
                    f"{row['runtime_compatibility']}"
                )
                print(f"  {row['manifest_path']}")
        elif args.command == "verify":
            return 0 if manager.verify(args.model_id) else 1
        return 0
    except HTTPError as error:
        print(f"Hugging Face returned HTTP {error.code}: {error.reason}", file=sys.stderr)
    except URLError as error:
        print(f"Network error: {error.reason}", file=sys.stderr)
    except (RuntimeError, OSError, ValueError, sqlite3.Error) as error:
        print(f"Error: {error}", file=sys.stderr)
    except KeyboardInterrupt:
        print("Download paused. Run the same install command to resume.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
