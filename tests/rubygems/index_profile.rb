# SPDX-License-Identifier: MIT
require "rubygems"
require "digest/sha2"
require File.expand_path("../../tools/rubygems_version_scheme",File.dirname(__FILE__))
scheme=PurifierRubyGemsVersionScheme
sdk="sha256-"+[Digest::SHA256.digest("ordinary SDK fixture")].pack("m").delete("\n")
index=Digest::SHA256.hexdigest("actual native index runtime context")
profile={"versionScheme"=>scheme::NUMERIC,"nativeSdkIdentity"=>sdk,"nativeIndexIdentity"=>index,"nativeIndexProfile"=>scheme::INDEX_094,"nativeIndexEncoderIdentity"=>Digest::SHA256.hexdigest("encoder bundle context"),"nativeConsumerAttestationIdentity"=>Digest::SHA256.hexdigest("attestation context")}
configuration=scheme.index_configuration(profile)
raise unless scheme.configuration(profile)==[scheme::NUMERIC,sdk,index]
raise unless scheme.index_configuration({}).nil?
entry=profile.merge("sourceVersion"=>"1.0.0","versionFingerprint"=>"0"*64,"version"=>scheme.version("1.0.0","0"*64,scheme::NUMERIC))
scheme.validate_provided!(entry,scheme::NUMERIC,sdk,index,configuration)
def rejected!
  rejected=false
  begin;yield;rescue StandardError;rejected=true;end
  raise "incompatible native profile accepted" unless rejected
end
scheme::INDEX_FIELDS.each do |key|
  changed=profile.dup;changed.delete(key);rejected! {scheme.configuration(changed)}
end
rejected! {scheme.configuration(profile.merge("versionScheme"=>scheme::DEFAULT))}
rejected! {scheme.configuration(profile.merge("nativeIndexProfile"=>"rubygems094"))}
rejected! {scheme.configuration(profile.merge("nativeIndexEncoderIdentity"=>"short"))}
rejected! {scheme.validate_provided!(entry,scheme::NUMERIC,sdk,index)}
legacy=entry.reject{|key,_|scheme::INDEX_FIELDS.include?(key)}
scheme.validate_provided!(legacy,scheme::NUMERIC,sdk,index)
rejected! {scheme.validate_provided!(legacy,scheme::NUMERIC,sdk,index,configuration)}
scheme::INDEX_FIELDS.each do |key|
  changed=entry.merge(key=>(key=="nativeIndexProfile" ? "unknown" : "f"*64))
  rejected! {scheme.validate_provided!(changed,scheme::NUMERIC,sdk,index,configuration)}
end
puts "Index profile: explicit version/encoder/attestation, old omitted-profile reuse and 11 rejection controls PASS"
