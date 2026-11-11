#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
cd "$(dirname "$0")/../.."
evidence_dir=${1:?supply an owned evidence directory}
mkdir -p "$evidence_dir"
native=$(nix-build tests/ruby160/ci.nix -A native --no-out-link)
cp -R "$native" "$evidence_dir/native"
git rev-parse HEAD > "$evidence_dir/source-revision"
git status --porcelain > "$evidence_dir/source-status"
