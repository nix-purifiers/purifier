# SPDX-License-Identifier: MIT
# Ordinary Helm reads the emitted JSON through its native --values interface.
{
  pkgs,
  producer,
  expectedKey,
  expectedValue,
}:
pkgs.runCommand "json-projection-ordinary-helm"
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.kubernetes-helm
    ];
  }
  ''
    mkdir -p chart/templates
    cat > chart/Chart.yaml <<'YAML'
    apiVersion: v2
    name: json-projection-consumer
    version: 1.0.0
    YAML
    printf '%s\n' '{{ .Values | toJson }}' > chart/templates/result.json
    helm template consumer chart --values ${producer.projections.json.files.default} > result.yaml
    python - <<'PY'
    import json
    text = open('result.yaml').read()
    value = json.loads(text[text.index('{'):])
    assert value[${builtins.toJSON expectedKey}] == json.loads(${builtins.toJSON (builtins.toJSON expectedValue)})
    PY
    touch $out
  ''
