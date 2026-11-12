# SPDX-License-Identifier: MIT
# The small bootstrap identity is independent of ecosystem lock schemas.
{ lib }:
args@{
  pkgs,
  source,
  repository,
  tool,
  nativeCommand,
  checksum,
  lockVersions,
  configuration ? null,
}:
let
  validData =
    value:
    value == null
    || builtins.isString value
    || builtins.isBool value
    || builtins.isInt value
    || (builtins.isList value && builtins.all validData value)
    || (builtins.isAttrs value && builtins.all validData (builtins.attrValues value));
  validConfiguration = value: builtins.isAttrs value && value != { } && validData value;
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
  }
  // lib.optionalAttrs (configuration != null) { inherit configuration; };
  manifest = pkgs.writeText "${tool}-implementation.json" (
    builtins.toJSON {
      bootstrapVersion = 1;
      inherit
        tool
        nativeCommand
        checksum
        lockVersions
        ;
      inherit configuration;
      source = identity;
      system = pkgs.stdenv.hostPlatform.system;
    }
  );
  # The runtime script may embed this helper's manifest path. Relabeling only
  # an outer join cannot rebind that script, so unknown recipe changes fail
  # rather than pretending the source's default constructor reproduces them.
  wrapPackage =
    package:
    let
      wrapped = pkgs.symlinkJoin {
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
      };
      changedRecipe = throw "${tool}: configure this package inside a source-owned constructor before wrapping it; an outer override cannot preserve its implementation identity";
      guard =
        value:
        value
        // {
          override =
            overrides:
            if !(package ? override) then
              changedRecipe
            else
              let
                changed = package.override overrides;
              in
              if changed.drvPath == package.drvPath then wrapPackage changed else changedRecipe;
          overrideAttrs =
            changes:
            let
              changed = value.overrideAttrs changes;
            in
            if changed.drvPath == value.drvPath then guard changed else changedRecipe;
        }
        // lib.optionalAttrs (value ? overrideDerivation) {
          overrideDerivation =
            changes:
            let
              changed = value.overrideDerivation changes;
            in
            if changed.drvPath == value.drvPath then guard changed else changedRecipe;
        };
    in
    guard wrapped;
  validLockedSource = (import ./implementation-source.nix).valid;
in
assert lib.assertMsg (
  configuration == null || validConfiguration configuration
) "purifier implementation configuration must be a nonempty object or null";
assert lib.assertMsg (
  builtins.length parts == 2
) "purifier implementation repository must be OWNER/REPO";
{
  inherit identity pin manifest;
  withoutIdentity = (import ./implementation.nix { inherit lib; }) (args // { source = { }; });
  withConfiguration =
    selected: (import ./implementation.nix { inherit lib; }) (args // { configuration = selected; });
  tool = ../../tools/implementation.py;
  sourceModel = ./implementation-source.nix;
  wrap = wrapPackage;
  # A builder never substitutes its own code for the project's pinned code.
  # Legacy locks remain readable until explicitly migrated.
  check =
    locked: value:
    if locked == null then
      value
    else if
      !builtins.isAttrs locked
      || !(builtins.elem (builtins.attrNames locked) [
        [
          "source"
          "tool"
          "version"
        ]
        [
          "configuration"
          "source"
          "tool"
          "version"
        ]
      ])
      || !builtins.isInt (locked.version or null)
      || (locked.version or null) != 1
      || (locked.tool or null) != tool
      || (locked.configuration or null) != configuration
      || (locked ? configuration && !validConfiguration locked.configuration)
      || identity == null
      || !validLockedSource (locked.source or null)
      || (locked.source.rev or null) != identity.rev
      || (locked.source.narHash or null) != identity.narHash
    then
      throw "${tool}: builder implementation differs from the project lock; use the pinned purifier source or explicitly run `${tool} self-update`"
    else
      value;
}
