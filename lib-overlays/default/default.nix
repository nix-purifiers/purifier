# SPDX-License-Identifier: MIT
#
# The `purifier` library namespace: the functions of library.nix.
# A purifier that lists this flake in `projects` holds it as
# `purifier/default`, and its library then has `lib.purifier`.
{ ... }:
{

  overlay = final: prev: {
    purifier = import ./library.nix { lib = final; };
  };

}
