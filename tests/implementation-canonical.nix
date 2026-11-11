{ pkgs }:
let
  revision = "25b4325aae46102c238df84c194ac79356415549";
  upstream = "https://raw.githubusercontent.com/nix-purifiers/pnpm-purifier/${revision}";
  native = pkgs.fetchurl {
    url = "${upstream}/src/lib.mjs";
    hash = "sha256-ZvoJblx2axQV2Maua5WyT4QDjEvc3IX5Db/TIN0j73A=";
  };
  prepare = pkgs.fetchurl {
    url = "${upstream}/tests/fixtures/prepare/pnpm-purifier.lock.json";
    hash = "sha256-I8Ve5sF6E6Bvig91DzxkbwB4qH+c4vJqF7ZBsHoIiQM=";
  };
  sources = pkgs.fetchurl {
    url = "${upstream}/tests/fixtures/sources/pnpm-purifier.lock.json";
    hash = "sha256-pg50w+U48UWnOT74GeFInJQ4nD3b3PJ79DSJKPCSprI=";
  };
in
pkgs.runCommand "purifier-canonical-implementation-checksum"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.nodejs
      pkgs.nix
    ];
    PNPM_NATIVE = native;
    PNPM_PREPARE = prepare;
    PNPM_SOURCES = sources;
  }
  ''
    mkdir -p tools tests
    cp ${../tools/implementation.py} tools/implementation.py
    cp ${./test_implementation_canonical.py} tests/test_implementation_canonical.py
    python -B tests/test_implementation_canonical.py
    touch "$out"
  ''
