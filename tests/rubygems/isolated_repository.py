# SPDX-License-Identifier: MIT
"""Project and reuse real gems when Ruby's bundled base64 gem is unavailable."""
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ruby, projector, fixture, output = map(Path, sys.argv[1:])
with tempfile.TemporaryDirectory(prefix="isolated-rubygems-") as directory:
    root = Path(directory)
    home = root / "home"
    gems = root / "empty-gems"
    home.mkdir()
    gems.mkdir()
    env = os.environ.copy()
    for key in ("RUBYOPT", "RUBYLIB", "NIX_GEM_PATH"):
        env.pop(key, None)
    env.update(HOME=str(home), GEM_HOME=str(gems), GEM_PATH=str(gems))

    def run(*args):
        return subprocess.run(
            [str(ruby / "bin/ruby"), *map(str, args)],
            env=env, capture_output=True, text=True, timeout=60,
        )

    unavailable = run("-e", 'require "base64"')
    assert unavailable.returncode != 0 and "LoadError" in unavailable.stderr, unavailable

    def project(name, specification, success=True):
        request = root / (name + ".json")
        request.write_text(json.dumps(specification))
        repository = root / name
        catalog = root / (name + "-catalog.json")
        result = run(projector, request, repository, catalog)
        if success:
            assert result.returncode == 0, result.stderr
            return repository, json.loads(catalog.read_text()), catalog
        assert result.returncode != 0, result.stdout
        assert "input archive integrity mismatch" in result.stderr, result.stderr
        assert not repository.exists() and not catalog.exists()

    repository, catalog, catalog_path = project("original", {
        "identity": "isolated-stdlib-test", "archives": [str(fixture)],
    })
    assert catalog["packages"]
    for entry in catalog["packages"]:
        raw = (repository / entry["archive"]).read_bytes()
        expected = "sha512-" + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        assert entry["integrity"] == expected

    reused, reused_catalog, _ = project("reused", {
        "identity": "second-producer", "archives": [],
        "dependencies": [{"repository": str(repository), "catalog": str(catalog_path)}],
    })
    assert reused_catalog == catalog
    for entry in catalog["packages"]:
        assert (reused / entry["archive"]).read_bytes() == (repository / entry["archive"]).read_bytes()

    corrupt = root / "corrupt"
    shutil.copytree(repository, corrupt)
    archive = corrupt / catalog["packages"][0]["archive"]
    raw = bytearray(archive.read_bytes())
    raw[-1] ^= 1
    archive.write_bytes(raw)
    project("rejected", {
        "identity": "tampered-producer", "archives": [],
        "dependencies": [{"repository": str(corrupt), "catalog": str(catalog_path)}],
    }, success=False)
    output.write_text(json.dumps({
        "base64Unavailable": True,
        "archiveCount": len(catalog["packages"]),
        "independentSha512": True,
        "providedReuse": True,
        "tamperRejectedBeforeOutput": True,
    }, indent=2) + "\n")
