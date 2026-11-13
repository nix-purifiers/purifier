# SPDX-License-Identifier: MIT
"""Capture and replay explicit Git source inputs for the supported subset.

Dependency locks do not contain this state. Object payloads retain their native
IDs; working contents and index entries are independent inputs.
"""
from pathlib import Path, PurePosixPath
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
from urllib.parse import urlsplit

MAX_OBJECT = 64 * 1024 * 1024
MAX_BYTES = 256 * 1024 * 1024
MAX_COUNT = 100000
GIT = shutil.which('git')

class Invalid(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise Invalid(message)

def write_json(path, data):
    path.write_text(json.dumps(data, sort_keys=True, indent=2) + '\n')

def safe_path(value):
    require(isinstance(value, str) and value and not value.startswith('/'), 'unsafe relative path')
    parts = value.split('/')
    require(all(p not in ('', '.', '..') and p.lower() != '.git' for p in parts), 'unsafe path component')
    require(not any(ord(c) < 32 or ord(c) == 127 for c in value), 'control character in path')
    return value

def beneath(root, name):
    safe_path(name)
    target = root / name
    parent = target.parent
    while parent != root:
        require(not parent.is_symlink(), 'symlink ancestor')
        parent = parent.parent
    require(not root.is_symlink(), 'symlink root')
    return target

def controlled_env(home):
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update(HOME=str(home), XDG_CONFIG_HOME=str(home / 'config'), GIT_CONFIG_NOSYSTEM='1',
               GIT_CONFIG_GLOBAL=os.devnull, GIT_NO_REPLACE_OBJECTS='1', GIT_NO_LAZY_FETCH='1',
               GIT_TERMINAL_PROMPT='0', GIT_OPTIONAL_LOCKS='0', LC_ALL='C', TZ='UTC')
    return env

def run(source, args, env, data=None, ok=(0,)):
    argv = [GIT, '-c', 'protocol.allow=never', '-c', 'core.fsmonitor=false', *args]
    p = subprocess.run(argv, cwd=source, env=env, input=data, capture_output=True, timeout=60)
    require(p.returncode in ok, 'native Git command failed: ' + args[0])
    return p

def oid_valid(oid, algorithm):
    return re.fullmatch('[0-9a-f]{' + ('40' if algorithm == 'sha1' else '64') + '}', oid) is not None

def object_oid(kind, data, algorithm):
    return hashlib.new(algorithm, kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).hexdigest()

def children(kind, data, algorithm):
    width = 20 if algorithm == 'sha1' else 32
    if kind in ('commit', 'tag'):
        headers = data.split(b'\n\n', 1)[0].splitlines()
        tree = [x[5:].decode('ascii') for x in headers if x.startswith(b'tree ')]
        parents = [x[7:].decode('ascii') for x in headers if x.startswith(b'parent ')]
        if kind == 'commit':
            require(len(tree) == 1, 'commit needs one tree')
            result = [(x, 'tree') for x in tree] + [(x, 'commit') for x in parents]
        else:
            targets = [x[7:].decode('ascii') for x in headers if x.startswith(b'object ')]
            types = [x[5:].decode('ascii') for x in headers if x.startswith(b'type ')]
            require(len(targets) == len(types) == 1, 'invalid annotated tag')
            result = [(targets[0], types[0])]
    elif kind == 'tree':
        result = []
        offset = 0
        while offset < len(data):
            end = data.index(b'\0', offset)
            header = data[offset:end]
            require(b' ' in header, 'invalid tree header')
            mode, name = header.split(b' ', 1)
            require(name and b'/' not in name and name not in (b'.', b'..'), 'invalid tree name')
            raw = data[end + 1:end + 1 + width]
            require(len(raw) == width, 'truncated tree object ID')
            oid = raw.hex()
            if mode == b'40000':
                result.append((oid, 'tree'))
            elif mode in (b'100644', b'100755', b'120000'):
                result.append((oid, 'blob'))
            else:
                require(mode == b'160000', 'unsupported tree mode')
            offset = end + 1 + width
    else:
        require(kind == 'blob', 'unsupported object type')
        result = []
    require(all(oid_valid(x, algorithm) and t in ('commit', 'tree', 'blob', 'tag') for x, t in result), 'invalid object edge')
    return result

def config_preflight(source, allow_path_policy=False):
    """Inspect names first; never serialize arbitrary credential configuration."""
    require(source.absolute() == source.resolve(), 'symlink source root/ancestor')
    gitdir = source / '.git'
    require(gitdir.is_dir() and not gitdir.is_symlink(), 'gitfile/worktree/bare input unsupported')
    for name in ['config', 'config.worktree', 'index', 'HEAD', 'packed-refs', 'shallow', 'info/attributes', 'info/exclude']:
        path = gitdir / name
        require(not path.is_symlink(), 'symlink Git metadata file: ' + name)
        if path.exists():
            require(path.is_file(), 'non-file Git metadata: ' + name)
    for name in ['objects', 'objects/pack', 'objects/info', 'info', 'refs', 'hooks']:
        path = gitdir / name
        require(not path.is_symlink(), 'symlink Git metadata directory: ' + name)
        if path.exists():
            require(path.is_dir(), 'non-directory Git metadata: ' + name)
    for name in ['objects', 'refs']:
        path = gitdir / name
        if path.exists():
            for directory, dirs, files in os.walk(path, followlinks=False):
                for child in dirs + files:
                    entry = Path(directory) / child
                    require(not entry.is_symlink(), 'symlink object/ref metadata')
                    require(entry.is_dir() or entry.is_file(), 'unsupported object/ref metadata type')
    attributes = gitdir / 'info/attributes'
    if attributes.exists():
        require(not attributes.read_bytes().strip(), 'local info/attributes unsupported')
    inspection_env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    p = subprocess.run([GIT, 'config', '--show-scope', '--name-only', '--list'], cwd=source,
                       env=inspection_env, capture_output=True, timeout=30)
    require(p.returncode == 0, 'cannot inspect effective Git configuration')
    for line in p.stdout.decode().splitlines():
        scope, key = line.split('\t', 1)
        if scope != 'local':
            # Authentication configuration cannot affect these local-only
            # reads. Values are never inspected or exported; native reads and
            # replay disable global/system configuration and lazy fetching.
            require(key in ('user.name', 'user.email', 'init.defaultbranch')
                    or key.startswith(('alias.', 'credential.')),
                    'unsupported ambient configuration key: ' + key)
    gitdir = source / '.git'
    require(gitdir.is_dir() and not gitdir.is_symlink(), 'gitfile/worktree/bare input unsupported')
    for name in ['commondir', 'objects/info/alternates', 'info/grafts', 'info/sparse-checkout',
                 'MERGE_HEAD', 'REBASE_HEAD', 'CHERRY_PICK_HEAD', 'rebase-merge', 'rebase-apply', 'sequencer']:
        require(not (gitdir / name).exists(), 'unsupported repository state: ' + name)
    require(not list(gitdir.glob('sharedindex.*')), 'split index unsupported')
    require(not list((gitdir / 'objects').glob('pack/*.promisor')), 'promisor objects unsupported')
    if (gitdir / 'hooks').exists():
        for p in (gitdir / 'hooks').iterdir():
            require(not p.is_symlink() and (p.name.endswith('.sample') or not os.access(p, os.X_OK)), 'active hook unsupported')
    exclude = gitdir / 'info/exclude'
    if exclude.exists():
        require(not exclude.is_symlink(), 'symlink exclude unsupported')
        require(not any(x.strip() and not x.lstrip().startswith('#') for x in exclude.read_text().splitlines()), 'custom excludes unsupported')
    p = subprocess.run([GIT, 'config', '--local', '--null', '--list'], cwd=source, env=inspection_env, capture_output=True, timeout=30)
    require(p.returncode == 0, 'cannot inspect local configuration')
    config = {}
    for record in p.stdout.split(b'\0'):
        if not record:
            continue
        key, value = record.split(b'\n', 1)
        key, value = key.decode(), value.decode()
        require(key not in config, 'duplicate local configuration unsupported')
        require(key in ('core.repositoryformatversion', 'core.filemode', 'core.bare', 'core.logallrefupdates', 'extensions.objectformat')
                or (allow_path_policy and key in ('core.ignorecase', 'core.precomposeunicode'))
                or re.fullmatch(r'remote\.[A-Za-z0-9_-]+\.(url|fetch)', key), 'unsupported local configuration key: ' + key)
        config[key] = value
    require(config.get('core.bare') == 'false' and config.get('core.filemode') == 'true', 'unsupported native bare/filemode policy')
    require(config.get('core.repositoryformatversion') in ('0', '1'), 'unsupported repository format')
    for key, value in config.items():
        if key.endswith('.fetch'):
            remote = key.split('.')[1]
            require(value == '+refs/heads/*:refs/remotes/' + remote + '/*', 'custom fetch mapping unsupported')
    return config

def facts(source, env, path_policy=True):
    config = config_preflight(source, allow_path_policy=path_policy)
    algorithm = run(source, ['rev-parse', '--show-object-format'], env).stdout.decode().strip()
    require(algorithm in ('sha1', 'sha256'), 'unsupported object format')
    head = run(source, ['rev-parse', 'HEAD'], env).stdout.decode().strip()
    symbolic = run(source, ['symbolic-ref', '--quiet', 'HEAD'], env, ok=(0, 1))
    headref = symbolic.stdout.decode().strip() if symbolic.returncode == 0 else None
    refs = {}
    symbols = {}
    raw = run(source, ['for-each-ref', '--format=%(refname)%00%(objectname)%00%(symref)'], env).stdout
    for line in raw.decode().splitlines():
        name, oid, symbol = line.split('\0')
        require(re.fullmatch(r'refs/(heads|tags|remotes)/.+', name), 'unrepresented ref namespace')
        require(oid_valid(oid, algorithm), 'invalid ref object ID')
        run(source, ['check-ref-format', name], env)
        refs[name] = oid
        if symbol:
            symbols[name] = symbol
    require(headref is None or refs.get(headref) == head, 'HEAD branch/ref mismatch')
    remotes = {}
    for key, value in config.items():
        if key.startswith('remote.') and key.endswith('.url'):
            name = key.split('.')[1]
            url = urlsplit(value)
            require(url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password
                    and not url.query and not url.fragment and not any(ord(c) < 32 for c in value), 'unsafe/unsupported remote identity')
            remotehead = 'refs/remotes/' + name + '/HEAD'
            target = symbols.pop(remotehead, None)
            default = None
            if target:
                prefix = 'refs/remotes/' + name + '/'
                require(target.startswith(prefix) and target in refs and refs[target] == refs[remotehead], 'remote symbolic-ref mismatch')
                default = 'refs/heads/' + target[len(prefix):]
            remotes[name] = {'url': value, 'defaultRef': default}
    require(not symbols, 'unrepresented symbolic refs')
    raw = run(source, ['ls-files', '--stage', '--debug', '-z'], env).stdout
    pattern = re.compile(rb'([0-7]{6}) ([0-9a-f]+) ([0-3])\t([^\0]*)\0  ctime: [^\n]*\n  mtime: [^\n]*\n  dev: [^\n]*\n  uid: [^\n]*\n  size: [^\n]*\tflags: ([0-9a-f]+)\n')
    index = []
    pos = 0
    while pos < len(raw):
        match = pattern.match(raw, pos)
        require(match is not None, 'unsupported index debug encoding')
        mode, oid, stage, path, flags = match.groups()
        mode, oid, path = mode.decode(), oid.decode(), path.decode()
        stage, flags = int(stage), int(flags, 16)
        safe_path(path)
        require(stage == 0 and mode in ('100644', '100755', '120000'), 'merge stages/gitlinks unsupported in prototype')
        require(flags & ~0x4000c000 == 0, 'unsupported index flags (including intent-to-add/fsmonitor)')
        require(oid_valid(oid, algorithm), 'invalid index object ID')
        index.append({'path': path, 'mode': mode, 'oid': oid, 'stage': stage,
                      'flags': {'assumeUnchanged': bool(flags & 0x8000), 'skipWorktree': bool(flags & 0x40000000), 'intentToAdd': False}})
        pos = match.end()
    shallow_path = source / '.git/shallow'
    require(not shallow_path.is_symlink(), 'symlink shallow boundary')
    shallow = shallow_path.read_text().splitlines() if shallow_path.exists() else []
    require(len(shallow) == len(set(shallow)) and all(oid_valid(x, algorithm) for x in shallow), 'invalid shallow boundary')
    paths = run(source, ['ls-files', '--cached', '--others', '--exclude-standard', '-z'], env).stdout.decode().rstrip('\0').split('\0')
    source_manifest = {}
    casefolded = {}
    for name in sorted(set(paths)):
        safe_path(name)
        if path_policy:
            name = actual_relative(source, name)
            if name is None:
                continue
        else:
            require(name.casefold() not in casefolded or casefolded[name.casefold()] == name, 'case collision')
            casefolded[name.casefold()] = name
        path = beneath(source, name)
        if path.is_symlink():
            data = os.readlink(path).encode()
            source_manifest[name] = {'kind': 'symlink', 'target': data.decode(), 'sha256': hashlib.sha256(data).hexdigest()}
        elif path.exists():
            require(path.is_file(), 'non-file source entry')
            source_manifest[name] = {'kind': 'file', 'executable': bool(path.stat().st_mode & 0o111), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    git = {'objectFormat': algorithm, 'head': {'oid': head, 'ref': headref}, 'refs': refs,
           'shallow': sorted(shallow), 'objects': 'objects', 'index': sorted(index, key=lambda x: x['path']), 'remotes': remotes}
    if path_policy:
        git['pathPolicy'] = make_path_policy(source, env, source_manifest)
        validate_path_policy(git['pathPolicy'], git, source_manifest)
    return {'git': git, 'source': source_manifest}

def object_roots(git):
    return set([git['head']['oid'], *git['refs'].values(), *(x['oid'] for x in git['index'])])

PATH_QUERIES = {
    'statusPorcelainV1Z': ['status', '--porcelain=v1', '-z'],
    'indexStageZ': ['ls-files', '--stage', '-z'],
    'untrackedZ': ['ls-files', '--others', '--exclude-standard', '-z'],
}

def path_nodes(manifest):
    """Working names only: indexed spellings belong to a separate namespace."""
    nodes = {}
    for name in manifest:
        parts = safe_path(name).split('/')
        for i, part in enumerate(parts):
            directory = '/'.join(parts[:i]) or '.'
            nodes.setdefault(directory, set()).add(part)
        require(not any('/'.join(parts[:i]) in manifest for i in range(1, len(parts))),
                'working source file/directory prefix collision')
    return nodes

def native_relation(root, directory, entry, alternate):
    """A finite native lookup observation, not a Unicode equivalence heuristic."""
    parent = root if directory == '.' else beneath(root, directory)
    require(parent.is_dir() and not parent.is_symlink(), 'unobserved path-policy directory')
    names = os.listdir(parent)
    require(entry in names, 'path-policy witness has no exact native entry')
    original = (parent / entry).lstat()
    try:
        alternative = (parent / alternate).lstat()
    except FileNotFoundError:
        return 'distinct'
    # Equal inode alone is insufficient: two hardlink names are distinct entries.
    if alternate in names:
        return 'distinct'
    return 'alias' if (original.st_dev, original.st_ino, stat.S_IFMT(original.st_mode)) == (
        alternative.st_dev, alternative.st_ino, stat.S_IFMT(alternative.st_mode)) else 'distinct'

def actual_relative(root, logical):
    """Resolve native Git's logical spelling to existing raw directory entries."""
    parts = safe_path(logical).split('/')
    current = root
    actual = []
    for offset, part in enumerate(parts):
        names = os.listdir(current)
        if part not in names:
            try:
                desired = (current / part).lstat()
            except FileNotFoundError:
                return None
            matches = []
            for name in names:
                item = (current / name).lstat()
                if (item.st_dev, item.st_ino, stat.S_IFMT(item.st_mode)) == (
                        desired.st_dev, desired.st_ino, stat.S_IFMT(desired.st_mode)):
                    matches.append(name)
            require(len(matches) == 1, 'ambiguous logical/native working pathname')
            part = matches[0]
        part.encode('utf-8')
        actual.append(part)
        current = current / part
        if offset < len(parts) - 1:
            require(current.is_dir() and not current.is_symlink(), 'symlink working path ancestor')
    return safe_path('/'.join(actual))

def policy_observations(source, env):
    result = {}
    for name, command in PATH_QUERIES.items():
        data = run(source, command, env).stdout
        require(len(data) <= MAX_OBJECT, 'path-policy query byte limit exceeded')
        result[name] = data.hex()
    return result

def case_alternate(name):
    alternate = next((name[:i] + c.swapcase() + name[i + 1:]
                      for i, c in enumerate(name) if c.isascii() and c.isalpha()), None)
    return alternate if alternate is not None else name.swapcase() if name.swapcase() != name else None

def make_path_policy(source, env, manifest):
    flags = {}
    for name, key in [('ignoreCase', 'core.ignorecase'), ('precomposeUnicode', 'core.precomposeunicode')]:
        value = run(source, ['config', '--type=bool', '--get', key], env, ok=(0, 1))
        require(value.returncode == 1 or value.stdout in (b'true\n', b'false\n'), 'invalid native path policy boolean')
        flags[name] = value.returncode == 0 and value.stdout == b'true\n'
    witnesses = []
    for directory, names in sorted(path_nodes(manifest).items()):
        case = None
        for name in sorted(names):
            alternate = case_alternate(name)
            if alternate is not None:
                case = {'directory': directory, 'entry': name, 'alternate': alternate, 'kind': 'case',
                        'relation': native_relation(source, directory, name, alternate)}
                break
        require(case is not None, 'unsupported path-policy directory without a case witness')
        witnesses.append(case)
        for name in sorted(names):
            if name.isascii():
                continue
            for alternate in sorted({unicodedata.normalize('NFC', name), unicodedata.normalize('NFD', name)} - {name}):
                witnesses.append({'directory': directory, 'entry': name, 'alternate': alternate,
                                  'kind': 'normalization', 'relation': native_relation(source, directory, name, alternate)})
    witnesses.sort(key=lambda x: tuple(x[k].encode() for k in ['directory', 'kind', 'entry', 'alternate']))
    require(len(witnesses) <= MAX_COUNT, 'path-policy witness count limit exceeded')
    require(all((x['relation'] == 'alias') == flags['ignoreCase'] for x in witnesses if x['kind'] == 'case'),
            'native case policy disagrees with witnessed source filesystem')
    return {'format': 'purifier-git-path-policy-v1', **flags, 'witnesses': witnesses,
            'queries': policy_observations(source, env)}

def validate_path_policy(policy, git, manifest):
    require(isinstance(policy, dict) and set(policy) == {
        'format', 'ignoreCase', 'precomposeUnicode', 'witnesses', 'queries'}, 'invalid complete path policy')
    require(policy['format'] == 'purifier-git-path-policy-v1'
            and type(policy['ignoreCase']) is bool and type(policy['precomposeUnicode']) is bool,
            'invalid path-policy format/flags')
    witnesses = policy['witnesses']
    require(isinstance(witnesses, list) and len(witnesses) <= MAX_COUNT, 'invalid path-policy witness count')
    nodes = path_nodes(manifest)
    seen = set()
    covered = set()
    for witness in witnesses:
        require(isinstance(witness, dict) and set(witness) == {
            'directory', 'entry', 'alternate', 'kind', 'relation'}, 'invalid path-policy witness fields')
        directory, entry, alternate = (witness[k] for k in ['directory', 'entry', 'alternate'])
        require(directory == '.' or safe_path(directory), 'unsafe witness directory')
        directory.encode('utf-8')
        for name in [entry, alternate]:
            safe_path(name)
            name.encode('utf-8')
            require('/' not in name, 'witness needs a basename')
        require(entry != alternate and witness['kind'] in ('case', 'normalization')
                and witness['relation'] in ('alias', 'distinct'), 'invalid witness relation')
        require(alternate == case_alternate(entry) if witness['kind'] == 'case' else
                alternate in {unicodedata.normalize('NFC', entry), unicodedata.normalize('NFD', entry)} - {entry},
                'witness is not a finite case/normalization candidate')
        require(entry in nodes.get(directory, set()), 'witness entry absent from working source')
        key = (directory, entry, alternate, witness['kind'])
        require(key not in seen, 'duplicate path-policy witness')
        seen.add(key)
        if witness['kind'] == 'case':
            require((witness['relation'] == 'alias') == policy['ignoreCase'],
                    'case witness disagrees with captured policy')
            covered.add(directory)
    require(covered == set(nodes), 'missing required per-directory path-policy evidence')
    required_case = set()
    required_normalization = set()
    for directory, names in nodes.items():
        for entry in sorted(names):
            alternate = case_alternate(entry)
            if alternate is not None:
                required_case.add((directory, entry, alternate, 'case'))
                break
        for entry in names:
            if entry.isascii():
                continue
            for alternate in {unicodedata.normalize('NFC', entry), unicodedata.normalize('NFD', entry)} - {entry}:
                required_normalization.add((directory, entry, alternate, 'normalization'))
    require({key for key in seen if key[3] == 'case'} == required_case,
            'missing or unexpected deterministic case evidence')
    require({key for key in seen if key[3] == 'normalization'} == required_normalization,
            'missing or unexpected normalization evidence')
    queries = policy['queries']
    require(isinstance(queries, dict) and set(queries) == set(PATH_QUERIES), 'invalid fixed path-policy queries')
    for data in queries.values():
        require(isinstance(data, str) and len(data) <= 2 * MAX_OBJECT and len(data) % 2 == 0
                and re.fullmatch('[0-9a-f]*', data) is not None, 'invalid path-policy query bytes')
    expected = b''.join((x['mode'] + ' ' + x['oid'] + ' ' + str(x['stage']) + '\t' + x['path']).encode()
                        + b'\0' for x in git['index'])
    require(bytes.fromhex(queries['indexStageZ']) == expected, 'path-policy index query does not match typed index')

def copy_source_exact(source, destination, manifest):
    """Materialize working names exclusively, checking every directory prefix."""
    destination.mkdir()
    for name, row in sorted(manifest.items()):
        parts = safe_path(name).split('/')
        parent = destination
        for part in parts[:-1]:
            path = parent / part
            names = os.listdir(parent)
            if part not in names:
                require(not os.path.lexists(path), 'native working directory-prefix alias collision')
                path.mkdir()
                require(part in os.listdir(parent), 'native directory spelling changed')
            require(path.is_dir() and not path.is_symlink(), 'unsafe working directory prefix')
            parent = path
        target = parent / parts[-1]
        require(not os.path.lexists(target), 'native working pathname alias collision')
        original = beneath(source, name)
        if row['kind'] == 'symlink':
            require(original.is_symlink() and os.readlink(original) == row['target'], 'source link changed')
            target.symlink_to(row['target'])
        else:
            fd = os.open(original, os.O_RDONLY | os.O_NOFOLLOW)
            with os.fdopen(fd, 'rb') as stream:
                require(stat.S_ISREG(os.fstat(stream.fileno()).st_mode), 'non-file source payload')
                data = stream.read(MAX_OBJECT + 1)
            require(len(data) <= MAX_OBJECT and hashlib.sha256(data).hexdigest() == row['sha256'], 'source payload changed')
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o755 if row['executable'] else 0o644)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
        require(parts[-1] in os.listdir(parent), 'native working filename spelling changed')

def check_unicode_capability(destination, policy, env):
    # This is an owned destination probe, removed before query comparison.
    # Config-key acceptance is not evidence of native Unicode conversion.
    with tempfile.TemporaryDirectory(prefix='.purifier-path-policy-', dir=destination) as temporary:
        probe = Path(temporary)
        run(probe, ['init', '--quiet', '--template='], env)
        name = 'cafe\u0301.txt'
        (probe / name).write_bytes(b'probe\n')
        option = 'core.precomposeunicode=' + ('true' if policy['precomposeUnicode'] else 'false')
        run(probe, ['-c', option, 'add', '--', name], env)
        actual = run(probe, ['-c', option, 'ls-files', '-z'], env).stdout
        expected = ('caf\u00e9.txt\0' if policy['precomposeUnicode'] else name + '\0').encode()
        require(actual == expected, 'unsupported native Git Unicode conversion capability')

def check_path_policy(destination, policy, env):
    for witness in policy['witnesses']:
        require(native_relation(destination, witness['directory'], witness['entry'], witness['alternate'])
                == witness['relation'], 'unsupported destination path-policy witness')
    check_unicode_capability(destination, policy, env)

def capture(source, output, home):
    require(source.absolute() == source.resolve(), 'symlink source root/ancestor')
    require(output.absolute().parent == output.absolute().parent.resolve(), 'symlink output ancestor')
    require(not output.exists(), 'capture destination exists')
    output.mkdir(parents=True)
    env = controlled_env(home)
    before = facts(source, env)
    check_unicode_capability(output, before['git']['pathPolicy'], env)
    index_seal = hashlib.sha256((source / '.git/index').read_bytes()).hexdigest()
    data_root = output / 'objects'
    payloads = data_root / 'payloads'
    payloads.mkdir(parents=True)
    process = subprocess.Popen([GIT, '--no-replace-objects', 'cat-file', '--batch'], cwd=source, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    entries = {}
    todo = object_roots(before['git'])
    algorithm = before['git']['objectFormat']
    total = 0
    try:
        while todo:
            oid = min(todo)
            todo.remove(oid)
            if oid in entries:
                continue
            require(len(entries) < MAX_COUNT, 'object count limit exceeded')
            process.stdin.write((oid + '\n').encode())
            process.stdin.flush()
            header = process.stdout.readline().split()
            require(len(header) == 3 and header[0].decode() == oid, 'missing object; no lazy fetch allowed')
            kind, size = header[1].decode(), int(header[2])
            require(0 <= size <= MAX_OBJECT and total + size <= MAX_BYTES, 'object byte limit exceeded')
            data = process.stdout.read(size)
            require(len(data) == size and process.stdout.read(1) == b'\n', 'truncated object payload')
            require(object_oid(kind, data, algorithm) == oid, 'native object hash mismatch')
            edges = children(kind, data, algorithm)
            if kind == 'commit' and oid in before['git']['shallow']:
                edges = [e for e in edges if e[1] != 'commit']
            for child, expected in edges:
                if child in entries:
                    require(entries[child]['type'] == expected, 'object edge type mismatch')
                todo.add(child)
            (payloads / oid).write_bytes(data)
            entries[oid] = {'type': kind, 'size': size}
            total += size
        process.stdin.close()
        require(process.wait(timeout=30) == 0, 'native object reader failed')
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
    write_json(data_root / 'manifest.json', {'format': 'purifier-git-objects-v1', 'objectFormat': algorithm, 'objects': entries})
    dest = output / 'source'
    copy_source_exact(source, dest, before['source'])
    after = facts(source, env)
    require(before == after and hashlib.sha256((source / '.git/index').read_bytes()).hexdigest() == index_seal, 'native snapshot changed during capture')
    write_json(output / 'capture.json', {'format': 'purifier-source-capture-v2', **before})
    validated = validate(output)
    write_json(output / 'receipt.json', {'format': 'purifier-source-capture-receipt-v1', 'objectCount': len(entries), 'objectBytes': total, 'nativeIndexUnchanged': True, 'status': 'passed'})
    return validated

def validate(export):
    require(export.absolute() == export.resolve(), 'symlink export/ancestor')
    for name in ['capture.json', 'objects', 'objects/manifest.json', 'objects/payloads', 'source']:
        require(not (export / name).is_symlink(), 'symlink export metadata')
    capture = json.loads((export / 'capture.json').read_text())
    require(set(capture) == {'format', 'git', 'source'} and capture['format'] in (
        'purifier-source-capture-v1', 'purifier-source-capture-v2'), 'invalid source capture format')
    git = capture['git']
    policy = capture['format'] == 'purifier-source-capture-v2'
    require(set(git) == {'objectFormat', 'head', 'refs', 'shallow', 'objects', 'index', 'remotes'}
            | ({'pathPolicy'} if policy else set()), 'unexpected versioned Git state fields')
    require(git['objects'] == 'objects', 'invalid object export path')
    manifest = json.loads((export / 'objects/manifest.json').read_text())
    require(manifest['format'] == 'purifier-git-objects-v1' and manifest['objectFormat'] == git['objectFormat'], 'object manifest format mismatch')
    require(set(manifest) == {'format', 'objectFormat', 'objects'}, 'unexpected object manifest fields')
    entries = manifest['objects']
    require(all(set(x) == {'type', 'size'} and type(x['size']) is int and x['type'] in ('commit', 'tree', 'blob', 'tag') for x in entries.values()), 'invalid typed object record')
    require(len(entries) <= MAX_COUNT, 'object count limit exceeded')
    require(sum(x['size'] for x in entries.values()) <= MAX_BYTES, 'aggregate object limit exceeded')
    visited = set()
    todo = [(x, None) for x in object_roots(git)]
    while todo:
        oid, expected = todo.pop()
        require(oid_valid(oid, git['objectFormat']) and oid in entries, 'missing reachable object')
        item = entries[oid]
        require(expected is None or item['type'] == expected, 'reachable object type mismatch')
        if oid in visited:
            continue
        require(0 <= item['size'] <= MAX_OBJECT, 'object size limit exceeded')
        path = export / 'objects/payloads' / oid
        require(path.is_file() and not path.is_symlink(), 'missing/unsafe object payload')
        data = path.read_bytes()
        require(len(data) == item['size'] and object_oid(item['type'], data, git['objectFormat']) == oid, 'tampered object payload')
        edges = children(item['type'], data, git['objectFormat'])
        if item['type'] == 'commit' and oid in git['shallow']:
            edges = [e for e in edges if e[1] != 'commit']
        todo.extend(edges)
        visited.add(oid)
    require(visited == set(entries), 'unreachable objects in export')
    require(all(x in visited and entries[x]['type'] == 'commit' for x in git['shallow']), 'invalid shallow boundary object')
    require(entries[git['head']['oid']]['type'] == 'commit', 'HEAD is not a commit')
    seen_index = set()
    for entry in git['index']:
        require(set(entry) == {'path', 'mode', 'oid', 'stage', 'flags'} and set(entry['flags']) == {'assumeUnchanged', 'skipWorktree', 'intentToAdd'} and all(type(x) is bool for x in entry['flags'].values()), 'invalid canonical index fields')
        safe_path(entry['path'])
        key = entry['path'] if policy else entry['path'].casefold()
        require(key not in seen_index, 'index path collision')
        seen_index.add(key)
        require(entry['stage'] == 0 and entry['mode'] in ('100644', '100755', '120000') and not entry['flags']['intentToAdd'], 'unsupported index entry')
        require(entries[entry['oid']]['type'] == 'blob', 'index entry not a blob')
    actual_files = set()
    for directory, dirs, files in os.walk(export / 'source', followlinks=False):
        for name in list(dirs):
            path = Path(directory) / name
            safe_path(path.relative_to(export / 'source').as_posix())
            if path.is_symlink():
                actual_files.add(path.relative_to(export / 'source').as_posix())
                dirs.remove(name)
        for name in files:
            actual_files.add((Path(directory) / name).relative_to(export / 'source').as_posix())
    require(actual_files == set(capture['source']), 'extra or missing source file')
    with tempfile.TemporaryDirectory(prefix='git-source-validation-') as tmp:
        for name, oid in git['refs'].items():
            require(oid_valid(oid, git['objectFormat']) and re.fullmatch(r'refs/(heads|tags|remotes)/.+', name), 'invalid ref')
            run(export, ['check-ref-format', name], controlled_env(Path(tmp)))
    require(git['head']['ref'] is None or (git['head']['ref'].startswith('refs/heads/') and git['refs'].get(git['head']['ref']) == git['head']['oid']), 'invalid symbolic HEAD')
    for name, row in capture['source'].items():
        path = beneath(export / 'source', name)
        if row['kind'] == 'symlink':
            require(path.is_symlink() and os.readlink(path) == row['target'], 'source symlink mismatch')
            data = os.readlink(path).encode()
        else:
            require(row['kind'] == 'file' and path.is_file() and not path.is_symlink(), 'unsafe source file')
            data = path.read_bytes()
            require(bool(path.stat().st_mode & 0o111) == row['executable'], 'source mode mismatch')
        require(hashlib.sha256(data).hexdigest() == row['sha256'], 'source payload mismatch')
    if policy:
        validate_path_policy(git['pathPolicy'], git, capture['source'])
    return capture

def replay(export, destination, home):
    capture = validate(export)
    require(destination.absolute().parent == destination.absolute().parent.resolve(), 'symlink replay ancestor')
    require(not destination.exists(), 'replay destination exists')
    git = capture['git']
    policy = git.get('pathPolicy')
    if policy is None:
        shutil.copytree(export / 'source', destination, symlinks=True)
        make_writable(destination)
    else:
        copy_source_exact(export / 'source', destination, capture['source'])
    env = controlled_env(home)
    if policy is not None:
        check_path_policy(destination, policy, env)
    template = home / 'empty-template'
    template.mkdir(parents=True, exist_ok=True)
    run(destination, ['init', '--quiet', '--template=' + str(template), '--object-format=' + git['objectFormat']], env)
    if policy is None:
        for option in ['core.ignorecase', 'core.precomposeunicode']:
            value = run(destination, ['config', '--type=bool', '--get', option], env, ok=(0, 1))
            require(value.returncode == 1 or value.stdout == b'false\n', 'legacy Git input needs policy-aware recapture')
    else:
        for field, option in [('ignoreCase', 'core.ignorecase'), ('precomposeUnicode', 'core.precomposeunicode')]:
            run(destination, ['config', option, 'true' if policy[field] else 'false'], env)
    filemode = run(destination, ['config', '--type=bool', '--get', 'core.filemode'], env, ok=(0, 1))
    require(filemode.returncode == 1 or filemode.stdout == b'true\n', 'unsupported destination filemode policy')
    hooks = home / 'empty-hooks'
    hooks.mkdir(exist_ok=True)
    run(destination, ['config', 'core.hooksPath', str(hooks)], env)
    manifest = json.loads((export / 'objects/manifest.json').read_text())
    for oid, item in sorted(manifest['objects'].items()):
        data = (export / 'objects/payloads' / oid).read_bytes()
        actual = run(destination, ['hash-object', '-t', item['type'], '-w', '--stdin'], env, data).stdout.decode().strip()
        require(actual == oid, 'replay changed object identity')
    if git['shallow']:
        (destination / '.git/shallow').write_text('\n'.join(git['shallow']) + '\n')
    for name, oid in sorted(git['refs'].items()):
        run(destination, ['check-ref-format', name], env)
        run(destination, ['update-ref', name, oid], env)
    if git['head']['ref']:
        run(destination, ['symbolic-ref', 'HEAD', git['head']['ref']], env)
    else:
        run(destination, ['update-ref', '--no-deref', 'HEAD', git['head']['oid']], env)
    index_data = b''.join((x['mode'] + ' ' + x['oid'] + ' ' + str(x['stage']) + '\t' + x['path']).encode() + b'\0' for x in git['index'])
    run(destination, ['update-index', '-z', '--index-info'], env, index_data)
    for entry in git['index']:
        if entry['flags']['assumeUnchanged']:
            run(destination, ['update-index', '--assume-unchanged', '--', entry['path']], env)
        if entry['flags']['skipWorktree']:
            run(destination, ['update-index', '--skip-worktree', '--', entry['path']], env)
    for name, remote in git['remotes'].items():
        run(destination, ['config', 'remote.' + name + '.url', remote['url']], env)
        if remote['defaultRef']:
            target = 'refs/remotes/' + name + '/' + remote['defaultRef'][len('refs/heads/'):]
            require(target in git['refs'], 'remote default target absent')
            run(destination, ['symbolic-ref', 'refs/remotes/' + name + '/HEAD', target], env)
    run(destination, ['-c', 'pack.threads=2', '-c', 'pack.window=0', 'repack', '-a', '-d'], env)
    run(destination, ['fsck', '--full', '--strict', '--no-reflogs', '--no-dangling'], env)
    if policy is not None:
        require(policy_observations(destination, env) == policy['queries'], 'native path-policy query replay mismatch')
    return env


def source_files(root, path_policy=False):
    """Describe an explicitly prepared working tree without following links."""
    require(root.is_dir() and not root.is_symlink(), 'source input must be a directory')
    result = {}
    folded = set()
    total = 0
    for directory, dirs, files in os.walk(root, followlinks=False):
        names = list(files)
        for name in list(dirs):
            path = Path(directory) / name
            safe_path(path.relative_to(root).as_posix())
            if path.is_symlink():
                names.append(name)
                dirs.remove(name)
        for name in names:
            path = Path(directory) / name
            relative = safe_path(path.relative_to(root).as_posix())
            key = relative if path_policy else relative.casefold()
            require(key not in folded, 'source path collision')
            folded.add(key)
            if path.is_symlink():
                target = os.readlink(path)
                data = target.encode()
                result[relative] = {'kind': 'symlink', 'target': target, 'sha256': hashlib.sha256(data).hexdigest()}
            else:
                require(path.is_file() and path.stat().st_size <= MAX_OBJECT, 'unsupported source file or size')
                data = path.read_bytes()
                result[relative] = {'kind': 'file', 'executable': bool(path.stat().st_mode & 0o111), 'sha256': hashlib.sha256(data).hexdigest()}
            total += len(data)
            require(total <= MAX_BYTES and len(result) <= MAX_COUNT, 'source size/count limit exceeded')
    return result


def make_writable(root):
    for directory, dirs, files in os.walk(root, followlinks=False):
        Path(directory).chmod(0o755)
        for name in files:
            path = Path(directory) / name
            if not path.is_symlink():
                path.chmod(0o755 if path.stat().st_mode & 0o111 else 0o644)


def replay_state(state, destination, home):
    require(set(state) == {'format', 'source', 'git'} and state['format'] in (
        'purifier-source-input-v1', 'purifier-source-input-v2'), 'invalid sourceInput state')
    policy = state['format'] == 'purifier-source-input-v2'
    require((isinstance(state['git'], dict) and 'pathPolicy' in state['git']) if policy else
            state['git'] is None or (isinstance(state['git'], dict) and 'pathPolicy' not in state['git']),
            'sourceInput policy/version mismatch')
    require(isinstance(state['source'], str), 'invalid source reference')
    source = Path(state['source'])
    require(source.is_absolute() and source.is_relative_to('/nix/store') and source.resolve().is_relative_to('/nix/store'), 'source reference must be an immutable Nix input')
    manifest = source_files(source, path_policy=policy)
    require(not destination.exists() and destination.absolute().parent == destination.absolute().parent.resolve(), 'unsafe or existing replay destination')
    if state['git'] is None:
        shutil.copytree(source, destination, symlinks=True)
        make_writable(destination)
        require(source_files(destination) == manifest, 'source copy mismatch')
        return
    git = state['git']
    require(isinstance(git, dict) and isinstance(git.get('objects'), str), 'invalid Git input')
    objects = Path(git['objects'])
    require(objects.is_absolute() and objects.is_relative_to('/nix/store') and objects.resolve().is_relative_to('/nix/store'), 'objects must be an immutable Nix input')
    with tempfile.TemporaryDirectory(prefix='purifier-source-state-') as temporary:
        export = Path(temporary)
        if policy:
            copy_source_exact(source, export / 'source', manifest)
        else:
            shutil.copytree(source, export / 'source', symlinks=True)
        shutil.copytree(objects, export / 'objects', symlinks=True)
        write_json(export / 'capture.json', {
            'format': 'purifier-source-capture-v2' if policy else 'purifier-source-capture-v1',
            'source': manifest,
            'git': {**git, 'objects': 'objects'},
        })
        replay(export, destination, home)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture_parser = commands.add_parser('capture', help='capture a supported local Git working tree')
    capture_parser.add_argument('source', type=Path)
    capture_parser.add_argument('output', type=Path)
    validate_parser = commands.add_parser('validate', help='validate a captured source and object closure')
    validate_parser.add_argument('capture', type=Path)
    replay_parser = commands.add_parser('replay', help='replay a full core sourceInput.sourceState JSON file')
    replay_parser.add_argument('state', type=Path)
    replay_parser.add_argument('destination', type=Path)
    args = parser.parse_args()
    try:
        with tempfile.TemporaryDirectory(prefix='purifier-source-home-') as temporary:
            home = Path(temporary)
            if args.command == 'capture':
                capture(args.source.absolute(), args.output.absolute(), home)
            elif args.command == 'validate':
                validate(args.capture.absolute())
            else:
                replay_state(json.loads(args.state.read_text()), args.destination.absolute(), home)
    except (Invalid, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        parser.exit(1, 'purifier-source-input: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
