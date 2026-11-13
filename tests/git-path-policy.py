# SPDX-License-Identifier: MIT
"""Native filename-policy capture, reconstruction, and rejection controls."""
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile

spec = importlib.util.spec_from_file_location('git_source', Path(__file__).parents[1] / 'tools/git_source.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def rejected(action, needle):
    try:
        action()
    except g.Invalid as error:
        assert needle in str(error), (needle, str(error))
    else:
        raise AssertionError('expected rejection: ' + needle)

with tempfile.TemporaryDirectory(prefix='native-path-policy-') as temporary:
    root = Path(temporary)
    source = root / 'source'
    source.mkdir()
    home = root / 'home'
    home.mkdir()
    env = g.controlled_env(home)
    def git(*args):
        return g.run(source, list(args), env).stdout
    git('init', '--quiet', '--template=')
    (source / 'Folder').mkdir()
    (source / 'Folder/nested.txt').write_text('nested\n')
    (source / 'Tracked').write_text('committed\n')
    (source / 'Case.txt').write_text('case spelling\n')
    (source / 'caf\u00e9.txt').write_text('unicode\n')
    (source / '.gitignore').write_text('ignored\n')
    git('add', '.')
    git('-c', 'user.name=Policy', '-c', 'user.email=policy@example.invalid', 'commit', '-qm', 'native defaults')
    (source / 'Tracked').write_text('indexed\n')
    git('add', 'Tracked')
    (source / 'Tracked').write_text('working\n')
    (source / 'Case.txt').rename(source / 'case.txt')
    (source / 'untracked').write_text('untracked\n')
    (source / 'ignored').write_text('ignored input stays in caller source\n')
    index = digest(source / '.git/index')
    before = g.facts(source, env)
    export = root / 'captured'
    captured = g.capture(source, export, home)
    assert captured['format'] == 'purifier-source-capture-v2'
    policy = captured['git']['pathPolicy']
    assert policy['format'] == 'purifier-git-path-policy-v1'
    assert 'case.txt' in captured['source']
    assert 'Case.txt' in {item['path'] for item in captured['git']['index']}
    assert 'ignored' not in captured['source']
    assert {w['directory'] for w in policy['witnesses'] if w['kind'] == 'case'} == {'.', 'Folder'}
    destination = root / 'replayed'
    g.replay(export, destination, home)
    for name, row in captured['source'].items():
        path = destination / name
        if row['kind'] == 'symlink':
            assert path.is_symlink() and os.readlink(path) == row['target']
        else:
            assert digest(path) == row['sha256']
            assert bool(path.stat().st_mode & 0o111) == row['executable']
    assert not (destination / 'ignored').exists()
    assert (destination / 'Tracked').read_text() == 'working\n'
    assert (destination / 'case.txt').read_text() == 'case spelling\n'
    assert g.policy_observations(destination, env) == policy['queries']
    for field, key in [('ignoreCase', 'core.ignorecase'), ('precomposeUnicode', 'core.precomposeunicode')]:
        assert g.run(destination, ['config', '--type=bool', '--get', key], env).stdout == (
            b'true\n' if policy[field] else b'false\n')
    assert digest(source / '.git/index') == index
    assert g.facts(source, env) == before

    def changed(name, mutation):
        target = root / name
        shutil.copytree(export, target, symlinks=True)
        value = json.loads((target / 'capture.json').read_text())
        mutation(value)
        g.write_json(target / 'capture.json', value)
        return target

    bad = changed('missing-policy', lambda x: x['git'].pop('pathPolicy'))
    rejected(lambda: g.validate(bad), 'versioned Git state fields')
    bad = changed('missing-witness', lambda x: x['git']['pathPolicy'].__setitem__('witnesses', []))
    rejected(lambda: g.validate(bad), 'missing required per-directory')
    assert any(w['kind'] == 'normalization' for w in policy['witnesses'])
    bad = changed('missing-normalization', lambda x: x['git']['pathPolicy'].__setitem__(
        'witnesses', [w for w in x['git']['pathPolicy']['witnesses'] if w['kind'] != 'normalization']))
    rejected(lambda: g.validate(bad), 'missing or unexpected normalization evidence')
    bad = changed('unknown-host-field', lambda x: x['git']['pathPolicy'].__setitem__('hostInode', 1))
    rejected(lambda: g.validate(bad), 'complete path policy')
    bad = changed('wrong-index-query', lambda x: x['git']['pathPolicy']['queries'].__setitem__('indexStageZ', '00'))
    rejected(lambda: g.validate(bad), 'does not match typed index')
    bad = changed('arbitrary-witness', lambda x: x['git']['pathPolicy']['witnesses'][0].__setitem__('alternate', 'unrelated'))
    rejected(lambda: g.validate(bad), 'finite case/normalization candidate')
    bad = changed('duplicate-witness', lambda x: x['git']['pathPolicy']['witnesses'].append(copy.deepcopy(x['git']['pathPolicy']['witnesses'][0])))
    rejected(lambda: g.validate(bad), 'duplicate path-policy witness')
    bad = changed('wrong-native-query', lambda x: x['git']['pathPolicy']['queries'].__setitem__('statusPorcelainV1Z', '00'))
    rejected(lambda: g.replay(bad, root / 'wrong-query-output', home), 'native path-policy query replay mismatch')
    def invert_case(value):
        value['git']['pathPolicy']['ignoreCase'] = not policy['ignoreCase']
        for witness in value['git']['pathPolicy']['witnesses']:
            if witness['kind'] == 'case':
                witness['relation'] = 'distinct' if witness['relation'] == 'alias' else 'alias'
    bad = changed('wrong-filesystem', invert_case)
    rejected(lambda: g.replay(bad, root / 'wrong-fs-output', home), 'unsupported destination path-policy witness')
    def legacy(value):
        value['format'] = 'purifier-source-capture-v1'
        value['git'].pop('pathPolicy')
    old = changed('legacy', legacy)
    seal = digest(old / 'capture.json')
    if policy['ignoreCase'] or policy['precomposeUnicode']:
        rejected(lambda: g.replay(old, root / 'legacy-output', home), 'policy-aware recapture')
    else:
        g.replay(old, root / 'legacy-output', home)
    assert digest(old / 'capture.json') == seal
    prefix_results = {}
    for kind, first, second in [('case', 'CaseDir', 'caseDir'),
                                ('normalization', 'caf\u00e9', 'cafe\u0301')]:
        original = root / ('prefix-source-' + kind)
        original.mkdir()
        (original / first).mkdir()
        relation = g.native_relation(original, '.', first, second)
        if relation == 'distinct':
            (original / second).mkdir()
        (original / first / 'a').write_bytes(b'a\n')
        (original / second / 'b').write_bytes(b'b\n')
        # Feed two requested spellings to the materializer. An immutable
        # source may support both even when its destination does not.
        payload = {first + '/a': {'kind': 'file', 'executable': False,
                                  'sha256': digest(original / first / 'a')},
                   second + '/b': {'kind': 'file', 'executable': False,
                                   'sha256': digest(original / second / 'b')}}
        target = root / ('prefix-destination-' + kind)
        if relation == 'alias':
            rejected(lambda: g.copy_source_exact(original, target, payload),
                     'native working directory-prefix alias collision')
        else:
            g.copy_source_exact(original, target, payload)
            assert {first, second} == set(os.listdir(target))
            assert (target / first / 'a').read_bytes() == b'a\n'
            assert (target / second / 'b').read_bytes() == b'b\n'
        prefix_results[kind] = {'nativeRelation': relation,
                                'result': 'alias rejected' if relation == 'alias' else 'distinct names preserved'}
    assert digest(source / '.git/index') == index
    assert g.facts(source, env) == before
    print(json.dumps({'status': 'passed', 'nativeDefaultPolicy': {
        'ignoreCase': policy['ignoreCase'], 'precomposeUnicode': policy['precomposeUnicode']},
        'witnesses': len(policy['witnesses']), 'caseOnlyIndexWorkingSpellingsPreserved': True,
        'nativeQueriesMatch': True, 'sourceIndexUnchanged': True, 'negativeControls': 9,
        'prefixMaterialization': prefix_results, 'legacyUnrewritten': True}))
