# SPDX-License-Identifier: MIT
# Private builder for fetchEntry's reproducible Git metadata.
{
  runCommand,
  python3,
  name,
  checkout,
  rev,
  commitObject,
  gitlinks,
  entryPath,
}:
runCommand name
  {
    nativeBuildInputs = [ python3 ];
    inherit
      checkout
      rev
      commitObject
      entryPath
      ;
    gitlinks = builtins.toJSON gitlinks;
    passAsFile = [ "gitlinks" ];
  }
  ''
    cp -R --no-preserve=ownership "$checkout" "$out"
    chmod -R u+w "$out"
    if ! printf '%s' "$commitObject" | base64 -d > "$TMPDIR/commit" 2> /dev/null; then
      echo "purifier: the git entry at path \"$entryPath\": its commitObject.object is not base64" >&2
      exit 1
    fi
    python3 ${./dot-git.py} "$out" "$TMPDIR/commit" "$gitlinksPath" "$rev" "$entryPath"
  ''
