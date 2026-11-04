# SPDX-License-Identifier: MIT
"""Project built asset directories and explicitly selected shared libraries."""
import json
import hashlib
from pathlib import Path, PurePosixPath
import re
import sys
import struct
import xml.etree.ElementTree as ET
import zipfile


def relative(value):
    path = PurePosixPath(value)
    if not value or path.is_absolute() or '..' in path.parts or '\\' in value:
        raise ValueError('expected a relative producer path: ' + value)
    return path


def webjar(spec, destination):
    group, artifact, version = (spec[key] for key in ('groupId', 'artifactId', 'version'))
    for value in (group, artifact, version):
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*', value) or '..' in value:
            raise ValueError('invalid WebJar coordinate: ' + value)
    assets = Path(spec['assets']).resolve(strict=True)
    if not assets.is_dir():
        raise ValueError('WebJar assets must be a directory')
    root = destination / group / artifact / version
    (root / 'ivys').mkdir(parents=True)
    (root / 'jars').mkdir()
    ivy = ET.Element('ivy-module', version='2.0')
    ET.SubElement(ivy, 'info', organisation=group, module=artifact, revision=version)
    publications = ET.SubElement(ivy, 'publications')
    ET.SubElement(publications, 'artifact', name=artifact, type='jar', ext='jar')
    (root / 'ivys/ivy.xml').write_bytes(ET.tostring(ivy, encoding='utf-8', xml_declaration=True))
    pom = ET.Element('project', xmlns='http://maven.apache.org/POM/4.0.0')
    for key, value in [('modelVersion', '4.0.0'), ('groupId', group),
                       ('artifactId', artifact), ('version', version), ('packaging', 'jar')]:
        ET.SubElement(pom, key).text = value
    pom_bytes = ET.tostring(pom, encoding='utf-8', xml_declaration=True)
    entries = {
        'META-INF/MANIFEST.MF': b'Manifest-Version: 1.0\r\n\r\n',
        f'META-INF/maven/{group}/{artifact}/pom.xml': pom_bytes,
        f'META-INF/maven/{group}/{artifact}/pom.properties':
            f'groupId={group}\nartifactId={artifact}\nversion={version}\n'.encode(),
    }
    count = 0
    for path in sorted(assets.rglob('*')):
        if not path.resolve(strict=True).is_relative_to(assets):
            raise ValueError('WebJar asset symlink escapes asset directory: ' + str(path))
        if path.is_file():
            name = path.relative_to(assets).as_posix()
            relative(name)
            entries[f'META-INF/resources/webjars/{artifact}/{version}/{name}'] = path.read_bytes()
            count += 1
        elif not path.is_dir():
            raise ValueError('unsupported WebJar asset: ' + str(path))
    if not count:
        raise ValueError('WebJar assets directory is empty')
    # ClassLoader.getResources on a directory (used by WebJar locators)
    # requires directory entries, even though reading a single asset does not.
    for name in list(entries):
        for parent in PurePosixPath(name).parents:
            if parent != PurePosixPath('.'):
                entries.setdefault(parent.as_posix() + '/', b'')
    with zipfile.ZipFile(root / 'jars' / f'{artifact}.jar', 'w') as archive:
        for name, contents in sorted(entries.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (0o40755 if name.endswith('/') else 0o100644) << 16
            archive.writestr(info, contents)


def validate_library(path, system):
    with path.open('rb') as stream:
        header = stream.read(64)
    if system in ('x86_64-linux', 'aarch64-linux'):
        machine = {'x86_64-linux': 62, 'aarch64-linux': 183}[system]
        valid = (len(header) >= 20 and header[:6] == b'\x7fELF\x02\x01'
                 and struct.unpack_from('<HH', header, 16) == (3, machine))
    elif system in ('x86_64-darwin', 'aarch64-darwin'):
        cpu = {'x86_64-darwin': 0x1000007, 'aarch64-darwin': 0x100000c}[system]
        valid = (len(header) >= 16 and header[:4] == b'\xcf\xfa\xed\xfe'
                 and struct.unpack_from('<I', header, 4)[0] == cpu
                 and struct.unpack_from('<I', header, 12)[0] == 6)
    else:
        raise ValueError('unsupported native projection target system: ' + system)
    if not valid:
        raise ValueError('native library binary ABI does not match ' + system + ': ' + str(path))


def native(spec, destination):
    producer = Path(spec['producer'])
    libraries = {}
    for name, value in spec['libraries'].items():
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:+-]*', name):
            raise ValueError('invalid native library name: ' + name)
        path = producer / relative(value)
        if not path.is_file():
            raise ValueError('native library does not exist: ' + str(path))
        validate_library(path, spec['system'])
        libraries[name] = str(path)
    if not libraries or not spec['system']:
        raise ValueError('native projection needs libraries and a target system')
    destination.mkdir(parents=True)
    catalog = {'version': 1, 'system': spec['system'],
               'producer': spec['producerIdentity'], 'libraries': libraries}
    catalog['prefix'] = str(producer)
    catalog['targets'] = spec.get('targetMetadata', {})
    for key in ('includeDirectories', 'pkgConfigDirectories'):
        directories = [producer / relative(value) for value in spec.get(key, [])]
        if any(not directory.is_dir() for directory in directories):
            raise ValueError('native metadata directory does not exist: ' + key)
        catalog[key] = [str(directory) for directory in directories]
    (destination / 'catalog.json').write_text(json.dumps(catalog, sort_keys=True) + '\n')
    # Embed paths, not build-time Python or ctypes objects. Import remains lazy
    # so a consumer can set signatures and choose the loading mode itself.
    (destination / 'purifier_native.py').write_text(
        'import ctypes\nLIBRARIES = ' + repr(libraries) + '\n'
        'def load(name, **kwargs):\n    return ctypes.CDLL(LIBRARIES[name], **kwargs)\n')
    directories = sorted({str(Path(path).parent) for path in libraries.values()})
    value = '-Djava.library.path=' + ':'.join(directories)
    (destination / 'java.args').write_text('"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"\n')
    support = destination / 'nix-support'
    support.mkdir()
    (support / 'inputs').write_text(str(producer) + '\n')


def data(spec, destination, metadata):
    destination.mkdir(parents=True)
    records = {}
    for name, value in spec['files'].items():
        path = relative(value)
        if path.parts[0] == 'nix-support':
            raise ValueError('JSON document uses reserved nix-support path')
        contents = (Path(spec['producer']) / path).read_bytes()
        # Reject non-JSON NaN/Infinity too: many native JSON consumers reject
        # the permissive extensions in Python's decoder.
        def invalid(value):
            raise ValueError('invalid JSON constant: ' + value)
        json.loads(contents, parse_constant=invalid)
        output = destination / path
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(contents)
        records[name] = {'file': value, 'sha256': hashlib.sha256(contents).hexdigest()}
    metadata.mkdir(parents=True)
    (metadata / 'catalog.json').write_text(json.dumps({
        'version': 1, 'format': 'json', 'producer': spec['producerIdentity'], 'files': records,
    }, sort_keys=True) + '\n')
    (destination / 'nix-support').mkdir(exist_ok=True)
    (destination / 'nix-support/inputs').write_text(spec['producer'] + '\n')


if __name__ == '__main__':
    mode, spec_file, output, *extra = sys.argv[1:]
    {'webjar': webjar, 'native': native, 'json': data}[mode](
        json.loads(Path(spec_file).read_text()), Path(output), *(Path(path) for path in extra))
