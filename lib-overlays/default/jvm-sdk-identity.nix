# SPDX-License-Identifier: MIT
# Versioned SDK identities keep every Nix context used by replay. Old
# inputIdentity hashes deliberately retain their original meaning.
{ lib }:
{
  sdk,
  system,
  home ? sdk.home or (throw "purifier: JVM SDK must declare a context-bearing home"),
  manager ? null,
}:
let
  problem = message: throw "purifier: JVM SDK ${message}";
  lexicalStorePath =
    value:
    let
      parts = lib.splitString "/" (lib.removePrefix "${builtins.storeDir}/" value);
    in
    builtins.match ".*[[:cntrl:]].*" value == null
    && lib.all (part: part != "" && part != "." && part != "..") parts
    &&
      builtins.match "[0-9abcdfghijklmnpqrsvwxyz]{32}-[A-Za-z0-9+._?=-]+" (builtins.head parts) != null;
  contextualPath =
    name: value:
    if
      !builtins.isString value
      || !lib.hasPrefix "${builtins.storeDir}/" value
      || builtins.getContext value == { }
    then
      problem "${name} must carry a Nix store reference"
    else if !lexicalStorePath value then
      problem "${name} must have a canonical lexical store path"
    else
      value;
  # Lexical validation cannot establish symlink canonicality. Consumers
  # must still compare native canonical paths and actual executable origin.
  output = contextualPath "output" (toString sdk);
  sdkHome = contextualPath "home" home;
  payload = {
    version = "sdk-output-home-context-v1";
    inherit output;
    home = sdkHome;
    outputContext = builtins.getContext output;
    homeContext = builtins.getContext sdkHome;
  };
  identityHash = builtins.hashString "sha256" (builtins.toJSON payload);
  managerIdentity =
    if manager == null then
      null
    else
      let
        executable = contextualPath "manager executable" manager.executable;
        runtimeHome = contextualPath "manager runtime home" manager.runtimeHome;
        managerPayload = {
          version = "jvm-manager-executable-runtime-home-v1";
          sdkIdentity = identityHash;
          inherit executable runtimeHome;
          executableContext = builtins.getContext executable;
          runtimeHomeContext = builtins.getContext runtimeHome;
        };
      in
      {
        payload = managerPayload;
        identityHash = builtins.hashString "sha256" (builtins.toJSON managerPayload);
      };
in
assert
  builtins.isAttrs sdk && sdk.type or null == "derivation"
  || problem "selection must be a derivation";
assert
  sdk.system or null == system || problem "derivation system differs from the execution system";
{
  inherit payload identityHash managerIdentity;
  # These values retain context. Serialized paths must never replace them.
  closureInputs = [
    sdk
    sdkHome
  ]
  ++ lib.optionals (managerIdentity != null) [
    managerIdentity.payload.executable
    managerIdentity.payload.runtimeHome
  ];
}
