# SPDX-License-Identifier: MIT
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
import importlib.util
import json,subprocess,os,hashlib,shutil,threading,functools,tarfile,io,sys
sdk=Path(sys.argv[1]);projection=Path(sys.argv[2]);native=Path(sys.argv[3]);gate=Path(sys.argv[4]);out=Path(sys.argv[5]);out.mkdir();assert json.loads((gate/'receipt.json').read_text())['native32All20Pass'];work=Path(os.environ['TMPDIR'])/'consumer';work.mkdir();home=work/'home';home.mkdir();gems=work/'gems';gems.mkdir();repo=work/'registry';(repo/'gems').mkdir(parents=True);archive=next((projection/'gems').glob('*.gem'));competitor=native/'ancient_leaf-1.0.0.gem';shutil.copyfile(projection/'yaml',repo/'yaml');shutil.copyfile(projection/'yaml.Z',repo/'yaml.Z');shutil.copyfile(archive,repo/'gems'/archive.name);shutil.copyfile(competitor,repo/'gems'/competitor.name);env={k:v for k,v in os.environ.items()if not k.startswith(('RUBY','GEM_','BUNDLE_','BUNDLER_'))and k.lower()not in('http_proxy','https_proxy','all_proxy')};env.update(HOME=str(home),GEM_HOME=str(gems),GEM_PATH=str(gems));receipt={'complete':False,'scope':'CI original0811/i686 production-profile pure consumer, actual produced YAML indexes unchanged; unindexed raw competitor present only, earlier feasibility proves indexed competitor; no public/x64/Bundler/ABI portability claim','executionArena':'confined Nix build sandbox','sdk':str(sdk),'projection':str(projection),'commands':[],'requests':[]}
def run(label,args,cwd=None,success=True):
 args=list(map(str,args))
 spec=importlib.util.spec_from_file_location('bounded',sys.argv[6]);bounded=importlib.util.module_from_spec(spec);spec.loader.exec_module(bounded)
 wrapper='import subprocess,sys,json; p=subprocess.run(sys.argv[2:],cwd=sys.argv[1],capture_output=True); print(json.dumps(dict(exit=p.returncode,stdout=p.stdout.hex(),stderr=p.stderr.hex())))'
 record=json.loads(bounded.run([sys.executable,'-c',wrapper,str(cwd or work),*args],env));p=subprocess.CompletedProcess(args,record['exit'],bytes.fromhex(record['stdout']),bytes.fromhex(record['stderr']))
 for stream,data in [('stdout',p.stdout),('stderr',p.stderr)]:(out/(label+'.'+stream)).write_bytes(data)
 receipt['commands'].append(dict(label=label,argv=args,cwd=str(cwd or work),exit=p.returncode,stdoutSha256=hashlib.sha256(p.stdout).hexdigest(),stderrSha256=hashlib.sha256(p.stderr).hexdigest()));(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n');assert(p.returncode==0)==success,(label,p.stderr.decode()[-4000:]);return p
index='require "rubygems";Gem.manage_gems;require "yaml";require "zlib";y=File.open(ARGV[0]+"/yaml","rb"){|f|f.read};z=File.open(ARGV[0]+"/yaml.Z","rb"){|f|f.read};raise unless Zlib::Inflate.inflate(z)==y;i=YAML.load(y);raise unless i.is_a?(Gem::SourceIndex);raise unless i.find_name("ancient_leaf").size==1;puts "PRODUCTION-INDEX|#{RUBY_VERSION}|#{Gem::RubyGemsVersion}"'
run('native0811-produced-index-validation',[sdk/'bin/ruby','-e',index,repo])
yaml_fallback = len(sys.argv)>7 and sys.argv[7]=='--yaml-fallback'
if yaml_fallback:(repo/'yaml.Z').unlink()
receipt['endpointMode']='plain-YAML-fallback' if yaml_fallback else 'compressed-YAML'
class Handler(SimpleHTTPRequestHandler):
 def log_message(self,*args):pass
 def send_response(self,code,message=None):
  if hasattr(self,'receipt_row'):self.receipt_row['status']=code
  super().send_response(code,message)
 def do_GET(self):
  row=dict(method='GET',path=self.path)
  if self.path.startswith('/gems/'):
   p=repo/self.path[1:]
   if p.is_file():row['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
  self.receipt_row=row;receipt['requests'].append(row);super().do_GET()
 def do_HEAD(self):
  self.receipt_row=dict(method='HEAD',path=self.path);receipt['requests'].append(self.receipt_row);super().do_HEAD()
server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(repo)));threading.Thread(target=server.serve_forever,daemon=True).start();host='http://127.0.0.1:'+str(server.server_port);version=archive.name[len('ancient_leaf-'):-4]
try:
 run('ordinary0811-http-install',[sdk/'bin/gem','install','--remote','--no-rdoc','--source',host,'ancient_leaf','--version',version])
 code='require "rubygems";raise unless RUBY_VERSION=="1.8.0" && RUBY_PLATFORM=="i686-linux-gnu" && ["pointer"].pack("p").size==4;raise if Gem.respond_to?(:loaded_specs);raise if Kernel.instance_methods.map{|m|m.to_s}.include?("gem");require_gem "ancient_leaf","= "+ARGV[0];origin=nil;set_trace_func proc{|event,file,line,id,binding,klass|origin=file if event=="call" && id==:answer};require "ancient_leaf";raise unless AncientLeaf.answer==42;set_trace_func nil;raise unless origin && origin.index(ENV["GEM_HOME"]+"/")==0;specs=Gem.source_index.find_name("ancient_leaf","= "+ARGV[0]);raise unless specs.size==1 && specs[0].full_gem_path.index(ENV["GEM_HOME"]+"/")==0;puts "ORIGIN|#{origin}";puts "SELECTED|#{specs[0].version}";puts "NATIVE|#{RUBY_VERSION}|#{RUBY_PLATFORM}|#{Gem::RubyGemsVersion}|42"'
 result=run('ordinary0811-native-origin',[sdk/'bin/ruby','-e',code,version]).stdout;assert b'NATIVE|1.8.0|i686-linux-gnu|0.8.11|42'in result;method=next(gems.glob('gems/ancient_leaf-*/lib/ancient_leaf.rb'));assert str(method).encode()in result
 with tarfile.open(archive)as outer:
  with tarfile.open(fileobj=io.BytesIO(outer.extractfile('data.tar.gz').read()),mode='r:gz')as payload:assert method.read_bytes()==payload.extractfile('lib/ancient_leaf.rb').read()
 assert any(r['path']=='/gems/'+archive.name and r.get('sha256')==hashlib.sha256(archive.read_bytes()).hexdigest()for r in receipt['requests']);assert not any(r['path']=='/gems/'+competitor.name for r in receipt['requests'])
 run('reject-unavailable-exact-version',[sdk/'bin/gem','install','--remote','--no-rdoc','--source',host,'ancient_leaf','--version','= 9.9.9'],success=False)
 relocated=work/'relocated';shutil.copytree(gems,relocated);hidden=work/'original.hidden';gems.rename(hidden)
 try:
  assert not gems.exists();env.update(GEM_HOME=str(relocated),GEM_PATH=str(relocated));before=len(receipt['requests']);r=run('relocated-original-unavailable',[sdk/'bin/ruby','-e',code,version]).stdout;assert str(relocated).encode()in r and str(method).encode()not in r;assert before==len(receipt['requests'])
 finally:env.update(GEM_HOME=str(gems),GEM_PATH=str(gems));hidden.rename(gems)
 minimal=work/'minimum';(minimal/'lib').mkdir(parents=True);(minimal/'lib/newer_only.rb').write_text('raise "minimum bypassed"\n');(minimal/'newer_only.gemspec').write_text('Gem::Specification.new do |s|\ns.name="newer_only";s.version="1.0.0";s.summary="original minimum negative";s.authors=["fixture"];s.files=["lib/newer_only.rb"];s.require_path="lib";s.required_ruby_version=">= 1.8.1"\nend\n');run('native-build-minimum-fixture',[sdk/'bin/gem','build','newer_only.gemspec'],minimal);p=run('original-cli-minimum-error-zero-exit',[sdk/'bin/gem','install','--local','--no-rdoc',minimal/'newer_only-1.0.0.gem']);assert b'requires Ruby version >= 1.8.1'in p.stderr;receipt['originalCliMinimumErrorExit']=p.returncode;p=run('original-installer-minimum-exception',[sdk/'bin/ruby','-e','require "rubygems";Gem.manage_gems;Gem::Installer.new(ARGV[0]).install(false,ENV["GEM_HOME"])',minimal/'newer_only-1.0.0.gem'],success=False);assert b'requires Ruby version >= 1.8.1'in p.stderr;assert not list(gems.glob('gems/newer_only*'))and not list(gems.glob('specifications/newer_only*'));shutil.copyfile(method,out/'executed-ancient_leaf.rb');assert any(r['method']=='GET' and r['path']=='/yaml' and r.get('status')==200 for r in receipt['requests']) if yaml_fallback else any(r['method']=='GET' and r['path']=='/yaml.Z' and r.get('status')==200 for r in receipt['requests']);receipt.update(complete=True,ruby='1.8.0',rubyPlatform='i686-linux-gnu',pointerBytes=4,rubygems='0.8.11',api='original require_gem; original SourceIndex constructor hash',exactVersion=version,archiveSha256=hashlib.sha256(archive.read_bytes()).hexdigest(),methodSha256=hashlib.sha256(method.read_bytes()).hexdigest(),unindexedRawCompetitorNotFetched=True,productionIndexConsumedUnmodified=True,originalUnavailableDuringRelocation=True,nativePackageMinimumRetained=True)
finally:server.shutdown();server.server_close();(out/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
