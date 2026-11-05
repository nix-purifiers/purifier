# SPDX-License-Identifier: MIT
"""Copy selected built resources with stable paths for HTTP, JVM and IDL tools."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys
import zipfile


def relative(value, root=False):
    if not isinstance(value, str):
        raise ValueError('resource path must be a string')
    path = PurePosixPath(value)
    if (not value or path.is_absolute()
            or '..' in path.parts or '\\' in value
            or (path == PurePosixPath('.') and not root)
            or str(path) != value):
        raise ValueError('expected a canonical relative resource path: ' + str(value))
    return path


def project(spec, output):
    producer = Path(spec['producer']).resolve(strict=True)
    entries = {}

    def add(name, source):
        relative(name)
        if name in entries:
            raise ValueError('resource collision: ' + name)
        entries[name] = source.read_bytes()

    def collect(source, boundary, prefix):
        if not source.resolve(strict=True).is_relative_to(boundary):
            raise ValueError('resource symlink escapes selected root: ' + str(source))
        if source.is_file():
            add(prefix, source)
        elif source.is_dir():
            for child in sorted(source.iterdir()):
                if child.is_symlink() and child.resolve(strict=True).is_dir():
                    raise ValueError('directory symlinks are unsupported: ' + str(child))
                target = child.name if prefix == '.' else prefix + '/' + child.name
                collect(child, boundary, target)
        else:
            raise ValueError('unsupported resource: ' + str(source))

    for prefix, selected in sorted(spec['roots'].items()):
        relative(prefix, root=True)
        relative(selected, root=True)
        source = producer / selected
        resolved = source.resolve(strict=True)
        if not resolved.is_relative_to(producer):
            raise ValueError('selected resource escapes producer: ' + selected)
        collect(source, resolved if source.is_dir() else producer, prefix)
    for dependency in spec.get('dependencies', []):
        bundle = Path(dependency['path'])
        # A catalog is required: a random directory is not a resource dependency.
        catalog = json.loads((bundle / 'catalog.json').read_text())
        if catalog.get('format') != 'purifier-resources-v1':
            raise ValueError('unsupported resource dependency catalog')
        for name, record in sorted(catalog['files'].items()):
            relative(name)
            source = bundle / 'files' / name
            if not source.resolve(strict=True).is_relative_to((bundle / 'files').resolve(strict=True)):
                raise ValueError('dependency resource escapes bundle: ' + name)
            if hashlib.sha256(source.read_bytes()).hexdigest() != record['sha256']:
                raise ValueError('resource dependency digest mismatch: ' + name)
            add(name, source)
    if not entries:
        raise ValueError('resource selection is empty')
    schema = spec.get('schema')
    if schema is not None:
        if (set(schema) != {'format', 'entrypoints'} or not isinstance(schema['format'], str)
                or not schema['format'] or not isinstance(schema['entrypoints'], list)
                or not schema['entrypoints']):
            raise ValueError('schema needs a format and explicit entrypoints')
        for entry in schema['entrypoints']:
            relative(entry)
            if entry not in entries:
                raise ValueError('schema entrypoint is absent: ' + entry)
    output.mkdir(parents=True)
    catalog = {'format': 'purifier-resources-v1', 'producerIdentity': spec['producerIdentity'],
               'dependencies': spec.get('dependencies', []), 'schema': schema, 'files': {}}
    with zipfile.ZipFile(output / 'resources.jar', 'w') as archive:
        for name, contents in sorted(entries.items()):
            target = output / 'files' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(contents)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = 0o100644 << 16
            archive.writestr(info, contents)
            catalog['files'][name] = {'sha256': hashlib.sha256(contents).hexdigest(), 'size': len(contents)}
    (output / 'catalog.json').write_text(json.dumps(catalog, sort_keys=True, indent=2) + '\n')
    (output / 'nix-support').mkdir()
    inputs = [spec['producer']] + [item['path'] for item in spec.get('dependencies', [])]
    (output / 'nix-support/inputs').write_text('\n'.join(inputs) + '\n')


if __name__ == '__main__':
    project(json.loads(Path(sys.argv[1]).read_text()), Path(sys.argv[2]))
