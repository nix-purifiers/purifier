# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  source = {
    rev = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
    narHash = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=";
  };
  make =
    source:
    purifier.implementation {
      inherit pkgs source;
      repository = "example/fixture-purifier";
      tool = "fixture-purifier";
      nativeCommand = "fixture";
      checksum = "npm";
      lockVersions = [ 3 ];
    };
  selected = make source;
  configured = selected.withConfiguration { sdk = "8.17.0"; };
  other = make (source // { rev = "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"; });
  overridden = make (source // { dirty = true; });
  package = selected.wrap (pkgs.writeShellScriptBin "fixture" "echo 42");
  overridable = selected.wrap (
    pkgs.lib.makeOverridable (
      {
        answer ? 42,
      }:
      pkgs.writeShellScriptBin "fixture" "echo ${toString answer}"
    ) { }
  );
  configuredConstructor = pkgs.lib.makeOverridable (
    {
      answer ? 42,
    }:
    (selected.withConfiguration { inherit answer; }).wrap (
      pkgs.writeShellScriptBin "fixture" "echo ${toString answer}"
    )
  ) { };
  configuredOverride = configuredConstructor.override { answer = 43; };
  metadataOnly = package.overrideAttrs (old: {
    meta = (old.meta or { }) // {
      priority = 7;
    };
  });

in
assert selected.check selected.pin true;
assert !(builtins.tryEval ((overridable.override { answer = 43; }).drvPath)).success;
assert
  !(builtins.tryEval (
    (package.overrideAttrs (old: {
      buildCommand = (old.buildCommand or "") + "\necho changed";
    })).drvPath
  )).success;
assert metadataOnly.drvPath == package.drvPath && metadataOnly.meta.priority == 7;
assert configuredOverride.implementation.source == selected.identity;
assert configuredOverride.implementation.configuration == { answer = 43; };
assert !(builtins.tryEval (selected.check (selected.pin // { version = 1.0; }) true)).success;
assert configured.check configured.pin true;
assert configured.withoutIdentity.identity == null;
assert !(builtins.tryEval (configured.withoutIdentity.check configured.pin true)).success;
assert builtins.all (value: !(builtins.tryEval ((selected.withConfiguration value).pin)).success) [
  { value = 1.5; }
  { value = [ { nested = 1.5; } ]; }
  { value = ./implementation.nix; }
];
assert !(builtins.tryEval (configured.check selected.pin true)).success;
assert !(builtins.tryEval (selected.check configured.pin true)).success;
assert selected.check null true;
assert !(builtins.tryEval (other.check selected.pin true)).success;
assert
  !(builtins.tryEval (
    selected.check (
      selected.pin
      // {
        source = {
          inherit (source) rev narHash;
        };
      }
    ) true
  )).success;
assert selected.check (
  selected.pin
  // {
    source = {
      type = "git";
      url = "https://example.invalid/mirror";
      inherit (source) rev narHash;
    };
  }
) true;
assert overridden.identity == null;
assert !(builtins.tryEval (overridden.check selected.pin true)).success;
pkgs.runCommand "purifier-implementation-package" { nativeBuildInputs = [ pkgs.python3 ]; } ''
  test "$(${package}/bin/fixture)" = 42
  test "$(${configuredOverride}/bin/fixture)" = 43
  python - ${package}/share/purifier/implementation.json <<'PY'
  import json,sys
  manifest=json.load(open(sys.argv[1]))
  assert manifest['source']['rev']=='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  assert manifest['tool']=='fixture-purifier'
  assert manifest['bootstrapVersion']==1
  PY
  touch "$out"
''
