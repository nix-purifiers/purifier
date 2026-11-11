# SPDX-License-Identifier: MIT
# Opt-in resource-consumer test recipes. Existing SDK fixture recipes are unchanged.
{ pkgs, olderRubySource }:
let
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
  policy =
    role:
    pkgs.writeText "resource-recipe-v1-${role}.json" (
      builtins.toJSON {
        format = "nix-purifiers-resource-test-recipe";
        recipeVersion = 1;
        inherit role;
        objectInventory = (builtins.fromJSON (builtins.readFile ./recipe-v1-objects.json)).${role} or null;
        opensslGeneratedDate = if role == "openssl097" then "Thu Jan  1 00:00:00 UTC 1970" else null;
      }
    );
  helper = mode: role: ''
    ${pkgs.python3}/bin/python3 -B ${./recipe-v1.py} ${mode} ${role} ${./recipe-v1-objects.json} ${./bounded-command.py} "$out" "$TMPDIR/resource-recipe-v1-${role}.json"
  '';
  originalOpenSSL = import ../rubygems0811/openssl097.nix { inherit pkgs old; };
  openssl = pkgs.lib.overrideDerivation originalOpenSSL (previous: {
    name = "openssl-0.9.7m-resource-metadata-v1";
    postBuild = (previous.postBuild or "") + helper "openssl-date" "openssl097";
    postInstall =
      (previous.postInstall or "")
      + helper "openssl-install" "openssl097"
      + ''
        mkdir -p "$out/share"
        cp ${policy "openssl097"} "$out/share/nix-purifiers-resource-recipe-v1.json"
      '';
  });
  ordered =
    role: name: original: extra:
    pkgs.lib.overrideDerivation original (
      previous:
      extra
      // {
        inherit name;
        postBuild = (previous.postBuild or "") + helper "ruby-link" role;
        postInstall =
          (previous.postInstall or "")
          + helper "ruby-install" role
          + ''
            mkdir -p "$out/share"
            cp ${policy role} "$out/share/nix-purifiers-resource-recipe-v1.json"
          '';
      }
    );
  runtime = ordered "ruby160" "ruby-1.6.0-resource-sdk-v1" (import ./runtime.nix {
    inherit pkgs olderRubySource;
  }) { };
  generator =
    ordered "ruby180" "ruby-1.8.0-resource-generator-v1"
      (import ../rubygems0811/runtime.nix { inherit pkgs olderRubySource; })
      {
        buildInputs = [
          old.zlib
          openssl
          old.ncurses
          old.readline
        ];
        # The older non-cross builder duplicated this list before overriding.
        nativeBuildInputs = [
          old.zlib
          openssl
          old.ncurses
          old.readline
        ];
      };
in
{
  inherit runtime generator openssl;
}
