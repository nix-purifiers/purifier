# SPDX-License-Identifier: MIT
# The small bootstrap identity is independent of ecosystem lock schemas.
{ lib }:
{
  pkgs,
  source,
  repository,
  tool,
  nativeCommand,
  checksum,
  lockVersions,
}:
let
  parts = lib.splitString "/" repository;
  identity =
    if (source.rev or null) == null || (source.narHash or null) == null || (source.dirty or false) then
      null
    else
      {
        type = "github";
        owner = builtins.elemAt parts 0;
        repo = builtins.elemAt parts 1;
        inherit (source) rev narHash;
      };
  pin = {
    version = 1;
    inherit tool;
    source = identity;
  };
  manifest = pkgs.writeText "${tool}-implementation.json" (
    builtins.toJSON {
      bootstrapVersion = 1;
      inherit
        tool
        nativeCommand
        checksum
        lockVersions
        ;
      source = identity;
      system = pkgs.stdenv.hostPlatform.system;
    }
  );
  wrapPackage =
    package:
    (pkgs.symlinkJoin {
      name = package.name;
      paths = [ package ];
      postBuild = ''
        mkdir -p "$out/share/purifier"
        ln -s ${manifest} "$out/share/purifier/implementation.json"
      '';
      meta = package.meta or { };
      passthru = (package.passthru or { }) // {
        implementation = pin;
      };
    })
    // lib.optionalAttrs (package ? override) {
      override = args: wrapPackage (package.override args);
    };
  validLockedSource =
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
in
assert lib.assertMsg (
  builtins.length parts == 2
) "purifier implementation repository must be OWNER/REPO";
{
  inherit identity pin manifest;
  tool = ../../tools/implementation.py;
  wrap = wrapPackage;
  # A builder never substitutes its own code for the project's pinned code.
  # Legacy locks remain readable until explicitly migrated.
  check =
    locked: value:
    if locked == null then
      value
    else if
      !builtins.isAttrs locked
      ||
        builtins.attrNames locked != [
          "source"
          "tool"
          "version"
        ]
      || (locked.version or null) != 1
      || (locked.tool or null) != tool
      || identity == null
      || !validLockedSource (locked.source or null)
      || (locked.source.rev or null) != identity.rev
      || (locked.source.narHash or null) != identity.narHash
    then
      throw "${tool}: builder implementation differs from the project lock; use the pinned purifier source or explicitly run `${tool} self-update`"
    else
      value;
}
