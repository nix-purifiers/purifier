# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  inherit (pkgs) lib;
  src = builtins.toFile "source" "working contents";
  objects = builtins.toFile "objects" "opaque object closure fixture";
  head = "0123456789abcdef0123456789abcdef01234567";
  other = "1123456789abcdef0123456789abcdef01234567";
  git = {
    objectFormat = "sha1";
    head = {
      oid = head;
      ref = "refs/heads/main";
    };
    refs."refs/heads/main" = head;
    shallow = [ head ];
    inherit objects;
    index = [
      {
        path = "file";
        mode = "100644";
        oid = other;
        stage = 0;
        flags = {
          assumeUnchanged = false;
          skipWorktree = false;
          intentToAdd = false;
        };
      }
    ];
    remotes.origin = {
      url = "https://example.org/repo.git";
      defaultRef = "refs/heads/main";
    };
  };
  make =
    changes:
    purifier.sourceInput {
      inherit src;
      git = git // changes;
    };
  fails = value: !(builtins.tryEval (builtins.deepSeq value true)).success;
  original = make { };
  pathPolicy = {
    format = "purifier-git-path-policy-v1";
    ignoreCase = false;
    precomposeUnicode = false;
    witnesses = [
      {
        directory = ".";
        entry = "file";
        alternate = "File";
        kind = "case";
        relation = "distinct";
      }
    ];
    queries = {
      statusPorcelainV1Z = "";
      indexStageZ = "";
      untrackedZ = "";
    };
  };
  stateBuild =
    input:
    pkgs.runCommand "source-state-identity" {
      sourceState = builtins.toJSON input.sourceState;
    } "touch $out";
  tests = {
    testPathPolicyVersionAndIdentity = {
      expr =
        let
          input = make { inherit pathPolicy; };
          changed = make {
            pathPolicy = pathPolicy // {
              ignoreCase = true;
            };
          };
        in
        input.sourceState.format == "purifier-source-input-v2"
        && input.sourceState.git.pathPolicy == pathPolicy
        && input.identity != changed.identity
        && original.sourceState.format == "purifier-source-input-v1";
      expected = true;
    };
    testPathPolicyRejectsUnknownOrIncompleteEvidence = {
      expr =
        builtins.all
          (
            policy:
            fails (make {
              pathPolicy = policy;
            })
          )
          [
            (builtins.removeAttrs pathPolicy [ "queries" ])
            (pathPolicy // { hostInode = 1; })
            (pathPolicy // { ignoreCase = 1; })
            (pathPolicy // { witnesses = pathPolicy.witnesses ++ pathPolicy.witnesses; })
            (
              pathPolicy
              // {
                queries = pathPolicy.queries // {
                  indexStageZ = "0";
                };
              }
            )
          ];
      expected = true;
    };
    testPathPolicyQueryAndWitnessIdentity = {
      expr =
        let
          input = make { inherit pathPolicy; };
          query = make {
            pathPolicy = pathPolicy // {
              queries = pathPolicy.queries // {
                untrackedZ = "00";
              };
            };
          };
          witness = make {
            pathPolicy = pathPolicy // {
              witnesses = map (w: w // { relation = "alias"; }) pathPolicy.witnesses;
            };
          };
        in
        input.identity != query.identity && input.identity != witness.identity;
      expected = true;
    };
    testStateChangesDerivation = {
      expr =
        (stateBuild original).drvPath != (stateBuild (make {
          head = {
            oid = head;
            ref = null;
          };
        })).drvPath;
      expected = true;
    };
    testDerivationObjectsNeedNoImport = {
      expr =
        (make {
          objects = pkgs.runCommand "unbuilt-history" { } "exit 1";
        }).sourceState.git.objects != "";
      expected = true;
    };

    testStageZeroWithMergeStageRejected = {
      expr =
        builtins.all
          (
            stage:
            fails (make {
              index = git.index ++ [
                ((builtins.head git.index) // { inherit stage; })
              ];
            })
          )
          [
            1
            2
            3
          ];
      expected = true;
    };
    testMergeStagesCoexist = {
      expr =
        map (entry: entry.stage)
          (make {
            index = map (stage: (builtins.head git.index) // { inherit stage; }) [
              3
              1
              2
            ];
          }).sourceState.git.index;
      expected = [
        1
        2
        3
      ];
    };
    testUnsafeIndexPathsRejected = {
      expr =
        builtins.all
          (
            path:
            fails (make {
              index = [
                ((builtins.head git.index) // { inherit path; })
              ];
            })
          )
          [
            ".git"
            ".git/config"
            "a/.git/config"
            "a/.GIT/config"
            "a\nb"
            "a\rb"
            "a\tb"
            (builtins.fromJSON ''"a\u0001b"'')
          ];
      expected = true;
    };
    testIndexFlagsChangeIdentity = {
      expr =
        builtins.all
          (
            flag:
            (make {
              index = [
                (
                  (builtins.head git.index)
                  // {
                    flags = (builtins.head git.index).flags // {
                      ${flag} = true;
                    };
                  }
                )
              ];
            }).identity != original.identity
          )
          [
            "assumeUnchanged"
            "skipWorktree"
            "intentToAdd"
          ];
      expected = true;
    };
    testMissingIndexFlagsRejected = {
      expr = fails (make {
        index = [ (removeAttrs (builtins.head git.index) [ "flags" ]) ];
      });
      expected = true;
    };
    testNonBooleanFlagRejected = {
      expr = fails (make {
        index = [
          (
            (builtins.head git.index)
            // {
              flags = (builtins.head git.index).flags // {
                skipWorktree = "false";
              };
            }
          )
        ];
      });
      expected = true;
    };
    testCredentialBearingRemotesRejected = {
      expr =
        builtins.all
          (
            url:
            fails (make {
              remotes.origin = git.remotes.origin // {
                inherit url;
              };
            })
          )
          [
            "https://user:secret@example.org/repo.git"
            "https://token@example.org/repo.git"
            "HTTP://token@example.org/repo.git"
            "HtTpS://token@example.org/repo.git"
            "https://example.org/repo.git?token=secret"
            "https://example.org/repo.git#secret"
            "ssh://user:secret@example.org/repo.git"
          ];
      expected = true;
    };
    testSshUserIsAnIdentity = {
      expr =
        (make {
          remotes.origin = git.remotes.origin // {
            url = "ssh://git@example.org/repo.git";
          };
        }).sourceState.git.remotes.origin.url;
      expected = "ssh://git@example.org/repo.git";
    };
    testPlainSource = {
      expr = (purifier.sourceInput { inherit src; }).sourceState.git;
      expected = null;
    };
    testOriginalSourcePreserved = {
      expr = original.src;
      expected = src;
    };
    testBranchChangeInvalidates = {
      expr =
        (make {
          head = {
            oid = head;
            ref = null;
          };
        }).identity != original.identity;
      expected = true;
    };
    testTagChangeInvalidates = {
      expr =
        (make {
          refs = git.refs // {
            "refs/tags/v1" = other;
          };
        }).identity != original.identity;
      expected = true;
    };
    testSourceChangeInvalidates = {
      expr =
        (purifier.sourceInput {
          src = builtins.toFile "source" "edited";
          inherit git;
        }).identity != original.identity;
      expected = true;
    };
    testObjectClosureChangeInvalidates = {
      expr = (make { objects = builtins.toFile "objects" "more history"; }).identity != original.identity;
      expected = true;
    };
    testIndexChangeInvalidates = {
      expr = (make { index = [ ]; }).identity != original.identity;
      expected = true;
    };
    testRemoteChangeInvalidates = {
      expr = (make { remotes = { }; }).identity != original.identity;
      expected = true;
    };
    testHistoryBoundaryInvalidates = {
      expr = (make { shallow = [ ]; }).identity != original.identity;
      expected = true;
    };
    testReferencesRetained = {
      expr = builtins.attrNames (builtins.getContext (builtins.toJSON original.sourceState));
      expected = lib.sort builtins.lessThan [
        (toString src)
        (toString objects)
      ];
    };
    testAmbientPathRejected = {
      expr = fails (purifier.sourceInput { src = "/tmp/ambient"; });
      expected = true;
    };
    testAmbientObjectsRejected = {
      expr = fails (make {
        objects = "/tmp/ambient";
      });
      expected = true;
    };
    testMissingHistoryDeclarationRejected = {
      expr = fails (
        purifier.sourceInput {
          inherit src;
          git = removeAttrs git [ "shallow" ];
        }
      );
      expected = true;
    };
    testUnknownFieldsRejected = {
      expr = fails (make {
        dirty = false;
      });
      expected = true;
    };
    testInconsistentHeadRejected = {
      expr = fails (make {
        refs = { };
      });
      expected = true;
    };
    testShortObjectRejected = {
      expr = fails (make {
        refs."refs/heads/main" = "0123456";
      });
      expected = true;
    };
    testRefTraversalRejected = {
      expr = fails (make {
        refs = git.refs // {
          "refs/heads/a/../b" = head;
        };
      });
      expected = true;
    };
    testDuplicateIndexRejected = {
      expr = fails (make {
        index = git.index ++ git.index;
      });
      expected = true;
    };
    testIndexTraversalRejected = {
      expr = fails (make {
        index = [ ((builtins.head git.index) // { path = "../file"; }) ];
      });
      expected = true;
    };
    testIndexStagePreserved = {
      expr = (make { index = [ ((builtins.head git.index) // { stage = 2; }) ]; }).sourceState.git.index;
      expected = [ ((builtins.head git.index) // { stage = 2; }) ];
    };
    testSha256Accepted = {
      expr =
        (make {
          objectFormat = "sha256";
          head = {
            oid = h256;
            ref = null;
          };
          refs = { };
          shallow = [ ];
          index = [ ];
        }).sourceState.git.objectFormat;
      expected = "sha256";
    };
    testListOrderCanonical = {
      expr =
        (make {
          shallow = [
            other
            head
          ];
        }).identity == (make {
          shallow = [
            head
            other
          ];
        }).identity;
      expected = true;
    };
  };
  h256 = builtins.hashString "sha256" "commit";
  failures = lib.debug.runTests tests;
in
assert failures == [ ] || throw (builtins.toJSON failures);
pkgs.runCommand "purifier-source-input-model" { } "touch $out"
