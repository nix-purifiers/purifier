# SPDX-License-Identifier: MIT
# Verify an immutable implementation before evaluating its flake, retaining
# revision metadata that would be lost by reopening only its store path.
let
  valid =
    locked:
    builtins.isAttrs locked
    && builtins.isString (locked.rev or null)
    && builtins.match "[0-9a-f]{40}" locked.rev != null
    && builtins.isString (locked.narHash or null)
    && builtins.match "sha256-[A-Za-z0-9+/]{43}=" locked.narHash != null
    && (
      if (locked.type or null) == "github" then
        builtins.attrNames locked == [
          "narHash"
          "owner"
          "repo"
          "rev"
          "type"
        ]
        &&
          builtins.all
            (
              key:
              builtins.isString locked.${key} && builtins.match "[A-Za-z0-9][A-Za-z0-9_.-]*" locked.${key} != null
            )
            [
              "owner"
              "repo"
            ]
      else if (locked.type or null) == "git" then
        builtins.attrNames locked == [
          "narHash"
          "rev"
          "type"
          "url"
        ]
        && builtins.isString locked.url
        && builtins.match "(https|ssh|file)://[^?#[:cntrl:]]+" locked.url != null
      else
        false
    );
  resolve =
    source:
    if !valid source then
      throw "purifier: invalid implementation source"
    else
      let
        reference =
          if source.type == "github" then
            "github:${source.owner}/${source.repo}/${source.rev}"
          else
            "git+${source.url}?rev=${source.rev}";
        tree = builtins.fetchTree source;
      in
      {
        inherit tree reference;
        flake = builtins.seq tree.outPath (builtins.getFlake reference);
      };
in
{
  inherit valid resolve;
}
