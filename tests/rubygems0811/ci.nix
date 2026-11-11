# SPDX-License-Identifier: MIT
# Two explicit phases avoid import-from-derivation while binding the measured SDK.
{
  nativeSdkIdentity ? null,
}:
let
  root = ../..;
  self = builtins.getFlake ("path:" + toString root);
  dependencies = builtins.getFlake ("path:" + toString ../dependencies);
  pkgs = import self.inputs.nixpkgs { system = "x86_64-linux"; };
  purifier = import root { lib = pkgs.lib; };
in
import ./fixtures.nix {
  inherit pkgs purifier nativeSdkIdentity;
  olderRubySource = dependencies.inputs.older-ruby;
}
