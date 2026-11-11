# SPDX-License-Identifier: MIT
"""Reject a forged embedded factory before its intentional owned side effect."""
from pathlib import Path
import hashlib, importlib.util, json, os, sys, tempfile
sdk, forged, closure, verifier, probe, sources_helper, output = map(Path,sys.argv[1:])
module = importlib.util.spec_from_file_location('bounded',verifier)
bounded = importlib.util.module_from_spec(module)
module.loader.exec_module(bounded)
output.mkdir()
receipt = dict(complete=False,scope='forged factory ordering; combined genuine+forged Nix closure intentionally reaches byte guard',commands=[])
with tempfile.TemporaryDirectory(prefix='factory-order-') as temp:
    root=Path(temp)
    env={k:v for k,v in os.environ.items() if not k.startswith(('RUBY','GEM_','BUNDLE_','BUNDLER_'))}
    env.update(HOME=temp,GEM_HOME=temp+'/gems',GEM_PATH=temp+'/gems',TZ='UTC')
    def run(label,args,success):
        args=list(map(str,args))
        wrapper='import subprocess,sys,json;p=subprocess.run(sys.argv[1:],capture_output=True);print(json.dumps(dict(exit=p.returncode,stdout=p.stdout.hex(),stderr=p.stderr.hex())))'
        result=json.loads(bounded.run([sys.executable,'-B','-c',wrapper,*args],env))
        row=dict(label=label,argv=args,exit=result['exit'])
        for stream in ['stdout','stderr']:
            data=bytes.fromhex(result[stream]);(output/(label+'.'+stream)).write_bytes(data);row[stream+'Sha256']=hashlib.sha256(data).hexdigest()
        receipt['commands'].append(row)
        (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
        assert (result['exit']==0)==success, result
        return bytes.fromhex(result['stderr'])
    # Prove the test factory really executes its marker when deliberately loaded.
    control=root/'control-sentinel';env['PURIFIER_FACTORY_SENTINEL']=str(control)
    run('owned-forged-factory-positive-control',[sdk/'bin/ruby',sources_helper,forged],True)
    assert control.read_bytes()==b'forged factory executed\n'
    sentinel=root/'rejected-sentinel';env['PURIFIER_FACTORY_SENTINEL']=str(sentinel)
    descriptor=json.loads((sdk/'share/purifier/consumer-components.json').read_text())
    descriptor['originalSources']=str(forged)
    descriptor_path=root/'forged-descriptor.json'
    descriptor_path.write_text(json.dumps(descriptor,sort_keys=True,separators=(',',':'))+'\n')
    document=root/'must-not-exist.json'
    nix=Path(os.environ['PURIFIER_TEST_NIX'])
    stderr=run('reject-unverified-factory-before-execution',[sys.executable,'-B',verifier,'create',descriptor_path,closure,nix,document,sdk/'bin/ruby',probe,sources_helper],False)
    assert b'embedded source bytes changed' in stderr
    assert not sentinel.exists() and not document.exists()
    receipt.update(complete=True,positiveControlExecuted=True,rejectedFactoryDidNotExecute=True,noAttestationOutput=True,forgedFactorySha256=hashlib.sha256((forged/'sources.gemspec').read_bytes()).hexdigest(),descriptorSha256=hashlib.sha256(descriptor_path.read_bytes()).hexdigest())
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
