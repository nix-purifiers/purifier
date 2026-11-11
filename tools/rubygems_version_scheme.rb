# SPDX-License-Identifier: MIT
# Explicit projection identities for native RubyGems version grammars.
module PurifierRubyGemsVersionScheme
  DEFAULT = "nix-prerelease-v1"
  NUMERIC = "legacy-numeric-v1"
  INDEX_094 = "ruby182-rubygems094-v1"
  INDEX_0811 = "ruby180-rubygems0811-i686-v1"
  INDEX_FIELDS = %w[nativeIndexProfile nativeIndexEncoderIdentity nativeConsumerAttestationIdentity nativeIndexClosureIdentity]

  def self.index_configuration(specification)
    present = INDEX_FIELDS.select { |key| specification.key?(key) }
    return nil if present.empty?
    raise "incomplete native index profile" unless present == INDEX_FIELDS
    raise "unsupported native index profile" unless [INDEX_094, INDEX_0811].include?(specification["nativeIndexProfile"])
    raise "native index profile requires numeric versions" unless specification["versionScheme"] == NUMERIC
    INDEX_FIELDS[1..-1].each do |key|
      raise "invalid native index profile identity" unless specification[key].is_a?(String) && specification[key] =~ /\A[0-9a-f]{64}\z/
    end
    INDEX_FIELDS.map { |key| specification.fetch(key) }
  end

  def self.configuration(specification)
    index_configuration(specification)
    scheme = specification.fetch("versionScheme", DEFAULT)
    raise "unsupported RubyGems version scheme" unless [DEFAULT, NUMERIC].include?(scheme)
    identity = specification["nativeSdkIdentity"]
    index_identity = specification["nativeIndexIdentity"]
    if scheme == NUMERIC
      valid = identity.is_a?(String) && identity =~ /\Asha256-[A-Za-z0-9+\/]{43}=\z/
      if valid
        raw = identity.sub(/\Asha256-/, "").unpack("m")[0]
        valid = raw.length == 32 && "sha256-" + [raw].pack("m").delete("\n") == identity
      end
      raise "numeric RubyGems projection needs an exact SDK identity" unless valid
      raise "numeric RubyGems projection needs an exact native index runtime" unless index_identity.is_a?(String) && index_identity =~ /\A[0-9a-f]{64}\z/
    elsif !identity.nil? || !index_identity.nil?
      raise "native SDK identity requires the numeric RubyGems version scheme"
    end
    [scheme, identity, index_identity]
  end

  def self.numeric_source!(version)
    raise "numeric RubyGems scheme cannot represent this upstream version" unless version.is_a?(String) && version =~ /\A[0-9]+(?:\.[0-9]+)*\z/
    # Keep the native textual identity. RubyGems may compare 1 and 1.0 as
    # equal; the original version and archive remain part of the fingerprint.
    raise "native RubyGems changed numeric version text" unless Gem::Version.new(version).to_s == version
    version
  end

  def self.version(source, fingerprint, scheme)
    raise "invalid RubyGems version fingerprint" unless fingerprint.is_a?(String) && fingerprint =~ /\A[0-9a-f]{64}\z/
    return source + ".1.nix.h" + fingerprint if scheme == DEFAULT
    raise "unsupported RubyGems version scheme" unless scheme == NUMERIC
    numeric_source!(source)
    # The positive bijection retains all 256 bits, including an all-zero
    # hash, without creating a trailing-zero version alias in old RubyGems.
    source + ".1." + (fingerprint.to_i(16) + 1).to_s
  end

  def self.validate_provided!(entry, scheme, identity, index_identity = nil, index_profile = nil)
    raise "provided RubyGems index profile differs" unless index_configuration(entry) == index_profile
    provided_scheme = entry.fetch("versionScheme", DEFAULT)
    raise "incompatible provided RubyGems version scheme" unless provided_scheme == scheme
    if scheme == NUMERIC
      raise "provided numeric RubyGems SDK differs" unless entry["nativeSdkIdentity"] == identity
      raise "provided numeric RubyGems index runtime differs" unless entry["nativeIndexIdentity"] == index_identity
      fingerprint = entry.fetch("versionFingerprint")
      expected = version(entry.fetch("sourceVersion"), fingerprint, scheme)
      raise "provided numeric RubyGems version differs from provenance" unless entry.fetch("version") == expected
    elsif entry.key?("nativeSdkIdentity") || entry.key?("versionFingerprint") || entry.key?("nativeIndexIdentity")
      raise "unexpected numeric provenance in default RubyGems input"
    end
  end
end
