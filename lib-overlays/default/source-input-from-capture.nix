# SPDX-License-Identifier: MIT
{ lib }:
capture:
let
  sourceInput = import ./source-input.nix { inherit lib; };
  root =
    if lib.isDerivation capture then
      throw "purifier: sourceInputFromCapture needs prepared capture metadata, not an unbuilt derivation"
    else
      builtins.path {
        path = capture;
        name = "purifier-source-capture";
      };
  manifest = builtins.fromJSON (builtins.readFile (root + "/capture.json"));
  source = builtins.path {
    path = root + "/source";
    name = "purifier-source";
  };
  objects = builtins.path {
    path = root + "/objects";
    name = "purifier-git-objects";
  };
in
if
  builtins.attrNames manifest != [
    "format"
    "git"
    "source"
  ]
  || manifest.format != "purifier-source-capture-v1"
  || !builtins.isAttrs manifest.git
  || (manifest.git.objects or null) != "objects"
then
  throw "purifier: invalid prepared Git source capture"
else
  sourceInput {
    src = source;
    git = manifest.git // {
      inherit objects;
    };
  }
