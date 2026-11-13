# SPDX-License-Identifier: MIT
# An unchanged compiled application view, not a source-package repository.
{ lib }:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  projectInputs = import ./project-inputs.nix { inherit lib; };
  relative =
    value:
    builtins.isString value
    && value != ""
    && builtins.match ".*[[:cntrl:]].*" value == null
    && !(lib.hasInfix "\\" value)
    && lib.all (part: part != "" && part != "." && part != "..") (lib.splitString "/" value);
in
{
  producer,
  applications,
  runtime,
  system,
  runCommand,
  python3,
  dependencies ? [ ],
  name ? "compiled-otp-projection",
}:
assert lib.assertMsg (
  applications != [ ]
  && builtins.isList applications
  && lib.all (
    app:
    builtins.isAttrs app
    &&
      builtins.attrNames app == [
        "observation"
        "path"
      ]
    && relative app.path
    && relative app.observation
  ) applications
  && lib.length applications == lib.length (lib.unique (map (app: app.path) applications))
) "otpProjections needs distinct compiled app directories and production observation members";
let
  selected = projectInputs {
    inherit dependencies system;
    formats = [ "otp" ];
  };
  runtimeIdentity = (inputIdentity runtime).hash;
  repositories = map (input: {
    repository = toString input.repository;
    catalog = toString input.repository.catalog;
    producer = toString input.producer;
    identity = input.repositoryIdentity.hash;
  }) selected;
  inputs = [
    producer
    runtime
  ]
  ++ lib.concatMap (input: [
    input.producer
    input.repository
  ]) selected;
  closure =
    runCommand "${name}-declared-closure"
      {
        __structuredAttrs = true;
        exportReferencesGraph.inputs = inputs;
      }
      ''
        out=''${outputs[out]}
        ${python3}/bin/python3 - <<'PY' > "$out"
        import json, os
        data = json.load(open(os.environ["NIX_ATTRS_JSON_FILE"]))
        print(json.dumps(sorted(entry["path"] for entry in data["inputs"])))
        PY
      '';
  toolchain = runCommand "${name}-projector-identity" {
    projector = ../../pkgs/otp-projection/project.py;
    inspector = ../../pkgs/otp-projection/inspect.escript;
    inherit runtime python3;
  } "touch $out";
  projectorIdentity = (inputIdentity toolchain).hash;
  identity = builtins.hashString "sha256" (
    builtins.toJSON {
      producer = (inputIdentity producer).hash;
      inherit
        applications
        runtimeIdentity
        system
        projectorIdentity
        ;
      dependencies = map (input: input.repositoryIdentity.hash) selected;
    }
  );
  projection =
    runCommand name
      {
        nativeBuildInputs = [
          runtime
          python3
        ];
        spec = builtins.toJSON {
          format = "purifier-compiled-otp-v1";
          inherit
            applications
            system
            identity
            projectorIdentity
            ;
          producer = toString producer;
          producerIdentity = (inputIdentity producer).hash;
          runtime = toString runtime;
          inherit runtimeIdentity;
          dependencies = repositories;
          closure = toString closure;
        };
        passAsFile = [ "spec" ];
        passthru = {
          catalog = "${projection}/catalog.json";
          applicationRoot = "${projection}/lib";
          inherit runtime system;
        };
      }
      ''
        export ERL_LIBS="" ERL_FLAGS="" ERL_AFLAGS="" ERL_ZFLAGS=""
        export HOME="$TMPDIR/otp-home"
        mkdir -p "$HOME"
        ${python3}/bin/python3 ${../../pkgs/otp-projection/project.py} "$specPath" \
          ${runtime}/bin/escript ${../../pkgs/otp-projection/inspect.escript} "$out"
      '';
in
assert lib.assertMsg (
  projection.system == system
) "otpProjections currently requires a native build for the selected system";
assert lib.all (input: (inputIdentity input.repository.runtime).hash == runtimeIdentity) selected;
{
  otp = projection;
}
