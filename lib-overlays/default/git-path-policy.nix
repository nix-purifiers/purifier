# SPDX-License-Identifier: MIT
# Type-check identity-bound observations. Native replay verifies their truth
# against the actual immutable source and destination filesystem.
{ lib }:
let
  exact = fields: value: builtins.isAttrs value && builtins.attrNames value == lib.sort builtins.lessThan fields;
  relative = value:
    builtins.isString value && value != "" && builtins.match ".*[[:cntrl:]].*" value == null
    && lib.all (part: part != "" && part != "." && part != ".." && lib.toLower part != ".git")
      (lib.splitString "/" value);
  component = value: relative value && !(lib.hasInfix "/" value);
  witness = value:
    exact [ "directory" "entry" "alternate" "kind" "relation" ] value
    && (value.directory == "." || relative value.directory)
    && component value.entry && component value.alternate && value.entry != value.alternate
    && builtins.elem value.kind [ "case" "normalization" ]
    && builtins.elem value.relation [ "alias" "distinct" ];
  # Keep the same supported limits as tools/git_source.py.
  query = value:
    builtins.isString value && builtins.stringLength value <= 134217728
    && builtins.div (builtins.stringLength value) 2 * 2 == builtins.stringLength value
    && builtins.match "[0-9a-f]*" value != null;
in
policy:
exact [ "format" "ignoreCase" "precomposeUnicode" "witnesses" "queries" ] policy
&& policy.format == "purifier-git-path-policy-v1"
&& builtins.isBool policy.ignoreCase && builtins.isBool policy.precomposeUnicode
&& builtins.isList policy.witnesses && builtins.length policy.witnesses <= 100000
&& lib.all witness policy.witnesses
&& (
  let
    keys = map (value: builtins.toJSON [ value.directory value.entry value.alternate value.kind ]) policy.witnesses;
    indexed = builtins.listToAttrs (map (name: { inherit name; value = true; }) keys);
  in builtins.length keys == builtins.length (builtins.attrNames indexed)
)
&& exact [ "statusPorcelainV1Z" "indexStageZ" "untrackedZ" ] policy.queries
&& lib.all query (builtins.attrValues policy.queries)
