# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  producer = pkgs.runCommand "core-wasm-fixture" { nativeBuildInputs = [ pkgs.wabt ]; } ''
    mkdir -p "$out/lib"
    cat > proof.wat <<'WAT'
    (module
      (import "provider" "base" (func $base (result i32)))
      (func (export "answer") (result i32) call $base i32.const 1 i32.add))
    WAT
    wat2wasm proof.wat -o "$out/lib/proof.wasm"
  '';
  projected = purifier.wasmProjections {
    inherit producer;
    modules.proof = {
      path = "lib/proof.wasm";
      imports = [
        {
          module = "provider";
          name = "base";
          kind = "function";
        }
      ];
    };
    inherit (pkgs) runCommand python3 nodejs;
  };
in
{
  wasm-resources = import ./resource-consumer.nix {
    inherit pkgs;
    projection = projected.resources;
  };
  wasm-consumers =
    pkgs.runCommand "core-wasm-ordinary-consumer"
      {
        nativeBuildInputs = [ pkgs.nodejs ];
      }
      ''
        node - ${../tools/wasm_projection.cjs} <<'JS'
        const fs = require('node:fs');
        const assert = require('node:assert/strict');
        const { validate } = require(process.argv[2]);
        const module = new WebAssembly.Module(fs.readFileSync('${projected.wasm.modules.proof}'));
        const instance = new WebAssembly.Instance(module, { provider: { base: () => 41 } });
        assert.equal(instance.exports.answer(), 42);
        assert.throws(() => new WebAssembly.Instance(module, {}));
        assert.throws(() => new WebAssembly.Instance(module, { provider: { base: 41 } }));
        const catalog = JSON.parse(fs.readFileSync('${projected.wasm.catalog}'));
        assert.equal(catalog.format, 'purifier-core-wasm-v1');
        assert.deepEqual(catalog.modules.proof.imports, [{ module: 'provider', name: 'base', kind: 'function' }]);
        assert.deepEqual(catalog.modules.proof.exports, [{ name: 'answer', kind: 'function' }]);
        assert.throws(() => validate({proof: {path: 'lib/proof.wasm', imports: []}}, '${projected.resources}'), /contract mismatch/);
        assert.throws(() => validate({proof: {path: 'lib/proof.wasm'}}, '${projected.resources}'), /explicit imports/);
        const { Module } = WebAssembly;
        assert.throws(() => new Module(Buffer.from('not a Wasm module')));
        JS
        touch $out
      '';
}
