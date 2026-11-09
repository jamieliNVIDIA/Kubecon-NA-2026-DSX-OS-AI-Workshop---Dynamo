import hashlib
import json
from pathlib import Path

import tempfile
import unittest


from scripts.development.mx_cache import seed as seed_module


def fixture_snapshot(tmp_path):
    model = "example/model"
    revision = "a" * 40
    hf_home = tmp_path / "hf"
    repo = hf_home / "hub/models--example--model"
    snapshot = repo / "snapshots" / revision
    snapshot.mkdir(parents=True)
    (repo / "blobs").mkdir()
    payloads = {
        "model-00001-of-00001.safetensors": b"trusted weights",
        "model.safetensors.index.json": json.dumps({"weight_map": {"layer": "model-00001-of-00001.safetensors"}}).encode(),
        "config.json": b'{"model_type":"test"}',
        "assets/vocab.json": b'{"a":1}',
    }
    rows = []
    for name, payload in payloads.items():
        git = hashlib.sha1(b'blob ' + str(len(payload)).encode() + b'\0' + payload).hexdigest()
        row = {'type': 'file', 'oid': git, 'size': len(payload), 'path': name}
        blob_id = git
        if name.endswith('.safetensors'):
            blob_id = hashlib.sha256(payload).hexdigest()
            row['lfs'] = {'oid': blob_id, 'size': len(payload)}
        rows.append(row)
        blob = repo / "blobs" / blob_id
        blob.write_bytes(payload)
        target = snapshot / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(blob)
    spec = {
        "id": "fixture",
        "model": model,
        "revision": revision,
        "model_metadata_sha256": {name: hashlib.sha256(payloads[name]).hexdigest() for name in ("config.json", "model.safetensors.index.json")},
        "weight_files": 1,
        "weight_bytes": len(payloads["model-00001-of-00001.safetensors"]),
        "cache_limit_bytes": 96 * 1024 ** 3,
        "hf_manifest_json": json.dumps(rows),
        "hf_manifest_sha256": hashlib.sha256(json.dumps(rows).encode()).hexdigest(),
        "hf_manifest_entries": len(rows),
        "hf_manifest_url": 'https://huggingface.co/api/models/' + model + '/tree/' + revision + '?recursive=true&expand=false&limit=1000',
    }
    return spec, hf_home, snapshot, payloads



class SeedTests(unittest.TestCase):
    def test_complete_snapshot_publishes_with_internal_links_and_no_overwrite(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        spec, hf_home, source, payloads = fixture_snapshot(tmp_path)
        cache = tmp_path / "cache"
        receipt = seed_module.seed(spec, hf_home, cache, resource_gate=lambda *_: {"fixture": True})
        assert receipt["status"] == "passed"
        assert set(receipt["files"]) == set(payloads)
        destination = cache / "models--example--model"
        for name, payload in payloads.items():
            target = destination / "snapshots" / spec["revision"] / name
            assert target.read_bytes() == payload
            assert target.resolve().is_relative_to(destination.resolve())
        assert (destination / "refs/main").read_text().strip() == spec["revision"]
        assert not (cache / ".mx-staging-fixture").exists()
        with self.assertRaisesRegex(ValueError, "not fresh"):
            seed_module.seed(spec, hf_home, cache, resource_gate=lambda *_: {})


    def test_weight_corruption_is_not_published(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        spec, hf_home, source, payloads = fixture_snapshot(tmp_path)
        weight = source / "model-00001-of-00001.safetensors"
        weight.write_bytes(b"broken weights!")  # Same size, authoritative blob name stays unchanged.
        with self.assertRaisesRegex(ValueError, "checksum differs"):
            seed_module.seed(spec, hf_home, tmp_path / "cache", resource_gate=lambda *_: {})
        assert not (tmp_path / "cache/models--example--model").exists()
        assert not (tmp_path / "cache/mx-dev-cache-seed.json").exists()


    def test_metadata_change_and_symlink_escape_are_rejected(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        spec, hf_home, source, _ = fixture_snapshot(tmp_path)
        (source / "config.json").write_bytes(b'{"model_type":"evil"}')
        with self.assertRaisesRegex(ValueError, "metadata hash differs"):
            seed_module.seed(spec, hf_home, tmp_path / "cache", resource_gate=lambda *_: {})
        outside = tmp_path / "outside"
        outside.write_bytes(b"outside")
        target = source / "assets/vocab.json"
        target.unlink()
        target.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "escapes pinned repository"):
            seed_module.seed(spec, hf_home, tmp_path / "cache2", resource_gate=lambda *_: {})


    def test_weight_count_or_bytes_mismatch_rejected_before_copy(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        tmp_path = Path(temporary.name)
        spec, hf_home, _, _ = fixture_snapshot(tmp_path)
        spec["weight_bytes"] += 1
        with self.assertRaisesRegex(ValueError, "weight count/bytes differ"):
            seed_module.seed(spec, hf_home, tmp_path / "cache", resource_gate=lambda *_: {})
        assert not (tmp_path / "cache").exists()


if __name__ == "__main__":
    unittest.main()
