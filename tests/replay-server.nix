# SPDX-License-Identifier: MIT
#
# The replay server (lib.purifier.replayServer) behind nixpkgs' mitm-cache
# setup hook, over HTTPS: a file is served as its bytes, and a directory
# URL from its index.html, with the Content-Type text/html that pip
# requires of an index page. The replay tree holds an inline entry, as a
# handler writes one (tools/http_records.py).
{ pkgs, purifier }:
let
  tree = pkgs.runCommand "purifier-test-replay-tree" { nativeBuildInputs = [ pkgs.python3 ]; } ''
    cd ${../tools}
    python3 -c '
    import http_records, json, os, sys
    out = sys.argv[1]
    entries = [
        http_records.inline_entry(http_records.index_path("https://index.test/simple/demo/"), "<html>demo</html>\n"),
        http_records.inline_entry(http_records.url_path("https://files.test/demo-1.0.tar.gz"), "tarball\n"),
    ]
    for entry in entries:
        path = os.path.join(out, entry["path"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(entry["contents"])
    ' $out
  '';
in
pkgs.runCommand "purifier-test-replay-server"
  {
    nativeBuildInputs = [
      (purifier.replayServer { inherit (pkgs) mitm-cache; })
      pkgs.python3
    ];
    mitmCache = tree;
  }
  ''
    mitmCacheConfigureHook
    for _ in $(seq 50); do
      python3 -c "import socket, sys; socket.create_connection(('$MITM_CACHE_HOST', $MITM_CACHE_PORT)).close()" 2>/dev/null && break
      sleep 0.1
    done
    python3 -c '
    import os, ssl, urllib.request
    proxy = "http://" + os.environ["https_proxy"]
    # The context pip checks certificates with, which, unlike
    # ssl.create_default_context, does not require the extensions that
    # the certificates mitm-cache makes leave out.
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cafile=os.environ["SSL_CERT_FILE"])
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"https": proxy}),
        urllib.request.HTTPSHandler(context=context),
    )
    page = opener.open("https://index.test/simple/demo/")
    assert page.headers.get("Content-Type", "").startswith("text/html"), page.headers
    assert page.read() == b"<html>demo</html>\n"
    tarball = opener.open("https://files.test/demo-1.0.tar.gz")
    assert "html" not in tarball.headers.get("Content-Type", ""), tarball.headers
    assert tarball.read() == b"tarball\n"
    print("ok")
    '
    touch $out
  ''
