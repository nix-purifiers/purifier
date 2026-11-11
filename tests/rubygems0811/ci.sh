#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
cd "$(dirname "$0")/../.."
evidence_dir=${1:?supply an owned evidence directory}
mkdir -p "$evidence_dir"
attestation=$(nix-build tests/rubygems0811/ci.nix -A attestation --no-out-link)
identity=$(python3 - "$attestation/consumer-sdk.json" <<'PY'
import base64, hashlib, json, sys
from pathlib import Path
raw = Path(sys.argv[1]).read_bytes()
document = json.loads(raw)
canonical = json.dumps(document,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()
assert raw == canonical+b'\n'
print('sha256-'+base64.b64encode(hashlib.sha256(canonical).digest()).decode())
PY
)
native=$(nix-build tests/rubygems0811/ci.nix -A native --argstr nativeSdkIdentity "$identity" --no-out-link)
fallback=$(nix-build tests/rubygems0811/ci.nix -A nativeFallback --argstr nativeSdkIdentity "$identity" --no-out-link)
crc=$(nix-build tests/rubygems0811/ci.nix -A crc --no-out-link)
cp -R "$attestation" "$evidence_dir/attestation"
cp -R "$native" "$evidence_dir/native"
cp -R "$fallback" "$evidence_dir/native-yaml-fallback"
cp -R "$crc" "$evidence_dir/crc"
printf '%s\n' "$identity" > "$evidence_dir/native-sdk-identity"
git rev-parse HEAD > "$evidence_dir/source-revision"
git status --porcelain > "$evidence_dir/source-status"
