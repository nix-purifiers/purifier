# SPDX-License-Identifier: MIT
"""Native package identity, authored dates and repeatable legacy gem archives."""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("sdks", nargs="+", type=Path)
parser.add_argument("--codec", type=Path,
                    default=Path(__file__).resolve().parents[2] / "tools/rubygems_codec.rb")
parser.add_argument("--output", type=Path)
args = parser.parse_args()
codec = args.codec.resolve()


def run_ruby(arguments, directory, environment):
    result = subprocess.run(arguments, cwd=directory, env=environment,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return result

# Deliberately uses only syntax and core APIs available in genuine Ruby 1.8.
builder = '''require "rubygems"
require "rubygems/package"
original_package = Gem::Package
original_kind = Gem::Package.class
native_epoch = Gem.respond_to?(:source_date_epoch) ? Gem.method(:source_date_epoch) : nil
require ARGV.shift
abort "native package object/type replaced" unless Gem::Package.equal?(original_package) && Gem::Package.class == original_kind
abort "native epoch method replaced" if native_epoch && native_epoch != Gem.method(:source_date_epoch)
["2001-02-03", Time.utc(2001,2,3), Time.now.utc].each do |authored|
  spec = Gem::Specification.new { |s| s.date = authored }
  expected = authored.is_a?(String) ? Time.utc(2001,2,3) : Time.utc(authored.year, authored.month, authored.day)
  abort "authored date changed" unless spec.date == expected
end
spec = Gem::Specification.new do |s|
  s.name = "codec_fixture"; s.version = "1.0.0"; s.authors = ["fixture"]
  s.summary = "native epoch regression"; s.files = ["value.rb"]
  s.date = "2001-02-03" if ARGV.shift == "authored"
end
if Gem::Package.respond_to?(:build)
  Gem::Package.build(spec)
else
  require "rubygems/builder"
  Gem::Builder.new(spec).build
end
puts "SDK|#{RUBY_VERSION}|#{Gem::VERSION}|#{Gem::Package.class}"
'''
results = []
with tempfile.TemporaryDirectory(prefix="rubygems-epoch-") as temporary:
    root = Path(temporary)
    for index, sdk in enumerate(args.sdks):
        ruby = (sdk / "bin/ruby").resolve()
        directory = root / str(index)
        directory.mkdir()
        payload = directory / "value.rb"
        payload.write_text("VALUE=42\n")
        environment = {key: value for key, value in os.environ.items()
                       if not key.startswith(("RUBY", "GEM_", "BUNDLE_", "BUNDLER_PURIFIER_"))}
        environment.update(HOME=str(directory), SOURCE_DATE_EPOCH="1")
        archives = []
        for attempt in range(2):
            # Native file mtimes and wall time must not leak into the archive.
            os.utime(payload, (1420070400 + attempt, 1420070400 + attempt))
            run = run_ruby([str(ruby), "-e", builder, str(codec), "default"],
                           directory, environment)
            data = (directory / "codec_fixture-1.0.0.gem").read_bytes()
            with tarfile.open(fileobj=io.BytesIO(data)) as outer:
                assert all(member.mtime == 1 for member in outer), "outer tar timestamp"
                for name in ("metadata.gz", "data.tar.gz"):
                    compressed = outer.extractfile(name).read()
                    assert int.from_bytes(compressed[4:8], "little") == 1, (name, "gzip timestamp")
                metadata = gzip.decompress(outer.extractfile("metadata.gz").read()).decode()
                assert "1970-01-01" in re.search(r"^date: (.*)$", metadata, re.M)[1]
                with tarfile.open(fileobj=io.BytesIO(gzip.decompress(outer.extractfile("data.tar.gz").read()))) as inner:
                    assert all(member.mtime == 1 for member in inner), "payload tar timestamp"
            archives.append(data)
            if attempt == 0:
                time.sleep(2)
        assert archives[0] == archives[1], "independent native archives differ"
        run_ruby([str(ruby), "-e", builder, str(codec), "authored"],
                 directory, environment)
        with tarfile.open(directory / "codec_fixture-1.0.0.gem") as outer:
            metadata = gzip.decompress(outer.extractfile("metadata.gz").read()).decode()
            assert "2001-02-03" in re.search(r"^date: (.*)$", metadata, re.M)[1], "authored archive date changed"
        actual = next(line for line in run.stdout.splitlines() if line.startswith("SDK|"))
        result = {"sdk": actual, "archiveSha256": hashlib.sha256(archives[0]).hexdigest(),
                  "packageObjectAndTypePreserved": True, "authoredDatesPreserved": True,
                  "nativeEpochMethodPreserved": True, "allTarGzipAndDefaultDateEpochControls": True,
                  "repeatedNativeArchivesByteIdentical": True}
        results.append(result)
        print("PASS " + actual + ": native identity, explicit dates, epoch headers, deterministic archives")
if args.output:
    args.output.write_text(json.dumps({"codecSha256": hashlib.sha256(codec.read_bytes()).hexdigest(),
                                      "results": results}, indent=2) + "\n")
