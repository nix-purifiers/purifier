# SPDX-License-Identifier: MIT
let
  root = ../..;
  self = builtins.getFlake ("path:" + toString root);
  dependencies = builtins.getFlake ("path:" + toString ../dependencies);
  pkgs = import self.inputs.nixpkgs { system = "x86_64-linux"; };
in
import ./fixtures.nix {
  inherit pkgs;
  purifier = import root { inherit (pkgs) lib; };
  olderRubySource = dependencies.inputs.older-ruby;
}
