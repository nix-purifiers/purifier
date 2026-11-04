# SPDX-License-Identifier: MIT
"""Generate wheel tags on the helper from facts collected on the target.

This worker runs in a separate helper process: adapting packaging's process
introspection cannot affect other users of packaging in the caller. The target
probe uses only its own standard library and imports no helper packages.
"""
import json
import sys
from types import SimpleNamespace


# Keep this script compatible with historical target interpreters. In particular
# it must not import packaging, typing, tomllib or helper Python modules.
PROBE = r'''
import json, os, platform, struct, sys, sysconfig
try:
    from importlib.machinery import EXTENSION_SUFFIXES
except ImportError:
    import imp
    EXTENSION_SUFFIXES = [entry[0] for entry in imp.get_suffixes() if entry[2] == imp.C_EXTENSION]
glibc = [-1, -1]
try:
    glibc = [int(item) for item in os.confstr("CS_GNU_LIBC_VERSION").split()[1].split(".")[:2]]
except (AttributeError, KeyError, ValueError, OSError):
    try:
        import ctypes
        function = ctypes.CDLL(None).gnu_get_libc_version
        function.restype = ctypes.c_char_p
        glibc = [int(item) for item in function().decode("ascii").split(".")[:2]]
    except (AttributeError, ValueError, OSError):
        pass
plat = sysconfig.get_platform().replace("-", "_").replace(".", "_")
if struct.calcsize("P") == 4:
    plat = {"linux_x86_64": "linux_i686", "linux_aarch64": "linux_armv8l"}.get(plat, plat)
arch = plat[len("linux_"):] if plat.startswith("linux_") else plat
archs = ["armv8l", "armv7l"] if arch == "armv8l" else [arch]
policy = None
try:
    import _manylinux
    policy = {"flags": {}, "versions": {}}
    for name in ("manylinux1_compatible", "manylinux2010_compatible", "manylinux2014_compatible"):
        if hasattr(_manylinux, name):
            policy["flags"][name] = bool(getattr(_manylinux, name))
    if hasattr(_manylinux, "manylinux_compatible"):
        policy["callback"] = True
        if glibc[0] != 2:
            raise RuntimeError("target manylinux policy requires a reviewed glibc major version")
        for arch in archs:
            for minor in range(glibc[1] + 1):
                value = _manylinux.manylinux_compatible(2, minor, arch)
                policy["versions"]["2.%d.%s" % (minor, arch)] = None if value is None else bool(value)
except ImportError:
    pass
implementation = getattr(sys, "implementation", None)
facts = {
    "version": list(sys.version_info), "executable": sys.executable,
    "maxunicode": sys.maxunicode, "refcount": hasattr(sys, "gettotalrefcount"),
    "implementation": getattr(implementation, "name", platform.python_implementation().lower()),
    "multiarch": getattr(implementation, "_multiarch", None),
    "platform": sysconfig.get_platform(), "config": sysconfig.get_config_vars(),
    "system": platform.system(), "mac": platform.mac_ver(),
    "pythonImplementation": platform.python_implementation(),
    "extensionSuffixes": EXTENSION_SUFFIXES, "pointerBytes": struct.calcsize("P"),
    "glibc": glibc, "manylinux": policy,
}
print(json.dumps(facts))
'''


def generate(facts):
    from packaging import tags, _manylinux, _musllinux

    # Only packaging's introspection references change, in this worker process.
    # Its algorithms and ordering remain those of the selected helper package.
    target_sys = SimpleNamespace(version_info=tuple(facts['version']),
        executable=facts['executable'], maxunicode=facts['maxunicode'],
        implementation=SimpleNamespace(name=facts['implementation'], _multiarch=facts['multiarch']))
    if facts['refcount']:
        target_sys.gettotalrefcount = lambda: 0
    tags.sys = target_sys
    tags.sysconfig = SimpleNamespace(get_platform=lambda: facts['platform'],
                                    get_config_var=lambda key: facts['config'][key])
    tags.platform = SimpleNamespace(system=lambda: facts['system'],
                                    mac_ver=lambda: tuple(facts['mac']),
                                    python_implementation=lambda: facts['pythonImplementation'])
    tags.EXTENSION_SUFFIXES = facts['extensionSuffixes']
    tags._32_BIT_INTERPRETER = facts['pointerBytes'] == 4
    # These functions bind pointer width in default arguments at module import;
    # replacing the module constant alone would retain the helper's width.
    linux_platforms = tags._linux_platforms
    tags._linux_platforms = lambda: linux_platforms(is_32bit=facts['pointerBytes'] == 4)
    mac_arch = tags._mac_arch
    tags._mac_arch = lambda arch: mac_arch(arch, is_32bit=facts['pointerBytes'] == 4)
    _manylinux.sys = target_sys
    _manylinux._get_glibc_version = lambda: tuple(facts['glibc'])
    policy = facts['manylinux']
    target_policy = None
    if policy is not None:
        target_policy = SimpleNamespace(**policy['flags'])
        if policy.get('callback'):
            target_policy.manylinux_compatible = lambda major, minor, arch: policy['versions'][f'{major}.{minor}.{arch}']
    sys.modules['_manylinux'] = target_policy
    if hasattr(_manylinux, '_get_manylinux_module'):
        _manylinux._get_manylinux_module = lambda: target_policy
    # The helper inspects the target ELF executable and its musl loader; it must
    # not inspect the helper interpreter's executable or libc.
    _musllinux.sys = target_sys
    return [str(tag) for tag in tags.sys_tags()]


if __name__ == '__main__':
    print(json.dumps(generate(json.load(sys.stdin))))
