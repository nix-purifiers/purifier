# SPDX-License-Identifier: MIT
# Pure evaluation counterpart of the native no-update source-graph check.
{ lib }:
{ selection, system }:
let
  problem = message: throw "purifier: JVM SDK ${message}";
  keysAre =
    value: keys:
    builtins.isAttrs value && builtins.attrNames value == builtins.sort builtins.lessThan keys;
  sourceValid =
    source:
    keysAre source [
      "type"
      "owner"
      "repo"
      "rev"
      "narHash"
    ]
    && source.type == "github"
    &&
      lib.all
        (
          name:
          builtins.isString source.${name}
          && builtins.match "[A-Za-z0-9_.-]+" source.${name} != null
          && !(builtins.elem source.${name} [
            "."
            ".."
          ])
        )
        [
          "owner"
          "repo"
        ]
    && builtins.isString source.rev
    && builtins.match "[0-9a-f]{40}" source.rev != null
    && builtins.isString source.narHash
    && builtins.match "sha256-[A-Za-z0-9+/]{43}=" source.narHash != null;
  source = selection.source;
  tree = builtins.fetchTree source;
  lockPath = tree.outPath + "/flake.lock";
  hasLock = builtins.pathExists lockPath;
  lock = if hasLock then builtins.fromJSON (builtins.readFile lockPath) else null;
  lockedSourceValid =
    value:
    builtins.isAttrs value && sourceValid (lib.filterAttrs (name: _: name != "lastModified") value);
  graphValid =
    lock != null
    && lock.version or null == 7
    && builtins.isAttrs (lock.nodes or null)
    && builtins.isString (lock.root or null)
    && builtins.hasAttr lock.root lock.nodes
    && lib.all (name: name == lock.root || lockedSourceValid (lock.nodes.${name}.locked or null)) (
      builtins.attrNames lock.nodes
    );
  # The immutable, fully specified reference avoids registry selection.
  flake = builtins.getFlake "github:${source.owner}/${source.repo}/${source.rev}?narHash=${source.narHash}";
  resolvedGraphAgrees =
    !hasLock
    || import ./jvm-sdk-source-graph.nix { inherit lib; } {
      inherit flake lock source;
    };
  selected = lib.attrByPath selection.attribute (problem "attribute is unavailable") flake;
  isAdapter = selection.selectionKind == "jvm-sdk-adapter-v1";
  sdk = if isAdapter then selected.sdk else selected;
  home =
    if isAdapter then selected.home else sdk.home or (problem "derivation must declare its home");
  manager = if isAdapter then selected.manager else null;
  identity = import ./jvm-sdk-identity.nix { inherit lib; } {
    inherit
      sdk
      home
      manager
      system
      ;
  };
  # Source code used during evaluation need not be an SDK runtime dependency.
  # Acquisition roots these live references alongside the four SDK contexts.
  sourceInputs = [
    tree.outPath
  ]
  ++ lib.optionals hasLock (
    map (
      name:
      (builtins.fetchTree (builtins.removeAttrs lock.nodes.${name}.locked [ "lastModified" ])).outPath
    ) (builtins.filter (name: name != lock.root) (builtins.attrNames lock.nodes))
  );
in
assert
  !(builtins ? currentSystem) && !(builtins ? currentTime)
  || problem "explicit selection requires pure evaluation";
assert
  keysAre selection [
    "id"
    "source"
    "selectionKind"
    "attribute"
  ]
  || problem "selection has unknown or missing fields";
assert builtins.isString selection.id && selection.id != "" || problem "selection id is invalid";
assert sourceValid source || problem "source must be an immutable GitHub revision and NAR";
assert
  builtins.elem selection.selectionKind [
    "derivation-v1"
    "jvm-sdk-adapter-v1"
  ]
  || problem "selection kind is unsupported";
assert
  builtins.isList selection.attribute
  && selection.attribute != [ ]
  && lib.all (key: builtins.isString key && key != "") selection.attribute
  || problem "attribute path is invalid";
assert tree.narHash == source.narHash || problem "source NAR differs";
assert (!hasLock || graphValid) || problem "source lock has unsupported or unlocked inputs";
assert
  (hasLock || builtins.attrNames (flake.inputs or { }) == [ ])
  || problem "source without a lock must have no external inputs";
assert resolvedGraphAgrees || problem "resolved source graph differs from its original lock";
assert
  (
    !isAdapter
    || (
      keysAre selected [
        "sdk"
        "home"
        "manager"
      ]
      && keysAre selected.manager [
        "executable"
        "runtimeHome"
      ]
    )
  )
  || problem "manager adapter has unknown or missing fields";
assert builtins.deepSeq {
  inherit (identity) payload identityHash managerIdentity;
} true;
{
  inherit
    sdk
    home
    manager
    identity
    ;
  inherit sourceInputs;
  closureInputs = identity.closureInputs ++ sourceInputs;
  sourceLock =
    if hasLock then
      {
        state = "present";
        sha256 = builtins.hashFile "sha256" lockPath;
      }
    else
      {
        state = "absent-no-external-inputs";
      };
  inherit (selection) id attribute selectionKind;
  inherit source system;
}
