# SPDX-License-Identifier: MIT
# Backport reproducible packaging to native codecs predating SOURCE_DATE_EPOCH.
require "rubygems"
require "rubygems/package"

unless Gem.respond_to?(:source_date_epoch)
  module Gem
    def self.source_date_epoch
      Time.at(Integer(ENV.fetch("SOURCE_DATE_EPOCH", "0"))).utc
    end
  end

  class Gem::Package
    alias_method :purifier_native_initialize, :initialize
    def initialize(*arguments)
      purifier_native_initialize(*arguments)
      @build_time = Gem.source_date_epoch
    end
  end

  class Gem::Package::TarHeader
    alias_method :purifier_native_initialize, :initialize
    def initialize(values)
      purifier_native_initialize(values.merge(:mtime => Gem.source_date_epoch))
    end
  end

  class Gem::Specification
    alias_method :purifier_native_date, :date
    def date
      if @date.nil?
        epoch = Gem.source_date_epoch
        @date = Time.utc(epoch.year, epoch.month, epoch.day)
      end
      purifier_native_date
    end
  end

  # Syck's native map emitter preserves the regular YAML map representation.
  # MRI 1.8 Hash iteration order changes between processes.
  if RUBY_VERSION =~ /\A1\.8\./
    Gem.load_yaml
    class Hash
      def to_yaml(options = {})
        YAML.quick_emit(self, options) do |output|
          output.map(taguri, to_yaml_style) do |mapping|
            keys.sort_by { |key| [key.class.to_s, key.to_s] }.each do |key|
              mapping.add(key, self[key])
            end
          end
        end
      end
    end
  end
end

module PurifierRubyGemsCodec
  # Keep JSON data independent of old Hash enumeration order. Native JSON
  # still encodes every key and scalar; arrays retain their semantic order.
  def self.json(value)
    case value
    when Hash
      "{" + value.keys.sort.map { |key| JSON.dump(key) + ":" + json(value[key]) }.join(",") + "}"
    when Array
      "[" + value.map { |entry| json(entry) }.join(",") + "]"
    else
      JSON.dump(value)
    end
  end
end
