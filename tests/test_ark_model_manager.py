# Copyright 2026 Arkapravo Ghosh

from __future__ import annotations

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "ark-model-manager.py"
SPEC = importlib.util.spec_from_file_location("ark_model_manager", SCRIPT)
assert SPEC and SPEC.loader
ark_model_manager = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ark_model_manager)


class FakeResponse(io.BytesIO):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        content_range: str | None = None,
    ) -> None:
        super().__init__(payload)
        self.status = status
        self.headers = {}
        if content_range:
            self.headers["Content-Range"] = content_range

    def getcode(self) -> int:
        return self.status

    def geturl(self) -> str:
        return "https://us.aws.cdn.hf.co/test-object"


class FakeOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.request = None

    def open(self, request, timeout=0):
        self.request = request
        return self.response


class MetadataManager(ark_model_manager.ArkModelManager):
    def __init__(self, root: Path, metadata: dict) -> None:
        super().__init__(root)
        self.metadata = metadata

    def inspect_repository(self, repository: str, revision: str = "main") -> dict:
        return self.metadata


class LocalInstallManager(ark_model_manager.ArkModelManager):
    def __init__(self, root: Path, payloads: dict[str, bytes]) -> None:
        super().__init__(root)
        self.payloads = payloads

    def _download_one(self, plan: dict, file_info: dict, stage: Path) -> Path:
        path = stage / file_info["filename"]
        path.write_bytes(self.payloads[file_info["filename"]])
        path.chmod(0o400)
        return path


def file_info(role: str, filename: str, payload: bytes) -> dict:
    return {
        "role": role,
        "filename": filename,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "etag": "test-etag",
    }


class ArkModelManagerTest(unittest.TestCase):
    def test_initialize_creates_owner_only_layout_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".arkbrowser"
            manager = ark_model_manager.ArkModelManager(root)
            manager.initialize()

            self.assertEqual(root.stat().st_mode & 0o777, 0o700)
            self.assertEqual(manager.database_path.stat().st_mode & 0o777, 0o600)
            for child in (
                "config",
                "data",
                "models/installed/huggingface",
                "models/staging",
                "models/trash",
                "cache/hub",
                "artifacts",
                "logs",
                "runtime",
            ):
                self.assertTrue((root / child).is_dir(), child)

            with sqlite3.connect(manager.database_path) as database:
                tables = {
                    row[0]
                    for row in database.execute(
                        "SELECT name FROM sqlite_master WHERE type='table'"
                    )
                }
            self.assertTrue(
                {"schema_meta", "download_jobs", "installed_models", "model_files"}
                <= tables
            )

    def test_preset_plan_resolves_revision_sizes_and_digests(self) -> None:
        preset = ark_model_manager.PRESETS["llama-3.2-vision-11b"]
        weight_name = preset["variants"]["Q4_K_M"]
        projector_name = preset["projector"]
        metadata = {
            "sha": "a" * 40,
            "cardData": {"license": "llama3.2"},
            "siblings": [
                {
                    "rfilename": weight_name,
                    "lfs": {"size": 101, "sha256": "1" * 64},
                },
                {
                    "rfilename": projector_name,
                    "lfs": {"size": 37, "sha256": "2" * 64},
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            manager = MetadataManager(Path(temporary) / ".arkbrowser", metadata)
            plan = manager.build_plan(
                "llama-3.2-vision-11b", None, None, None, "main"
            )

        self.assertEqual(plan["variant"], "Q4_K_M")
        self.assertEqual(plan["resolved_revision"], "a" * 40)
        self.assertEqual(plan["total_size_bytes"], 138)
        self.assertEqual([item["role"] for item in plan["files"]], ["weights", "projector"])
        self.assertEqual(
            plan["runtime_compatibility"],
            "pending_upstream_llama_cpp_mllama_support",
        )

    def test_download_resumes_only_with_matching_content_range(self) -> None:
        payload = b"0123456789abcdef"
        info = file_info("weights", "model.gguf", payload)
        plan = {
            "repository": "owner/repo",
            "resolved_revision": "b" * 40,
        }
        with tempfile.TemporaryDirectory() as temporary:
            stage = Path(temporary)
            (stage / "model.gguf.part").write_bytes(payload[:6])
            manager = ark_model_manager.ArkModelManager(stage)
            opener = FakeOpener(
                FakeResponse(
                    payload[6:],
                    status=206,
                    content_range=f"bytes 6-{len(payload) - 1}/{len(payload)}",
                )
            )
            manager.opener = opener

            result = manager._download_one(plan, info, stage)

            self.assertEqual(result.read_bytes(), payload)
            self.assertEqual(opener.request.get_header("Range"), "bytes=6-")
            self.assertFalse((stage / "model.gguf.part").exists())

    def test_install_writes_manifest_and_sqlite_rows_atomically(self) -> None:
        weights = b"small fake gguf weights"
        projector = b"small fake projector"
        files = [
            file_info("weights", "model.Q4_K_M.gguf", weights),
            file_info("projector", "mmproj.f16.gguf", projector),
        ]
        plan = {
            "schema_version": 1,
            "installation_id": "mdl_test",
            "display_name": "Test Vision Model",
            "source": "huggingface",
            "repository": "owner/repo",
            "requested_revision": "main",
            "resolved_revision": "c" * 40,
            "variant": "Q4_K_M",
            "license": "test-license",
            "runtime_compatibility": "verified",
            "capabilities": ["text", "image_input"],
            "files": files,
            "total_size_bytes": len(weights) + len(projector),
            "created_at": ark_model_manager.utc_now(),
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / ".arkbrowser"
            manager = LocalInstallManager(
                root,
                {
                    "model.Q4_K_M.gguf": weights,
                    "mmproj.f16.gguf": projector,
                },
            )
            destination = manager.install(plan, "test-license")

            manifest = json.loads(
                (destination / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(manifest["installation_id"], "mdl_test")
            self.assertTrue(manager.verify("mdl_test"))
            with sqlite3.connect(manager.database_path) as database:
                state = database.execute(
                    "SELECT state FROM download_jobs"
                ).fetchone()[0]
                file_count = database.execute(
                    "SELECT COUNT(*) FROM model_files WHERE model_id='mdl_test'"
                ).fetchone()[0]
            self.assertEqual(state, "completed")
            self.assertEqual(file_count, 2)

    def test_install_rejects_unacknowledged_license(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = LocalInstallManager(Path(temporary) / ".arkbrowser", {})
            plan = {
                "license": "llama3.2",
                "total_size_bytes": 0,
            }
            with self.assertRaisesRegex(RuntimeError, "License acknowledgement"):
                manager.install(plan, "wrong-license")

    def test_redirect_policy_allows_only_hugging_face_https_hosts(self) -> None:
        allowed = ark_model_manager.SafeHuggingFaceRedirectHandler._allowed
        self.assertTrue(allowed("https://huggingface.co/owner/repo"))
        self.assertTrue(allowed("https://us.aws.cdn.hf.co/object"))
        self.assertFalse(allowed("http://huggingface.co/owner/repo"))
        self.assertFalse(allowed("https://huggingface.co.example.com/object"))

    def test_model_paths_cannot_escape_ark_data_root(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "owner/name"):
            ark_model_manager.validate_repository("../outside/repo")
        with self.assertRaisesRegex(RuntimeError, "Unsafe GGUF filename"):
            ark_model_manager.validate_model_filename("../../outside.gguf")
        with self.assertRaisesRegex(RuntimeError, "Unsafe variant"):
            ark_model_manager.validate_component("../../outside", "variant")


if __name__ == "__main__":
    unittest.main()
