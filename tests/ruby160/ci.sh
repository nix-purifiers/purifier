#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
set -euo pipefail
cd "$(dirname "$0")/../.."
evidence_dir=${1:?supply an owned evidence directory}
mkdir -p "$evidence_dir"
native=$(nix-build tests/ruby160/ci.nix -A native --no-out-link)
cp -R "$native" "$evidence_dir/native"
outputs=$(nix-build tests/ruby160/recipe-output-proof.nix --no-out-link)
cp -R "$outputs" "$evidence_dir/recipe-outputs"
extensions=$(nix-build tests/ruby160/recipe-native.nix -A extensions --no-out-link)
crc=$(nix-build tests/ruby160/recipe-native.nix -A crc --no-out-link)
cp -R "$extensions" "$evidence_dir/recipe-extensions"
cp -R "$crc" "$evidence_dir/recipe-crc"
git rev-parse HEAD > "$evidence_dir/source-revision"
git status --porcelain > "$evidence_dir/source-status"
