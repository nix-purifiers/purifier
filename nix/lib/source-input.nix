# SPDX-License-Identifier: MIT
# Source state is an input to the build, never a dependency-lock entry.
{ lib }:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  exact =
    fields: value:
    builtins.isAttrs value && builtins.attrNames value == lib.sort builtins.lessThan fields;
  relative =
    value:
    builtins.isString value
    && value != ""
    && builtins.match ".*[[:cntrl:]].*" value == null
    && lib.all (part: part != "" && part != "." && part != ".." && lib.toLower part != ".git") (
      lib.splitString "/" value
    );
  ref =
    value:
    builtins.isString value
    && builtins.match "refs/(heads|tags|remotes)/.+" value != null
    && lib.all (bad: !(lib.hasInfix bad value)) [
      ".."
      "@{"
      " "
      "\t"
      "\n"
      "\r"
      "~"
      "^"
      ":"
      "?"
      "*"
      "["
      "\\"
    ]
    && lib.all (part: part != "" && !(lib.hasPrefix "." part) && !(lib.hasSuffix ".lock" part)) (
      lib.splitString "/" value
    )
    && builtins.match ".*[[:cntrl:]].*" value == null
    && !(lib.hasSuffix "." value);
in
{
  src,
  git ? null,
}:
let
  sourceIdentity = inputIdentity src;
  checked =
    if git == null then
      null
    else
      let
        oid =
          value:
          builtins.isString value
          &&
            builtins.match (if git.objectFormat == "sha1" then "[0-9a-f]{40}" else "[0-9a-f]{64}") value
            != null;
        indexed =
          item:
          exact [ "path" "mode" "oid" "stage" "flags" ] item
          && exact [ "assumeUnchanged" "skipWorktree" "intentToAdd" ] item.flags
          && lib.all builtins.isBool (builtins.attrValues item.flags)
          && relative item.path
          && oid item.oid
          && builtins.elem item.mode [
            "100644"
            "100755"
            "120000"
            "160000"
          ]
          && builtins.elem item.stage [
            0
            1
            2
            3
          ];
        keys = map (item: "${item.path}:${toString item.stage}") git.index;
        byPath = lib.groupBy (item: item.path) git.index;
        objectIdentity = inputIdentity git.objects;
      in
      let
        check = condition: message: { inherit condition message; };
        checks = [
          (check (exact [
            "objectFormat"
            "head"
            "refs"
            "shallow"
            "objects"
            "index"
            "remotes"
          ] git) "git must explicitly name objectFormat, head, refs, shallow, objects, index and remotes")
          (check (builtins.elem git.objectFormat [
            "sha1"
            "sha256"
          ]) "unsupported Git object format")
          (check (
            exact [ "oid" "ref" ] git.head
            && oid git.head.oid
            && (git.head.ref == null || (ref git.head.ref && lib.hasPrefix "refs/heads/" git.head.ref))
          ) "HEAD needs its exact object ID and a local branch ref or null for detached HEAD")
          (check (
            builtins.isAttrs git.refs
            && lib.all ref (builtins.attrNames git.refs)
            && lib.all oid (builtins.attrValues git.refs)
          ) "invalid selected refs")
          (check (
            git.head.ref == null || (git.refs.${git.head.ref} or null) == git.head.oid
          ) "the HEAD branch must be captured at the HEAD object ID")
          (check (
            builtins.isList git.shallow
            && lib.all oid git.shallow
            && builtins.length git.shallow == builtins.length (lib.unique git.shallow)
          ) "shallow must explicitly list unique history boundary object IDs")
          (check (
            builtins.isList git.index
            && lib.all indexed git.index
            && builtins.length keys == builtins.length (lib.unique keys)
          ) "index must contain unique path/stage entries with exact modes and object IDs")
          (check (lib.all (items: !(lib.any (item: item.stage == 0) items) || builtins.length items == 1) (
            builtins.attrValues byPath
          )) "index stage 0 cannot coexist with merge stages for the same path")
          (check (
            builtins.isAttrs git.remotes
            && lib.all (name: ref ("refs/remotes/" + name + "/HEAD")) (builtins.attrNames git.remotes)
            && lib.all (
              remote:
              exact [ "url" "defaultRef" ] remote
              && builtins.isString remote.url
              && remote.url != ""
              && builtins.match "https?://[^/]*@.*" (lib.toLower remote.url) == null
              && builtins.match ".*://[^/]*:[^/@]+@.*" remote.url == null
              && !(lib.hasInfix "?" remote.url)
              && !(lib.hasInfix "#" remote.url)
              && builtins.match ".*[[:cntrl:]].*" remote.url == null
              && (
                remote.defaultRef == null
                || (ref remote.defaultRef && lib.hasPrefix "refs/heads/" remote.defaultRef)
              )
            ) (builtins.attrValues git.remotes)
          ) "remotes need a valid name, URL and default branch ref or null")
        ];
        problem = lib.findFirst (item: !item.condition) null checks;
      in
      if problem != null then
        throw "purifier: sourceInput: ${problem.message}"
      else
        builtins.deepSeq objectIdentity (
          git
          // {
            objects = toString git.objects;
            index = lib.sort (a: b: if a.path == b.path then a.stage < b.stage else a.path < b.path) git.index;
            shallow = lib.sort builtins.lessThan git.shallow;
          }
        );

  state = {
    format = "purifier-source-input-v1";
    source = toString src;
    git = checked;
  };
in
builtins.deepSeq sourceIdentity (
  builtins.deepSeq checked {
    inherit src;
    sourceState = state;
    # Including the serialized state in a derivation retains its Nix references.
    # The digest is for comparison; a digest alone does not retain those inputs.
    identity = builtins.hashString "sha256" (builtins.toJSON state);
  }
)
