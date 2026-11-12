# SPDX-License-Identifier: MIT
# Providers declare their runtime layout; the resolver never guesses it.
{ lib }:
{
  sdk,
  system,
  home ? sdk.home or (throw "purifier: JVM SDK adapter must declare its home"),
  executable,
  runtimeHome,
}:
let
  manager = { inherit executable runtimeHome; };
  identity = import ./jvm-sdk-identity.nix { inherit lib; } {
    inherit
      sdk
      system
      home
      manager
      ;
  };
in
assert builtins.deepSeq {
  inherit (identity) payload identityHash managerIdentity;
} true;
{
  inherit sdk home manager;
}
