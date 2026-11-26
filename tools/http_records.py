# SPDX-License-Identifier: MIT
"""The HTTP records of a lock run, and the handler protocol over them.

A purifier whose lock run puts a recording proxy in front of the build,
as cmake-purifier does with mitmproxy, writes one JSON object per line
for each response the build received:

    {"method": "GET", "url": ..., "status": 200, "hash": "sha256-..."}
    {"method": "GET", "url": ..., "status": 302, "location": ...}

`hash` is the SRI SHA-256 of the body of a successful GET; `location` is
the target of a redirect. The sandbox build replays these downloads with
the library's replay server (lib.purifier.replayServer), which serves a
URL from `<scheme>/<host>/<path>` of a directory tree (url_path), and a
directory URL from the index.html in that directory (index_path).

A handler is a program that takes such records on standard input and
prints one JSON object on standard output:

    {"claimed": [<url>, ...], "entries": [<download entry>, ...]}

It claims the URLs whose responses it understands better than a replay
of their bytes, such as the pages of a package index, which change
whenever a project publishes a release. Its entries are download entries
of the library, at the paths the replay server reads, and replace the
claimed responses in the replay tree: file entries for the files the
build fetched, and inline entries for what it generates from them. The
host purifier, whose lock run made the records, drops the claimed URLs
from its own entries, adds the handler's entries to its lockfile, and
lays them out with the rest. A handler's output depends on its input
alone, so a relock reproduces the lockfile.

A handler written in Python calls run() with a function from the
records to the claimed URLs and the entries.
"""
import json
import sys
import urllib.parse


def url_path(url):
    """The path in the replay tree that serves a URL: <scheme>/<host>/<path>,
    with the port after the host when the URL names one, except 443 of
    https, which the proxy leaves out of the authority it replays."""
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ""
    if parts.port and not (parts.scheme == "https" and parts.port == 443):
        host = f"{host}:{parts.port}"
    components = [c for c in parts.path.split("/") if c]
    return "/".join(c for c in [parts.scheme, host, *components] if c)


def index_path(url):
    """The path in the replay tree of the page served for a directory URL."""
    return url_path(url) + "/index.html"


def read_records(stream):
    """The records of a stream of JSON lines, skipping blank lines."""
    return [json.loads(line) for line in stream if line.strip()]


def successful_gets(records):
    """The successful GETs of records, by URL, each with its hash."""
    return {r["url"]: r for r in records if r["method"] == "GET" and r.get("status") == 200 and "hash" in r}


def file_entry(url, sri_hash):
    """A file download entry of the library, at the replay path of its URL."""
    return {"path": url_path(url), "url": url, "mirrors": [], "hash": sri_hash}


def inline_entry(path, contents):
    """An inline entry of the library: a file the replay tree holds as written."""
    return {"path": path, "contents": contents}


def run(handle):
    """Runs a handler: reads the records from standard input, calls
    handle(records), which returns the claimed URLs and the entries, and
    prints the result, sorted, as the protocol has it."""
    claimed, entries = handle(read_records(sys.stdin))
    json.dump(
        {"claimed": sorted(set(claimed)), "entries": sorted(entries, key=lambda e: e["path"])},
        sys.stdout,
        indent=2,
        sort_keys=True,
    )
    sys.stdout.write("\n")
