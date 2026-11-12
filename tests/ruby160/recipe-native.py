# SPDX-License-Identifier: MIT
from pathlib import Path
import importlib.util,json,hashlib,os,sys,tempfile
r160,r180,libc,openssl,helper,out=map(Path,sys.argv[1:]);out.mkdir();m=importlib.util.spec_from_file_location('bounded',helper);bounded=importlib.util.module_from_spec(m);m.loader.exec_module(bounded);receipt={'complete':False,'scope':'Resource test recipes v1 native extension APIs; generated OpenSSL DATE policy explicit','commands':[]};env={k:v for k,v in os.environ.items()if not k.startswith(('RUBY','GEM_','BUNDLE_','BUNDLER_','LD_LIBRARY_PATH','LD_PRELOAD'))}
with tempfile.TemporaryDirectory(prefix='ordered-native-')as tmp:
 env['HOME']=tmp
 def run(label,ruby,code,args):
  argv=[str(ruby/'bin/ruby'),'-e',code,*map(str,args)];p=bounded.run(argv,env=env,timeout=30);row={'label':label,'argv':argv,'exit':p.returncode}
  for stream in ['stdout','stderr']:
   raw=getattr(p,stream);(out/(label+'.'+stream)).write_bytes(raw);row[stream+'Sha256']=hashlib.sha256(raw).hexdigest()
  receipt['commands'].append(row);(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');assert p.returncode==0,(label,p.stderr);return p.stdout
 def code(version,body,names):
  return 'raise unless RUBY_VERSION=="'+version+'" && RUBY_PLATFORM=="i686-linux-gnu" && ["x"].pack("p").size==4;raise if defined?(Gem);'+body+';root=ARGV.shift;maps=File.readlines("/proc/self/maps").join;'+''.join('raise unless maps.index(root+"/lib/ruby/'+('1.6'if version=='1.6.0'else'1.8')+'/i686-linux-gnu/'+n+'.so");'for n in names)+'puts "NATIVE-EXTENSION-APIS|'+version+'|PASS"'
 run('ruby160-md5',r160,code('1.6.0','require "md5";d=MD5.new;d.update("abc");raise unless d.hexdigest=="900150983cd24fb0d6963f7d28e17f72"',['md5']),[r160])
 run('ruby160-sdbm',r160,code('1.6.0','require "sdbm";SDBM.open(ARGV.pop){|db|db["answer"]="42";raise unless db["answer"]=="42"}',['sdbm']),[r160,Path(tmp)/'sdbm160'])
 run('ruby180-sdbm',r180,code('1.8.0','require "sdbm";SDBM.open(ARGV.pop){|db|db["answer"]="42";raise unless db["answer"]=="42"}',['sdbm']),[r180,Path(tmp)/'sdbm180'])
 run('ruby180-syck',r180,code('1.8.0','require "yaml";raise unless defined?(YAML::Syck::Parser);raise unless YAML.load("answer: 42\\n")["answer"]==42',['syck']),[r180])
 run('ruby180-openssl',r180,code('1.8.0','require "openssl";d=OpenSSL::Digest::Digest.new("MD5");d.update("abc");raise unless d.hexdigest=="900150983cd24fb0d6963f7d28e17f72";d=OpenSSL::Digest::Digest.new("SHA1");d.update("abc");raise unless d.hexdigest=="a9993e364706816aba3e25717850c26c9cd0d89d";crypto=ARGV.pop;raise unless File.readlines("/proc/self/maps").join.index(crypto+"/lib/libcrypto.so.0.9.7")',['openssl']),[r180,openssl])
 run('ruby180-dl',r180,code('1.8.0','require "dl";h=DL.dlopen(ARGV.pop);f=h["strlen","IS"];raise unless f.call("x"*42)[0]==42',['dl']),[r180,libc/'lib/libc.so.6'])
receipt['complete']=True;(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
