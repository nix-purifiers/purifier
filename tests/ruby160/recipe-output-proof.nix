# SPDX-License-Identifier: MIT
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
  recipes = import ./recipes-v1.nix { inherit pkgs olderRubySource; };
  capture = role: value: {
    path = toString value;
    deriver = builtins.unsafeDiscardStringContext value.drvPath;
    aterm = pkgs.writeText "${role}-resource-v1.aterm" (
      builtins.unsafeDiscardStringContext (
        builtins.readFile (builtins.unsafeDiscardOutputDependency value.drvPath)
      )
    );
  };
  descriptor = pkgs.writeText "resource-recipe-v1-outputs.json" (
    builtins.toJSON {
      outputs = {
        inherit (builtins) currentSystem;
        ruby160 = (capture "ruby160" recipes.runtime) // {
          source = toString recipes.runtime.src;
        };
        ruby180 = (capture "ruby180" recipes.generator) // {
          source = toString recipes.generator.src;
        };
        openssl097 = (capture "openssl097" recipes.openssl) // {
          source = toString recipes.openssl.src;
        };
      };
      compiler = capture "compiler" old.stdenv.gcc;
      stdenv = capture "stdenv" old.stdenv;
      nix = toString pkgs.nix;
    }
  );
  closure = pkgs.closureInfo {
    rootPaths = [
      recipes.runtime
      recipes.generator
      recipes.openssl
      old.stdenv
      old.stdenv.gcc
      recipes.runtime.src
      recipes.generator.src
      recipes.openssl.src
      pkgs.nix
    ];
  };
in
pkgs.runCommand "resource-recipe-v1-full-output-proof" { } ''
  ${pkgs.python3}/bin/python3 -B ${./recipe-outputs.py} ${descriptor} ${closure}/store-paths ${../../tools/rubygems_0811_sdk.py} "$out"
''
