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
in
{
  extensions = pkgs.runCommand "resource-recipe-v1-native-extension-apis" { } ''
    ${pkgs.python3}/bin/python3 -B ${./recipe-native.py} ${recipes.runtime} ${recipes.generator} ${old.glibc} ${recipes.openssl} ${./bounded-command.py} "$out"
  '';
  crc = pkgs.runCommand "resource-recipe-v1-original-crc20" { } ''
    ${pkgs.python3}/bin/python3 -B ${../rubygems0811/crc.py} ${recipes.generator}/bin/ruby ${../rubygems0811/crc-cases} ${../../tools/rubygems_0811_sdk.py} "$out"
  '';
}
