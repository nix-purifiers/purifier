# SPDX-License-Identifier: MIT
# Separate diagnostic candidate; original runtime recipes remain unchanged.
let
  root = ../..;
  self = builtins.getFlake ("path:" + toString root);
  dependencies = builtins.getFlake ("path:" + toString ../dependencies);
  pkgs = import self.inputs.nixpkgs { system = "x86_64-linux"; };
  olderRubySource = dependencies.inputs.older-ruby;
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
  ruby160 = import ./runtime.nix { inherit pkgs olderRubySource; };
  ruby180 = import ../rubygems0811/runtime.nix { inherit pkgs olderRubySource; };
  openssl097 = import ../rubygems0811/openssl097.nix { inherit pkgs old; };
  capture = role: value: {
    path = toString value;
    deriver = builtins.unsafeDiscardStringContext value.drvPath;
    # Transport unchanged ATerm bytes, as in the existing SDK provenance capture.
    aterm = pkgs.writeText "${role}.aterm" (
      builtins.unsafeDiscardStringContext (
        builtins.readFile (builtins.unsafeDiscardOutputDependency value.drvPath)
      )
    );
  };
  inputs = {
    outputs = {
      inherit (builtins) currentSystem;
      ruby160 = (capture "ruby160" ruby160) // {
        source = toString ruby160.src;
      };
      ruby180 = (capture "ruby180" ruby180) // {
        source = toString ruby180.src;
      };
      openssl097 = (capture "openssl097" openssl097) // {
        source = toString openssl097.src;
      };
    };
    compiler = capture "compiler" old.stdenv.gcc;
    stdenv = capture "stdenv" old.stdenv;
    nix = toString pkgs.nix;
  };
  descriptor = pkgs.writeText "ruby160-output-diagnostic.json" (builtins.toJSON inputs);
  closure = pkgs.closureInfo {
    rootPaths = [
      ruby160
      ruby180
      openssl097
      old.stdenv
      old.stdenv.gcc
      ruby160.src
      ruby180.src
      openssl097.src
      pkgs.nix
    ];
  };
in
pkgs.runCommand "ruby160-three-original-output-diagnostic" { } ''
  ${pkgs.python3}/bin/python3 -B ${./diagnostic.py} ${descriptor} ${closure}/store-paths ${../../tools/rubygems_0811_sdk.py} "$out"
''
