# SPDX-License-Identifier: MIT
# Convenience providers for this flake's pinned SDKs. These mappings are
# explicit and native-tested; they are not a rule for arbitrary Java homes.
{ pkgs }:
let
  adapter = import ./jvm-sdk-adapter.nix { inherit (pkgs) lib; };
  java8 = pkgs.javaPackages.compiler.openjdk8.headless;
  java11 = pkgs.javaPackages.compiler.openjdk11.headless;
  java17 = pkgs.javaPackages.compiler.openjdk17.headless;
  system = pkgs.stdenv.hostPlatform.system;
in
assert
  system == "x86_64-linux"
  || throw "purifier: pinned JVM SDK adapters currently require x86_64-linux";
{
  openjdk8 = adapter {
    sdk = java8;
    inherit system;
    home = java8.home;
    executable = "${java8.home}/bin/java";
    runtimeHome = "${java8.home}/jre";
  };
  openjdk11 = adapter {
    sdk = java11;
    inherit system;
    home = java11.home;
    executable = "${java11.home}/bin/java";
    runtimeHome = java11.home;
  };
  openjdk17 = adapter {
    sdk = java17;
    inherit system;
    home = java17.home;
    executable = "${java17.home}/bin/java";
    runtimeHome = java17.home;
  };
}
