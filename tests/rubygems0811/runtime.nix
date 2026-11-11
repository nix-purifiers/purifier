# SPDX-License-Identifier: MIT
# Original Ruby 1.8.0 source; this release has no RUBY_PATCHLEVEL constant.
{ pkgs, olderRubySource }:
let
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
in
old.stdenv.mkDerivation {
  name = "ruby-1.8.0";
  version = "1.8.0";
  src = pkgs.fetchurl {
    url = "https://cache.ruby-lang.org/pub/ruby/1.8/ruby-1.8.0.tar.gz";
    hash = "sha256-EVxf4KFXCavRtkNRqhvtnAMNHz13ytPy8rULNwTCAfE=";
  };
  buildInputs = [
    old.zlib
    (import ./openssl097.nix { inherit pkgs old; })
    old.ncurses
    old.readline
  ];
  CC = "gcc";
  preConfigure = ''
    command -v "$CC"
    "$CC" --version
    "$CC" -dumpmachine
  '';
  NIX_CFLAGS_COMPILE = "-O0 -fno-omit-frame-pointer -fno-strict-aliasing";
  configureFlags = [
    "--enable-shared"
    "--disable-pthread"
    "--disable-asm"
    "--enable-dlstack"
    "--build=i686-pc-linux-gnu"
    "--host=i686-pc-linux-gnu"
  ];
  doInstallCheck = true;
  installCheckPhase = ''
    "$out/bin/ruby" -e 'require "zlib"; require "openssl"; require "dl"; require "timeout"; 10.times { Timeout.timeout(1) { sleep 0.01 } }; abort unless RUBY_VERSION == "1.8.0"; abort if defined?(RUBY_PATCHLEVEL); puts ["OBSERVED",RUBY_VERSION,RUBY_PLATFORM,["pointer"].pack("p").size].join("|"); abort unless RUBY_PLATFORM == "i686-linux-gnu" && ["pointer"].pack("p").size == 4; puts [RUBY_VERSION, RUBY_RELEASE_DATE, RUBY_PLATFORM, ["pointer"].pack("p").size, OpenSSL::OPENSSL_VERSION].join("|")'
  '';
  passthru = {
    libPath = "lib/ruby/1.8";
    gemPath = "lib/ruby/gems/1.8";
  };
}
