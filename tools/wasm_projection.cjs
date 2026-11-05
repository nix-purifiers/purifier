// SPDX-License-Identifier: MIT
// Core module validation and explicit import contract; no WASI/component adapter.
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');

function imports(records) {
  if (!Array.isArray(records)) throw new Error('imports must be explicitly listed');
  return records.map(record => {
    if (record === null || typeof record !== 'object' ||
        Object.keys(record).sort().join(',') !== 'kind,module,name' ||
        !['function', 'global', 'memory', 'table', 'tag'].includes(record.kind) ||
        typeof record.module !== 'string' || typeof record.name !== 'string') {
      throw new Error('invalid WebAssembly import record');
    }
    return JSON.stringify([record.module, record.name, record.kind]);
  }).sort();
}

function validate(spec, root) {
  const resources = JSON.parse(fs.readFileSync(path.join(root, 'catalog.json')));
  const catalog = {
    format: 'purifier-core-wasm-v1', producerIdentity: resources.producerIdentity,
    validator: process.version, modules: Object.create(null),
  };
  for (const [logical, selected] of Object.entries(spec).sort()) {
    if (!/^[A-Za-z0-9_][A-Za-z0-9_.-]*$/.test(logical) || logical.includes('..')) {
      throw new Error('invalid logical WebAssembly module name');
    }
    if (!selected || Object.keys(selected).sort().join(',') !== 'imports,path') {
      throw new Error('a core module needs path and explicit imports');
    }
    const file = logical + '.wasm';
    const bytes = fs.readFileSync(path.join(root, 'files', file));
    const module = new WebAssembly.Module(bytes);
    const actual = WebAssembly.Module.imports(module);
    if (JSON.stringify(imports(actual)) !== JSON.stringify(imports(selected.imports))) {
      throw new Error('WebAssembly import contract mismatch: ' + logical);
    }
    catalog.modules[logical] = {
      file, sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
      imports: actual, exports: WebAssembly.Module.exports(module),
    };
  }
  fs.writeFileSync(path.join(root, 'wasm.json'), JSON.stringify(catalog, null, 2) + '\n');
}

if (require.main === module) {
  validate(JSON.parse(fs.readFileSync(process.argv[2])), process.argv[3]);
}
module.exports = { validate };
