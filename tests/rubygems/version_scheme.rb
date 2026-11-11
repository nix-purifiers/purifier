# SPDX-License-Identifier: MIT
# Runs unchanged on the actual legacy RubyGems SDK as well as the host helper.
require "rubygems"
require "digest/sha2"
require File.expand_path("../../tools/rubygems_version_scheme", File.dirname(__FILE__))
scheme = PurifierRubyGemsVersionScheme
identity = "sha256-" + Base64.encode64(Digest::SHA256.digest("native SDK fixture")).delete("\n")
raise unless scheme.configuration({}) == [scheme::DEFAULT, nil]
raise unless scheme.configuration({"versionScheme" => scheme::NUMERIC, "nativeSdkIdentity" => identity}) == [scheme::NUMERIC, identity]
["0" * 64, "f" * 64, Digest::SHA256.hexdigest("package namespace fixture")].each do |hash|
  projected = scheme.version("1.0.0", hash, scheme::NUMERIC)
  native = Gem::Version.new(projected)
  raise unless Gem::Requirement.new("= " + projected).satisfied_by?(native)
  raise if Gem::Requirement.new("= " + projected).satisfied_by?(Gem::Version.new("99.0.0"))
  raise unless Marshal.load(Marshal.dump(native)).to_s == projected
  raise unless projected.split(".").last.to_i - 1 == hash.to_i(16)
  entry = {"versionScheme"=>scheme::NUMERIC, "nativeSdkIdentity"=>identity, "sourceVersion"=>"1.0.0", "versionFingerprint"=>hash, "version"=>projected}
  scheme.validate_provided!(entry, scheme::NUMERIC, identity)
end
hash = "0" * 64
raise unless scheme.version("1.0.0", hash, scheme::DEFAULT) == "1.0.0.1.nix.h" + hash
checks = [
  lambda { scheme.configuration({"versionScheme"=>"unknown"}) },
  lambda { scheme.configuration({"versionScheme"=>scheme::NUMERIC}) },
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
puts "Version schemes: native zero/max/full fingerprint, exact requirements, Marshal, default encoding and 8 rejection controls PASS"
