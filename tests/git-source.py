# SPDX-License-Identifier: MIT
"""Exercise source/index separation, reachable objects, and replay rejection."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile

spec = importlib.util.spec_from_file_location('git_source', Path(__file__).parents[1] / 'tools/git_source.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)
with tempfile.TemporaryDirectory() as temporary:
    root = Path(temporary)
    source = root / 'native'
    source.mkdir()
    home = root / 'home'
    home.mkdir()
    env = g.controlled_env(home)
    def git(*args):
        return g.run(source, list(args), env).stdout
    git('init', '--quiet', '--template=')
    (source / 'tracked').write_text('committed\n')
    git('add', 'tracked')
    git('-c', 'user.name=Source Test', '-c', 'user.email=source@example.invalid', 'commit', '-qm', 'initial')
    git('-c', 'user.name=Source Test', '-c', 'user.email=source@example.invalid', 'tag', '-a', 'v1', '-m', 'annotated')
    (source / 'tracked').write_text('indexed\n')
    git('add', 'tracked')
    (source / 'tracked').write_text('working\n')
    (source / 'untracked').write_text('untracked\n')
    index = (source / '.git/index').read_bytes()
    # Capture must ignore ambient Git repository redirection.
    os.environ['GIT_DIR'] = str(root / 'poison')
    export = root / 'capture'
    g.capture(source, export, home)
    assert (source / '.git/index').read_bytes() == index
    destination = root / 'replayed'
    g.replay(export, destination, home)
    assert (destination / 'tracked').read_text() == 'working\n'
    assert (destination / 'untracked').read_text() == 'untracked\n'
    for query in [['rev-parse', 'HEAD'], ['show', ':tracked'], ['show-ref'], ['ls-files', '--stage']]:
        assert g.run(source, query, env).stdout == g.run(destination, query, env).stdout, query
    payload = next((export / 'objects/payloads').iterdir())
    payload.write_bytes(b'tampered')
    try:
        g.validate(export)
    except g.Invalid:
        pass
    else:
        raise AssertionError('corrupt object accepted')
print('source/index separation, native query parity, isolation and object rejection passed')
