# SPDX-License-Identifier: MIT
"""Run the original native32 interpreter against twenty pinned gzip controls."""
from pathlib import Path
import gzip, hashlib, importlib.util, json, os, sys, zlib
ruby, inputs, helper, output = map(Path, sys.argv[1:])
spec = importlib.util.spec_from_file_location('bounded', helper)
bounded = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bounded)
output.mkdir()
rows = json.loads((inputs/'manifest.json').read_text())
assert len(rows) == 20
files = []
for row in rows:
    path = inputs/row['path']
    assert path.parent == inputs
    raw = path.read_bytes()
    payload = gzip.decompress(raw)
    assert hashlib.sha256(raw).hexdigest() == row['compressedSha256']
    assert hashlib.sha256(payload).hexdigest() == row['uncompressedSha256']
    assert zlib.crc32(payload) == row['crc32']
    files.append(path)
assert sum(row['crc32'] >= 0x80000000 for row in rows) == 10
env = {k:v for k,v in os.environ.items() if not k.startswith(('RUBY','GEM_','BUNDLE_','BUNDLER_'))}
env['HOME'] = os.environ['TMPDIR']
commands = []
def run(label, args):
    args = list(map(str,args))
    wrapper = 'import subprocess,sys,json;p=subprocess.run(sys.argv[1:],capture_output=True);print(json.dumps(dict(exit=p.returncode,stdout=p.stdout.hex(),stderr=p.stderr.hex())))'
    result = json.loads(bounded.run([sys.executable,'-c',wrapper,*args],env))
    row = {'label':label,'argv':args,'exit':result['exit']}
    for stream in ['stdout','stderr']:
        data = bytes.fromhex(result[stream])
        (output/(label+'.'+stream)).write_bytes(data)
        row[stream+'Sha256'] = hashlib.sha256(data).hexdigest()
    commands.append(row)
    assert result['exit'] == 0, result
    return bytes.fromhex(result['stdout']).decode()
abi = run('actual32-abi',[ruby,'-e','raise unless RUBY_VERSION=="1.8.0" && RUBY_RELEASE_DATE=="2003-08-04" && RUBY_PLATFORM=="i686-linux-gnu" && ["pointer"].pack("p").size==4 && !defined?(RUBY_PATCHLEVEL);puts "ORIGINAL180|i686-linux-gnu|4"'])
assert abi.strip() == 'ORIGINAL180|i686-linux-gnu|4'
code = 'require "zlib";require "digest/sha2";ARGV.each{|path|s=Zlib::GzipReader.open(path){|f|f.read};puts Digest::SHA256.hexdigest(s)}'
actual = run('native20-crc',[ruby,'-e',code,*files]).splitlines()
assert actual == [row['uncompressedSha256'] for row in rows]
receipt = dict(complete=True,native32All20Pass=True,targetSystem='i686-linux',executionArena='confined Nix build sandbox',commands=commands,identicalInputHashes=[dict(name=p.name,sha256=hashlib.sha256(p.read_bytes()).hexdigest()) for p in files])
(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
