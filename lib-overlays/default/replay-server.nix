# SPDX-License-Identifier: MIT
#
# replayServer { mitm-cache }: the mitm-cache that a purifier replays a
# build's downloads with, nixpkgs' package with one change
# (pkgs/replay-server/directory-index.patch): a URL whose path is a
# directory of the replay tree is served from the index.html in that
# directory, with the Content-Type text/html. A page of a Python package
# index, `/simple/<project>/`, is such a URL, and pip reads a page only
# with an HTML or a simple-API Content-Type. The setup hook and the
# command are unchanged, so a purifier passes the result wherever it
# passes mitm-cache.
{ lib }:
{ mitm-cache }:
mitm-cache.overrideAttrs (old: {
  patches = (old.patches or [ ]) ++ [ ../../pkgs/replay-server/directory-index.patch ];
})
