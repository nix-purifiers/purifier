# SPDX-License-Identifier: MIT
"""Project built asset directories and explicitly selected shared libraries."""
import json
from pathlib import Path, PurePosixPath
import re
import sys
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


def native(spec, destination):
    producer = Path(spec['producer'])
    libraries = {}
    for name, value in spec['libraries'].items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', name):
            raise ValueError('invalid native library name: ' + name)
        path = producer / relative(value)
        if not path.is_file():
            raise ValueError('native library does not exist: ' + str(path))
        libraries[name] = str(path)
    if not libraries or not spec['system']:
        raise ValueError('native projection needs libraries and a target system')
    destination.mkdir(parents=True)
    catalog = {'version': 1, 'system': spec['system'],
               'producer': spec['producerIdentity'], 'libraries': libraries}
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


if __name__ == '__main__':
    mode, spec_file, output = sys.argv[1:]
    {'webjar': webjar, 'native': native}[mode](json.loads(Path(spec_file).read_text()), Path(output))
