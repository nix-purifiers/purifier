# SPDX-License-Identifier: MIT
# Runs unchanged on the actual legacy RubyGems SDK as well as the host helper.
require "rubygems"
require "digest/sha2"
require File.expand_path("../../tools/rubygems_version_scheme", File.dirname(__FILE__))
scheme = PurifierRubyGemsVersionScheme
identity = "sha256-" + [Digest::SHA256.digest("native SDK fixture")].pack("m").delete("\n")
index_identity = Digest::SHA256.hexdigest("native index runtime fixture")
raise unless scheme.configuration({}) == [scheme::DEFAULT, nil, nil]
raise unless scheme.configuration({"versionScheme" => scheme::NUMERIC, "nativeSdkIdentity" => identity, "nativeIndexIdentity" => index_identity}) == [scheme::NUMERIC, identity, index_identity]
["0" * 64, "f" * 64, Digest::SHA256.hexdigest("package namespace fixture")].each do |hash|
  projected = scheme.version("1.0.0", hash, scheme::NUMERIC)
  native = Gem::Version.new(projected)
  raise unless Gem::Requirement.new("= " + projected).satisfied_by?(native)
  raise if Gem::Requirement.new("= " + projected).satisfied_by?(Gem::Version.new("99.0.0"))
  raise unless Marshal.load(Marshal.dump(native)).to_s == projected
  raise unless projected.split(".").last.to_i - 1 == hash.to_i(16)
  entry = {"versionScheme"=>scheme::NUMERIC, "nativeSdkIdentity"=>identity, "nativeIndexIdentity"=>index_identity, "sourceVersion"=>"1.0.0", "versionFingerprint"=>hash, "version"=>projected}
  scheme.validate_provided!(entry, scheme::NUMERIC, identity, index_identity)
end
hash = "0" * 64
raise unless scheme.version("1.0.0", hash, scheme::DEFAULT) == "1.0.0.1.nix.h" + hash
checks = [
  lambda { scheme.configuration({"versionScheme"=>"unknown"}) },
  lambda { scheme.configuration({"versionScheme"=>scheme::NUMERIC}) },
  lambda { scheme.configuration({"versionScheme"=>scheme::NUMERIC,"nativeSdkIdentity"=>identity}) },
  lambda { scheme.configuration({"versionScheme"=>scheme::NUMERIC,"nativeSdkIdentity"=>identity.sub(/=$/, "A")}) },
  lambda { scheme.configuration({"nativeSdkIdentity"=>identity}) },
  lambda { scheme.version("1.0.0.beta1", hash, scheme::NUMERIC) },
  lambda { scheme.version(" 1.0", hash, scheme::NUMERIC) },
  lambda { scheme.validate_provided!({"version"=>"1.0.0"}, scheme::NUMERIC, identity) },
  lambda { scheme.version("1.0.0", "short", scheme::NUMERIC) }
]
checks.each do |operation|
  rejected = false
  begin
    operation.call
  rescue StandardError
    rejected = true
  end
  raise "invalid numeric projection accepted" unless rejected
end
malformed_identities = [nil, false, true, 0, [], {}, "", identity + " ", identity + "\n", identity.sub(/=$/, ""), identity + "=", "sha256-" + "A" * 42 + "B=", identity.sub(/\Asha256-/, "sha256-\t"), identity.sub(/\Asha256-/, "sha256-\000")]
malformed_identities.each do |invalid|
  rejected = false
  begin
    scheme.configuration({"versionScheme"=>scheme::NUMERIC, "nativeSdkIdentity"=>invalid, "nativeIndexIdentity"=>index_identity})
  rescue StandardError
    rejected = true
  end
  raise "malformed SDK SRI accepted" unless rejected
end
puts "Version schemes: native full fingerprint, exact requirements, Marshal, default encoding, 9 projection and 14 strict SRI rejection controls PASS"
