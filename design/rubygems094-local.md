# Local RubyGems 0.9.4 consumer candidate

This candidate is isolated from Bundler support and public publication.

`rubygemsProjections` adds `legacyIndexProfile ? null` and
`legacyIndexAttestation ? null`. Existing callers omit both and retain the
existing SDK101 index path and catalog interpretation. The new profile is the
explicit string `ruby182-rubygems094-v1`; it requires numeric versions, the
actual `legacyIndexRuby` reference and a separately versioned ordinary-consumer
SDK attestation. Missing profile fields never select SDK094.

New catalog fields are `nativeIndexProfile`, `nativeIndexEncoderIdentity` and
`nativeConsumerAttestationIdentity`, and `nativeIndexClosureIdentity`. They occur only under the explicit new
profile. The actual `inputIdentity legacyIndexRuby` continues to be stored as
`nativeIndexIdentity`. No string-context normalization is introduced.

The new fingerprint envelope contains profile version, encoder identity,
attestation and authoritative closure identities and the existing native
SDK/index identities. The encoder
identity is the Nix input identity of a versioned encoder derivation that
binds the writer, original-runtime probe and strict schema validator. Provided input reuse
requires exact equality of all fields, then validates the existing complete
numeric fingerprint and archive integrity. No provided versions, archives or
catalog bytes are rewritten. A legacy catalog missing the new fields is
incompatible with the new profile; old default interpretation stays unchanged.

The ordinary-consumer attestation is a new schema, format
`rubygems-native-consumer-sdk`, schemaVersion 1, profile
`ruby182-rubygems094-v1`. It records original runtime and RubyGems reports,
absent PATCHLEVEL, actual executable, every installed gem artifact and its
role, original archive hashes, installed library hashes, compiler/build facts,
native JSON library hashes and physical closure hashes. Bundler remains an
incidental installed artifact, explicitly unloaded, never a supported client.
Canonical attestation bytes (sorted object keys, ASCII JSON, no whitespace
and no final newline in the digest) determine the SRI `nativeSdkIdentity`.
`nativeConsumerAttestationIdentity` separately records the unmodified Nix
input context of the attestation file; these identities serve different
purposes. Mutable source caches and
HOME/GEM_HOME are outside the immutable SDK and repository.

`rubygemsConsumerSdk { pkgs; sdk; components; compiler; nativeGems; name ? ...; }`
constructs the separate measured wrapper. Components have exactly `name`,
`version`, `archive`, and `library`; the bounded profile requires original
Ruby182, Gem094, sources001, JSON113, and incidental Bundler031 artifacts.
The wrapper exposes original `ruby` and `gem` plus
`purifier-verify-consumer-sdk ATTESTATION ACTUAL_RUBY CLOSURE_PATHS`.
`legacyIndexRuby` is this measured wrapper; `legacyIndexAttestation` is
`legacyIndexRuby.consumerAttestation`, a file in a separate derivation.
`consumerAttestationPackage` exposes that buildable artifact. The wrapper is
built first; the attestation measures the complete wrapper closure, including
its verifier Python/Nix runtime. The document records both the actual wrapper
`sdk` and the original `underlyingSdk`. Keeping the attestation outside the
wrapper prevents a hash self-reference. The verifier remeasures
the physical closure, archives and libraries, observes the explicitly passed
actual Ruby, and requires exact equality with the canonical document before
projection writes. Core obtains the authoritative closure directly through
Nix `exportReferencesGraph` for the actual `legacyIndexRuby`, rather than
trusting a caller list or the convenience `consumerClosure` passthru. The
exporter context is explicitly fingerprinted and checked on provided inputs.
The writer independently compares the complete actual
native observation, including executable, installed versions/specification
bytes and mapped parser origin, before creating indexes.

Compiler provenance retains byte-exact ATerm records read from the actual
`nativeGems.drvPath` and `compiler.drvPath`, checks compiler input and output
joins and the original JSON archive used by the native build, and records
their hashes. Only those serialized evidence copies discard string context;
this avoids realizing unrelated compiler bootstrap outputs. The index SDK,
encoder and attestation `inputIdentity` contexts remain intact.

SDK094 owns both YAML and Marshal serialization, including bulk and quick
indexes, generated from the exact projected archives using original
Gem::Format and Gem::SourceIndex. The modern indexer is skipped for this
profile; there are no advertised modern specs endpoints or incompatible
Gem101 Marshal endpoints. Before writing, the only permitted existing tree
is `gems/*.gem`, all regular non-symlink files; every specification is read
and minimum/platform/source-extension checks pass before index directories
are created. Hidden archive names, malformed native coordinates, noncanonical
roots and escaping paths are rejected; the exact validated archive list is
read without a second glob. The full output manifest and all serialized
index bodies are prepared before any index directories or files are written.
The exact resulting endpoint set is `yaml`, `yaml.Z`,
`Marshal.4.8`, `Marshal.4.8.Z`, `quick/index.rz`, and one YAML quick spec
plus one `quick/Marshal.4.8` spec for each archive. The normal Nix wrapper
then adds only `nix-support/inputs`. The writer checks the entire resulting
file and directory manifest and rejects symlinks and special files.
The existing SDK101 writer is untouched.

The native consumer first runs original `gem sources --list --source URL`,
then original `gem install` under an owned HOME/GEM_HOME with inherited
Ruby/Gem/Bundler and proxy environment removed. All requests remain on the
controlled loopback registry. Binary platform prompt input is recorded.
The native minimum requirements remain in effect. The adapter restricts
precompiled metadata to the observed x86_64-linux platform; the original
binary selection prompt is retained. The bounded native proof uses actual
Ruby182-built JSON113 bytes. It establishes no cross-runtime ABI portability
or source-extension compilation support. Explicit native source initialization
is supported workflow evidence, not raw cold-install parity.

Before independent review: strict schema and identity negative controls,
provided-policy controls, original SDK/index observations, full graph HTTP
and payload origin checks, wrong minimum/platform and stale/truncated index
controls, no-partial-output checks, physical closure checks, Nix rebuild and
existing profile regression checks. Source compilation and tool/project
runtime bridges are outside this candidate.
