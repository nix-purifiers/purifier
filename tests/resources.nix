# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  inherit (pkgs) runCommand python3;
  source = runCommand "schema-resource-fixture" { } ''
    mkdir -p $out/protobuf/common $out/thrift/common
    cat > $out/protobuf/common/value.proto <<'PROTO'
    syntax = "proto3";
    package proof;
    message Value { int32 answer = 1; }
    PROTO
    cat > $out/protobuf/main.proto <<'PROTO'
    syntax = "proto3";
    package proof;
    import "common/value.proto";
    message Envelope { Value value = 1; }
    PROTO
    cat > $out/thrift/common/value.thrift <<'THRIFT'
    namespace py common_value
    struct Value { 1: i32 answer }
    THRIFT
    cat > $out/thrift/main.thrift <<'THRIFT'
    include "common/value.thrift"
    namespace py main_value
    struct Envelope { 1: value.Value value }
    THRIFT
    echo private > $out/private.txt
  '';
  make =
    format:
    let
      dependency = purifier.resourceProjections {
        producer = source;
        roots.common = "${format}/common";
        inherit runCommand python3;
      };
    in
    purifier.resourceProjections {
      producer = source;
      roots."main.${if format == "protobuf" then "proto" else "thrift"}" = "${format}/main.${
        if format == "protobuf" then "proto" else "thrift"
      }";
      dependencies = [ dependency.resources ];
      schema = {
        inherit format;
        entrypoints = [ "main.${if format == "protobuf" then "proto" else "thrift"}" ];
      };
      inherit runCommand python3;
    };
  proto = make "protobuf";
  thrift = make "thrift";
  python = pkgs.python3.withPackages (p: [
    p.protobuf
    p.thrift
  ]);
in
{
  resource-unit = runCommand "resource-unit" { nativeBuildInputs = [ python3 ]; } ''
    python ${../.}/tests/test_resources.py
    touch $out
  '';
  resource-schema-consumers =
    runCommand "resource-schema-consumers"
      {
        nativeBuildInputs = [
          python
          pkgs.protobuf
          pkgs.thrift
          pkgs.jdk
        ];
      }
      ''
        mkdir proto-generated thrift-generated
        protoc -I ${proto.resources.directory} --python_out=proto-generated main.proto common/value.proto
        thrift -r --gen py -I ${thrift.resources.directory} -out thrift-generated ${thrift.resources.directory}/main.thrift
        PYTHONPATH=proto-generated:thrift-generated python - <<'PY'
        from main_pb2 import Envelope
        message = Envelope()
        message.value.answer = 42
        assert Envelope.FromString(message.SerializeToString()).value.answer == 42
        from main_value.ttypes import Envelope as ThriftEnvelope
        from common_value.ttypes import Value
        from thrift.transport.TTransport import TMemoryBuffer
        from thrift.protocol.TBinaryProtocol import TBinaryProtocol
        message = ThriftEnvelope(value=Value(answer=42))
        buffer = TMemoryBuffer()
        message.write(TBinaryProtocol(buffer))
        restored = ThriftEnvelope()
        restored.read(TBinaryProtocol(TMemoryBuffer(buffer.getvalue())))
        assert restored.value.answer == 42
        import json, pathlib, zipfile
        for bundle in ('${proto.resources}', '${thrift.resources}'):
            root = pathlib.Path(bundle)
            catalog = json.loads((root / 'catalog.json').read_text())
            with zipfile.ZipFile(root / 'resources.jar') as jar:
                assert set(jar.namelist()) == set(catalog['files'])
                assert 'private.txt' not in jar.namelist()
                for name in jar.namelist():
                    assert jar.read(name) == (root / 'files' / name).read_bytes()
        import functools, http.server, threading, urllib.request
        handler = functools.partial(http.server.SimpleHTTPRequestHandler,
                                    directory='${proto.web.documentRoot}')
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            try:
                assert urllib.request.urlopen(base + '/common/value.proto').read() == pathlib.Path(
                    '${proto.resources.directory}/common/value.proto').read_bytes()
                for hidden in ('private.txt', 'catalog.json', 'nix-support/inputs'):
                    try:
                        urllib.request.urlopen(base + '/' + hidden)
                        raise AssertionError('served private metadata: ' + hidden)
                    except urllib.error.HTTPError as error:
                        assert error.code == 404
            finally:
                server.shutdown()
                thread.join()
        PY
        mkdir incomplete failed-generated
        cp ${proto.resources.directory}/main.proto incomplete/
        if protoc -I incomplete --python_out=failed-generated main.proto; then
          echo "unexpectedly compiled protobuf without its schema dependency" >&2
          exit 1
        fi
        cp ${thrift.resources.directory}/main.thrift incomplete/
        if thrift -r --gen py -I incomplete -out failed-generated incomplete/main.thrift; then
          echo "unexpectedly compiled Thrift without its included schema" >&2
          exit 1
        fi
        cat > Resources.java <<'JAVA'
        public class Resources {
          public static void main(String[] args) throws Exception {
            for (String name : args) {
              try (var stream = Resources.class.getResourceAsStream("/" + name)) {
                if (stream == null || stream.readAllBytes().length == 0) throw new AssertionError(name);
              }
            }
          }
        }
        JAVA
        javac Resources.java
        java -cp .:${proto.java-resources.classPath} Resources main.proto common/value.proto
        java -cp .:${thrift.java-resources.classPath} Resources main.thrift common/value.thrift
        touch $out
      '';
}
