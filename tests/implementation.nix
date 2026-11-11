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
  embedded = selected.wrap (
    pkgs.lib.makeOverridable (
      {
        marker ? 42,
      }:
      pkgs.writeShellScriptBin "fixture-purifier" ''
        # Native script variant ${toString marker}; the bootstrap path is embedded.
        if [ "''${1:-}" = implementation-relock ]; then exit 0; fi
        exec ${pkgs.python3}/bin/python ${selected.tool} self-update \
          --config ${selected.manifest} --lockfile "$PWD/bootstrap.lock" \
          --installed-command "$0" --to installed
      ''
    ) { }
  );

in
assert selected.check selected.pin true;
assert !(builtins.tryEval ((overridable.override { answer = 43; }).drvPath)).success;
assert
  !(builtins.tryEval (
    (package.overrideAttrs (old: {
      buildCommand = (old.buildCommand or "") + "\necho changed";
    })).drvPath
  )).success;
assert !(builtins.tryEval ((embedded.override { marker = 43; }).drvPath)).success;
assert
  !(package ? overrideDerivation)
  || !(builtins.tryEval (
    (package.overrideDerivation (_: {
      name = "changed-recipe";
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
  python - ${selected.tool} <<'PY'
  import importlib.util
  spec=importlib.util.spec_from_file_location("bootstrap",__import__('sys').argv[1])
  bootstrap=importlib.util.module_from_spec(spec);spec.loader.exec_module(bootstrap)
  open('bootstrap.lock','w').write(bootstrap.render_lock({'version':3,'hash':""},'npm'))
  PY
  ${embedded}/bin/fixture-purifier
  python - <<'PY'
  import json
  value=json.load(open('bootstrap.lock'))
  assert value['implementation']['source']['rev']=='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
  PY
  touch "$out"
''
