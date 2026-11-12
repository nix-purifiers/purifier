# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  sdkOutput = pkgs.runCommand "sdk-identity-home-output" { } "mkdir -p $out";
  sdk = sdkOutput // {
    home = "${sdkOutput}/lib/openjdk";
  };
  home = sdk.home;
  manager = {
    executable = home + "/bin/java";
    runtimeHome = home + "/jre";
  };
  identify =
    args:
    purifier.jvmSdkIdentity (
      {
        inherit sdk manager;
        system = pkgs.stdenv.hostPlatform.system;
      }
      // args
    );
  original = identify { };
  force =
    value:
    builtins.deepSeq {
      inherit (value) payload identityHash managerIdentity;
    } true;
  accepts = args: (builtins.tryEval (force (identify args))).success;
  distinctOutput = pkgs.runCommand "sdk-identity-distinct-output" {
    passthru.home = home;
  } "mkdir -p $out";
  separate = identify { sdk = distinctOutput; };
  changedManager = identify {
    manager = manager // {
      runtimeHome = home;
    };
  };
  pinnedAdapters = import ../../lib-overlays/default/jvm-sdk-adapters.nix { inherit pkgs; };
  invalidPaths = [
    "${sdk}/../../outside"
    "${home}/./nested"
    "${home}//nested"
    "${home}/trailing/"
    "${home}/bad\tname"
    "${home}/bad\nname"
    "${home}/bad\rname"
    (home + "/bad" + builtins.fromJSON ''"\u0001"'' + "name")
    (home + "/bad" + builtins.fromJSON ''"\u007f"'' + "name")
    (builtins.appendContext "/nix/store/not-a-valid-root/home" (builtins.getContext home))
  ];
  tests = {
    testDistinctOutputRetainsHomeContext = {
      expr =
        separate.payload.homeContext == original.payload.homeContext
        && separate.payload.outputContext != original.payload.outputContext
        && separate.identityHash != original.identityHash;
      expected = true;
    };
    testManagerRelationHasIndependentIdentity = {
      expr =
        changedManager.identityHash == original.identityHash
        && changedManager.managerIdentity.identityHash != original.managerIdentity.identityHash;
      expected = true;
    };
    testSdkIdentityVersion = {
      expr = original.payload.version;
      expected = "sdk-output-home-context-v1";
    };
    testRejectAmbientSdkHome = {
      expr = accepts { home = "/tmp/jdk"; };
      expected = false;
    };
    testRejectContextStrippedRuntimeHome = {
      expr = accepts {
        manager = manager // {
          runtimeHome = builtins.unsafeDiscardStringContext manager.runtimeHome;
        };
      };
      expected = false;
    };
    testRejectCrossSystemSdk = {
      expr = accepts { system = "unsupported-target"; };
      expected = false;
    };
    testRejectNoncanonicalSdkAndManagerPaths = {
      expr = pkgs.lib.all (
        path:
        !accepts { home = path; }
        && !accepts {
          manager = manager // {
            executable = path;
          };
        }
        && !accepts {
          manager = manager // {
            runtimeHome = path;
          };
        }
      ) invalidPaths;
      expected = true;
    };
    testPinnedProviderRuntimeMappings = {
      expr =
        if pkgs.stdenv.hostPlatform.system != "x86_64-linux" then
          true
        else
          pinnedAdapters.openjdk8.manager.runtimeHome == pinnedAdapters.openjdk8.home + "/jre"
          && pinnedAdapters.openjdk11.manager.runtimeHome == pinnedAdapters.openjdk11.home
          && pinnedAdapters.openjdk17.manager.runtimeHome == pinnedAdapters.openjdk17.home;
      expected = true;
    };
  };
  failures = pkgs.lib.debug.runTests tests;
in
pkgs.runCommand "purifier-jvm-sdk-identities" { } (
  if failures == [ ] then
    "touch $out"
  else
    "echo ${pkgs.lib.escapeShellArg (builtins.toJSON failures)} >&2; exit 1"
)
