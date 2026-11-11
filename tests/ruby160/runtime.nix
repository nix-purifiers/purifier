# SPDX-License-Identifier: MIT
# Original Ruby1.6.0, native i686 test consumer; no source patches.
{ pkgs, olderRubySource }:
let
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
in
old.stdenv.mkDerivation {
  name = "ruby-1.6.0-original-target-feasibility";
  src = pkgs.fetchurl {
    url = "https://cache.ruby-lang.org/pub/ruby/1.6/ruby-1.6.0.tar.gz";
    hash = "sha256-ps0xH74yfbXzexl1PAtQq+f4eSYSz3rExRqAJmHQcDE=";
  };
  CC = "gcc";
  preConfigure = ''
    command -v "$CC"
    "$CC" --version
    "$CC" -dumpmachine
  '';
  NIX_CFLAGS_COMPILE = "-O0 -fno-strict-aliasing -fno-omit-frame-pointer";
  configureFlags = [
    "--enable-shared"
    "--build=i686-pc-linux-gnu"
    "--host=i686-pc-linux-gnu"
  ];
  doInstallCheck = true;
  installCheckPhase = ''
    "$out/bin/ruby" -e 'raise unless RUBY_VERSION=="1.6.0" && RUBY_RELEASE_DATE=="2000-09-19" && ["pointer"].pack("p").size==4;raise if defined?(RUBY_PATCHLEVEL);puts ["ORIGINAL160",RUBY_VERSION,RUBY_RELEASE_DATE,RUBY_PLATFORM,["pointer"].pack("p").size].join("|")'
  '';
}
