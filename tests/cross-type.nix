# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  inherit (pkgs) runCommand python3;
  native = pkgs.stdenv.mkDerivation {
    name = "cross-type-native-fixture";
    dontUnpack = true;
    buildPhase = ''
      cat > proof.c <<'C'
      #include <jni.h>
      int answer(void) { return 42; }
      JNIEXPORT jint JNICALL Java_Proof_answer(JNIEnv *env, jclass cls) { return answer(); }
      C
      $CC -shared -fPIC -I${pkgs.jdk}/include -I${pkgs.jdk}/include/${
        if pkgs.stdenv.hostPlatform.isDarwin then "darwin" else "linux"
      } proof.c -o libproof${pkgs.stdenv.hostPlatform.extensions.sharedLibrary}
    '';
    installPhase = ''
      mkdir -p $out/lib
      cp libproof* $out/lib/
    '';
  };
  ffi = purifier.nativeProjections {
    producer = native;
    libraries.proof = "lib/libproof${pkgs.stdenv.hostPlatform.extensions.sharedLibrary}";
    system = pkgs.stdenv.hostPlatform.system;
    inherit runCommand python3;
  };
  assets = pkgs.writeTextDir "dist/proof.js" "globalThis.answer = 42;";
  web = purifier.webjarProjections {
    producer = assets;
    assets = "${assets}/dist";
    artifactId = "proof";
    version = "1.0.0";
    inherit runCommand python3;
  };
in
{
  cross-type-native =
    runCommand "cross-type-native-consumers"
      {
        nativeBuildInputs = [
          python3
          pkgs.jdk
        ];
      }
      ''
        PYTHONPATH=${ffi."python-ffi"} python - <<'PY'
        import purifier_native
        assert purifier_native.load("proof").answer() == 42
        PY
        cat > Proof.java <<'JAVA'
        public class Proof {
          static { System.loadLibrary("proof"); }
          static native int answer();
          public static void main(String[] args) {
            if (answer() != 42) throw new AssertionError();
          }
        }
        JAVA
        javac Proof.java
        java @${ffi."java-ffi"}/java.args -cp . Proof
        touch $out
      '';
  cross-type-webjar =
    runCommand "cross-type-webjar-consumer"
      {
        nativeBuildInputs = [
          python3
          pkgs.jdk
        ];
      }
      ''
        jarfile=$(find ${web.maven} -name '*.jar')
        cat > Assets.java <<'JAVA'
        public class Assets {
          public static void main(String[] args) throws Exception {
            if (!Assets.class.getClassLoader().getResources("META-INF/resources/webjars/").hasMoreElements()) throw new AssertionError();
            try (var stream = Assets.class.getResourceAsStream("/META-INF/resources/webjars/proof/1.0.0/proof.js")) {
              if (stream == null || !new String(stream.readAllBytes()).contains("42")) throw new AssertionError();
            }
          }
        }
        JAVA
        javac Assets.java
        java -cp ".:$jarfile" Assets
        test -n "$(find ${web.ivy} -name '*.jar')"
        touch $out
      '';
}
