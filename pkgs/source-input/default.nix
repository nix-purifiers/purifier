# SPDX-License-Identifier: MIT
# Git is deliberately supplied by the caller during native capture. A pure
# replay adapter supplies its selected Git alongside this executable.
{ python3, writeShellScriptBin }:
writeShellScriptBin "purifier-source-input" ''
  exec ${python3}/bin/python3 ${../../tools/git_source.py} "$@"
''
