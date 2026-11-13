# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  inherit (pkgs) lib runCommand python3;
  runtime = pkgs.beamPackages.erlang;
  producer = runCommand "compiled-otp-native-fixture" { nativeBuildInputs = [ runtime ]; } ''
    ${runtime}/bin/escript ${./produce.escript} "$out" ${runtime}
  '';
  application = name: {
    path = "lib/${name}";
    observation = "lib/${name}/ebin/otp-observation.term";
  };
  project =
    source: names: dependencies:
    purifier.otpProjections {
      producer = source;
      applications = map application names;
      inherit
        runtime
        dependencies
        runCommand
        python3
        ;
      system = pkgs.stdenv.hostPlatform.system;
    };
  dep = project producer [ "otp_fixture_dep" ] [ ];
  bound = producer // {
    projections = dep;
  };
  app = project producer [ "otp_fixture_app" ] [ bound ];
  optional = project producer [ "otp_fixture_optional" ] [ ];
  optionalBound = project producer [ "otp_fixture_optional" ] [ bound ];
  included = project producer [ "otp_fixture_included" ] [ bound ];
  changed =
    label: commands:
    runCommand "compiled-otp-negative-${label}" { nativeBuildInputs = [ runtime ]; } ''
      cp -r ${producer} "$out"
      chmod -R u+w "$out"
      ${commands}
    '';
  expect =
    message: drv:
    pkgs.testers.testBuildFailure (
      drv.overrideAttrs (old: {
        buildCommand = ''
          set +e
          ( ${old.buildCommand} ) > "$TMPDIR/attempt.log" 2>&1
          result=$?
          cat "$TMPDIR/attempt.log"
          if [ "$result" -eq 0 ]; then exit 0; fi
          grep -F ${lib.escapeShellArg message} "$TMPDIR/attempt.log" || exit 0
          exit 1
        '';
      })
    );
  changeObservation = field: value: ''
    ${runtime}/bin/erl +S 2:2 -noshell -eval '
      File = os:getenv("out") ++ "/lib/otp_fixture_dep/ebin/otp-observation.term",
      {ok,[Value]} = file:consult(File),
      ok = file:write_file(File, io_lib:format("~p.~n", [Value#{${field} => ${value}}])), halt().'
  '';
  badRuntime = changed "runtime" (changeObservation "runtime" ''"/unrepresented/runtime"'');
  badErts = changed "erts" (changeObservation "erts" ''"not-the-selected-erts"'');
  incomplete = changed "modules" ''
    ${runtime}/bin/erl +S 2:2 -noshell -eval '
      File = os:getenv("out") ++ "/lib/otp_fixture_dep/ebin/otp_fixture_dep.app",
      {ok,[{application,A,Props}]} = file:consult(File),
      ok=file:write_file(File,io_lib:format("~p.~n",[{application,A,lists:keystore(modules,1,Props,{modules,[]})}])),halt().'
  '';
  nativePayload = changed "native-payload" ''
    mkdir -p "$out/lib/otp_fixture_dep/priv"
    printf '\177ELF' > "$out/lib/otp_fixture_dep/priv/native.so"
  '';
  duplicateModule = changed "duplicate-module" ''
    cp -r "$out/lib/otp_fixture_dep" "$out/lib/duplicate"
    mv "$out/lib/duplicate/ebin/otp_fixture_dep.app" "$out/lib/duplicate/ebin/otp_fixture_duplicate.app"
    sed -i 's/{application,otp_fixture_dep,/{application,otp_fixture_duplicate,/' "$out/lib/duplicate/ebin/otp_fixture_duplicate.app"
  '';
  escaped = changed "escape" ''ln -s ${producer}/lib/otp_fixture_dep "$out/lib/escape"'';
  runtimeCollision = changed "runtime-collision" ''
    mv "$out/lib/otp_fixture_dep/ebin/otp_fixture_dep.app" "$out/lib/otp_fixture_dep/ebin/kernel.app"
    sed -i 's/{application,otp_fixture_dep,/{application,kernel,/' "$out/lib/otp_fixture_dep/ebin/kernel.app"
  '';
  sdkModule = changed "sdk-module" ''
    ${runtime}/bin/erl +S 2:2 -noshell -eval '
      Ebin=os:getenv("out") ++ "/lib/otp_fixture_dep/ebin",
      Source=Ebin ++ "/file.erl",
      ok=file:write_file(Source,"-module(file). -export([value/0]). value()->42."),
      {ok,file}=compile:file(Source,[{outdir,Ebin}]),
      Beam=Ebin ++ "/file.beam",
      {ok,{file,Chunks}}=beam_lib:chunks(Beam,[exports,imports,compile_info]),
      ok=file:delete(Ebin ++ "/otp_fixture_dep.beam"),
      AppFile=Ebin ++ "/otp_fixture_dep.app",
      {ok,[{application,A,P}]}=file:consult(AppFile),
      ok=file:write_file(AppFile,io_lib:format("~p.~n",[{application,A,lists:keystore(modules,1,P,{modules,[file]})}])),
      ObsFile=Ebin ++ "/otp-observation.term",{ok,[Obs]}=file:consult(ObsFile),
      ok=file:write_file(ObsFile,io_lib:format("~p.~n",[Obs#{modules=>[file],compiled=>[#{module=>file,file=>Beam,chunks=>Chunks}]}])),halt().'
  '';
  unsafe = [
    ""
    "/absolute"
    "../other"
    "a/../b"
    "a//b"
    "a\\b"
  ];
  rejects =
    path:
    !(builtins.tryEval (
      builtins.deepSeq
        (purifier.otpProjections {
          inherit
            producer
            runtime
            runCommand
            python3
            ;
          applications = [
            {
              inherit path;
              observation = "valid";
            }
          ];
          system = pkgs.stdenv.hostPlatform.system;
        }).otp.drvPath
        true
    )).success;
in
{
  otp-evaluation =
    assert lib.all rejects unsafe;
    assert builtins.hasAttr (builtins.unsafeDiscardStringContext producer.drvPath) (
      builtins.getContext app.otp.spec
    );
    assert builtins.hasAttr (builtins.unsafeDiscardStringContext runtime.drvPath) (
      builtins.getContext app.otp.spec
    );
    assert builtins.hasAttr (builtins.unsafeDiscardStringContext dep.otp.drvPath) (
      builtins.getContext app.otp.spec
    );
    runCommand "compiled-otp-evaluation" {
      drv = builtins.unsafeDiscardStringContext app.otp.drvPath;
    } ''touch "$out"'';
  otp-native = runCommand "compiled-otp-native-consumer" { nativeBuildInputs = [ runtime ]; } ''
    export ERL_LIBS=${app.otp.applicationRoot} ERL_FLAGS="" ERL_AFLAGS="" ERL_ZFLAGS=""
    cat > consumer.erl <<'ERLANG'
    -module(consumer).
    -export([main/0]).
    -include_lib("otp_fixture_dep/include/value.hrl").
    main() ->
      {ok,_}=application:ensure_all_started(otp_fixture_app),
      ?OTP_VALUE=otp_fixture_app:value(),
      {ok,"1.2.3"}=application:get_key(otp_fixture_dep,vsn),
      Path=code:which(otp_fixture_app),
      true=lists:prefix(os:getenv("ERL_LIBS") ++ "/",Path),
      io:format("value=42 include_lib/startup/native-version/origin verified~n"),halt().
    ERLANG
    erlc consumer.erl
    erl +S 2:2 -noshell -pa . -s consumer main
    ${python3}/bin/python3 - <<'PY'
    import hashlib, json
    from pathlib import Path
    model=json.load(open('${app.otp.catalog}'))
    for a in model['applications']:
        source=Path(a['origin'])/'lib'/a['name']/'ebin'/(a['name']+'.app')
        target=Path('${app.otp}')/a['directory']/'ebin'/(a['name']+'.app')
        assert source.read_bytes()==target.read_bytes()
    assert {a['name'] for a in model['applications']}=={'otp_fixture_app','otp_fixture_dep'}
    PY
    ${python3}/bin/python3 - <<'PY'
    import json
    absent=json.load(open('${optional.otp.catalog}'))
    present=json.load(open('${optionalBound.otp.catalog}'))
    assert {a['name'] for a in absent['applications']}=={'otp_fixture_optional'}
    assert {a['name'] for a in present['applications']}=={'otp_fixture_optional','otp_fixture_dep'}
    assert 'crypto' in {a['name'] for a in absent['runtimeApplications']}
    PY
    test -f ${included.otp.catalog}
    touch "$out"
  '';
  otp-missing =
    expect "missing_required_compiled_application"
      (project producer [ "otp_fixture_app" ] [ ]).otp;
  otp-duplicate-app =
    expect "duplicate_application_owners"
      (project (changed "other-owner" "") [ "otp_fixture_dep" ] [ bound ]).otp;
  otp-duplicate-module =
    expect "duplicate_compiled_module_owners"
      (project duplicateModule [ "duplicate" ] [ bound ]).otp;
  otp-runtime-mismatch =
    expect "production_runtime_input_mismatch"
      (project badRuntime [ "otp_fixture_dep" ] [ ]).otp;
  otp-erts-mismatch =
    expect "production_runtime_mismatch,erts"
      (project badErts [ "otp_fixture_dep" ] [ ]).otp;
  otp-incomplete-app =
    expect "incomplete_application_modules"
      (project incomplete [ "otp_fixture_dep" ] [ ]).otp;
  otp-native-payload =
    expect "custom native payload needs"
      (project nativePayload [ "otp_fixture_dep" ] [ ]).otp;
  otp-escape = expect "application selection escapes producer" (project escaped [ "escape" ] [ ]).otp;
  otp-runtime-collision =
    expect "runtime_application_collision"
      (project runtimeCollision [ "otp_fixture_dep" ] [ ]).otp;
  otp-runtime-module-collision =
    expect "runtime_module_collision"
      (project sdkModule [ "otp_fixture_dep" ] [ ]).otp;
}
