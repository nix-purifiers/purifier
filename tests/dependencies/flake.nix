# SPDX-License-Identifier: MIT
{
  inputs.caisson.url = "github:nix-caisson/caisson";
  inputs.flake-parts.url = "github:hercules-ci/flake-parts";
  # Same channel as the main flake, so dev-partition evals agree with the
  # exported pkgSet.
  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
  inputs.treefmt-nix.url = "github:numtide/treefmt-nix";
  inputs.treefmt-nix.inputs.nixpkgs.follows = "nixpkgs";
  inputs.historical-ruby = {
    url = "github:NixOS/nixpkgs/1db42b7fe3878f3f5f7a4f2dc210772fd080e205";
    flake = false;
  };
  inputs.older-ruby = {
    url = "github:NixOS/nixpkgs/770822493e3962d795739fafd522e771bfe06e3d";
    flake = false;
  };
  outputs = { ... }: { };
}
