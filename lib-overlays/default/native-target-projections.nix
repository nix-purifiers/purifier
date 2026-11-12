# SPDX-License-Identifier: MIT
# Select installed shared targets from native build-system metadata. Static
# libraries and runtime plugins require different consumer interfaces.
{ lib }:
{
  producer,
  targets,
  installedFiles ? [ ],
  system,
  runCommand,
  python3,
}:
let
  shared = lib.filterAttrs (
    _: target:
    builtins.elem target.type [
      "SHARED_LIBRARY"
      "shared library"
    ]
  ) targets;
  libraryFile =
    name: target:
    let
      stripNumeric =
        parts:
        if parts != [ ] && builtins.match "[0-9]+" (lib.last parts) != null then
          stripNumeric (lib.init parts)
        else
          lib.concatStringsSep "." parts;
      candidates = builtins.filter (
        file: builtins.match ".*\\.so(\\.[0-9.]+)?" file != null || lib.hasSuffix ".dylib" file
      ) target.files;
      # Prefer the unversioned linker name when the native target records
      # both it and versioned symlinks; all still belong to the same output.
      sorted = lib.sort (a: b: builtins.stringLength a < builtins.stringLength b) candidates;
      stems = lib.unique (
        map (
          file:
          let
            so = builtins.match "(.*)\\.so(\\.[0-9.]+)?" file;
          in
          if so != null then
            builtins.head so
          else
            stripNumeric (lib.splitString "." (lib.removeSuffix ".dylib" file))
        ) candidates
      );
    in
    if sorted == [ ] then
      throw "purifier: installed shared target ${name} has no supported library artifact"
    else if builtins.length stems != 1 then
      throw "purifier: installed shared target ${name} has ambiguous library artifacts"
    else
      builtins.head sorted;
  libraries = lib.mapAttrs libraryFile shared;
in
lib.optionalAttrs (libraries != { }) (
  import ./native-projections.nix { inherit lib; } {
    inherit
      producer
      libraries
      system
      runCommand
      python3
      ;
    targetMetadata = shared;
    includeDirectories = lib.optional (builtins.any (lib.hasPrefix "include/") installedFiles) "include";
    pkgConfigDirectories = lib.unique (
      map dirOf (builtins.filter (lib.hasSuffix ".pc") installedFiles)
    );
  }
)
