# SPDX-License-Identifier: MIT
# Compare native getFlake's resolved inputs with the source's original lock.
# getFlake alone can refresh a stale graph even during pure evaluation.
{ lib }:
{
  flake,
  lock,
  source,
}:
let
  problem = message: throw "purifier: JVM SDK source graph ${message}";
  nodes = lock.nodes;
  root = lock.root;
  node = name: nodes.${name} or (problem "references a missing node");
  # This only reads expected references in the existing lock. It never
  # constructs a flake or substitutes for the native resolver.
  follow =
    path: active:
    let
      marker = builtins.toJSON path;
    in
    if builtins.elem marker active then
      problem "contains a follows cycle"
    else
      atPath root path (active ++ [ marker ]);
  atPath =
    name: path: active:
    if path == [ ] then
      name
    else
      let
        edge = (node name).inputs.${builtins.head path} or (problem "has a dangling follows path");
        target = targetOf edge active;
      in
      atPath target (builtins.tail path) active;
  targetOf =
    edge: active:
    if builtins.isString edge then
      edge
    else if builtins.isList edge && lib.all builtins.isString edge then
      follow edge active
    else
      problem "has a malformed input reference";
  collect =
    name: seen:
    if builtins.elem name seen then
      seen
    else
      lib.foldl' (found: edge: collect (targetOf edge [ ]) found) (seen ++ [ name ]) (
        builtins.attrValues ((node name).inputs or { })
      );
  reachable = collect root [ ];
  rootDeclaration = (import ((builtins.fetchTree source).outPath + "/flake.nix")).inputs or { };
  declarationAgrees =
    name: declaration: edge: isRoot:
    if declaration ? follows then
      edge == (if declaration.follows == "" then [ ] else lib.splitString "/" declaration.follows)
    else
      builtins.isString edge
      && (
        let
          fields = builtins.removeAttrs declaration [
            "url"
            "inputs"
            "flake"
            "follows"
          ];
          hasSelector = isRoot || declaration ? url || fields != { };
          original = builtins.parseFlakeRef (declaration.url or "flake:${name}") // fields;
          expected = node edge;
          overrides = declaration.inputs or { };
        in
        (!hasSelector || original == (expected.original or { }))
        && (!(isRoot || declaration ? flake) || (declaration.flake or true) == (expected.flake or true))
        # Read explicit nested overrides from the current root declaration
        # as well. Their selectors are not inferred from the old lock.
        && lib.all (
          key:
          declarationAgrees key overrides.${key} (expected.inputs.${key}
            or (problem "omits a declared input override")
          ) false
        ) (builtins.attrNames overrides)
      );
  rootSelectorsAgree = lib.all (
    name:
    declarationAgrees name rootDeclaration.${name} ((node root).inputs.${name}
      or (problem "omits a declared root input")
    ) true
  ) (builtins.attrNames rootDeclaration);
  visit =
    name: actual: active:
    let
      expected = node name;
      expectedSource =
        if name == root then source else builtins.removeAttrs expected.locked [ "lastModified" ];
      tree = builtins.fetchTree expectedSource;
      info = actual.sourceInfo or actual;
      isFlake = if name == root then true else expected.flake or true;
      inputs = if isFlake then actual.inputs or { } else { };
      expectedInputs = expected.inputs or { };
      signature = {
        rev = info.rev or null;
        narHash = info.narHash or null;
        outPath = toString info.outPath;
        inputNames = builtins.attrNames inputs;
        flake = actual._type or null == "flake";
      };
      previous = lib.findFirst (entry: entry.name == name) null active;
    in
    assert
      (info.rev or null) == (tree.rev or null)
      && (info.narHash or null) == tree.narHash
      && toString info.outPath == toString tree.outPath
      || problem "resolved a different locked source";
    assert (actual._type or null == "flake") == isFlake || problem "changed an input's flake kind";
    assert
      builtins.attrNames inputs == builtins.attrNames expectedInputs
      || problem "added, removed or refreshed input edges";
    if previous != null then
      assert previous.signature == signature || problem "changed a repeated node's identity";
      true
    else
      lib.all (
        key:
        visit (targetOf expectedInputs.${key} [ ]) inputs.${key} (active ++ [ { inherit name signature; } ])
      ) (builtins.attrNames expectedInputs);
in
assert rootSelectorsAgree || problem "changed a root input selector";
assert
  builtins.sort builtins.lessThan reachable == builtins.attrNames nodes
  || problem "contains unreachable or refreshed lock nodes";
visit root flake [ ]
