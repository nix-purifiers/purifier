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
  stateBuild =
    input:
    pkgs.runCommand "source-state-identity" {
      sourceState = builtins.toJSON input.sourceState;
    } "touch $out";
  tests = {
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
