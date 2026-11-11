#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
cd "$(dirname "$0")/../.."
evidence_dir=${1:?supply an owned evidence directory}
mkdir -p "$evidence_dir"
result=$(nix-build tests/ruby160/diagnostic.nix --no-out-link)
cp -R "$result" "$evidence_dir/outputs"
git rev-parse HEAD > "$evidence_dir/source-revision"
git status --porcelain > "$evidence_dir/source-status"
