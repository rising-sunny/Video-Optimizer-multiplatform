"""Create a deterministic, readable bootstrap archive and verify it offline."""
import ast
import base64
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile

SOURCE=Path(__file__).resolve().parent
OUT=Path('/workspace/artifacts')
NAME='video-autonomia-general-v49-20261107'

def main():
    files=sorted(p for p in SOURCE.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='payload-sha256.json')
    for file in files:
        if file.suffix=='.py':ast.parse(file.read_bytes())
    payload={str(p.relative_to(SOURCE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (SOURCE/'payload-sha256.json').write_text(json.dumps(payload,indent=2)+'\n');files.append(SOURCE/'payload-sha256.json')
    archive=OUT/(NAME+'.tgz')
    with archive.open('wb') as stream:
        with gzip.GzipFile(fileobj=stream,mode='wb',mtime=0) as gz:
            with tarfile.open(fileobj=gz,mode='w') as tar:
                directories={Path('.')}
                for file in files:directories.update(file.relative_to(SOURCE).parents)
                for relative in sorted(directories,key=lambda p:(len(p.parts),str(p))):
                    entry=tarfile.TarInfo(NAME if str(relative)=='.' else NAME+'/'+str(relative));entry.type=tarfile.DIRTYPE;entry.mode=0o755;tar.addfile(entry)
                for file in sorted(files):
                    raw=file.read_bytes();entry=tarfile.TarInfo(NAME+'/'+str(file.relative_to(SOURCE)))
                    entry.size=len(raw);entry.mode=0o644;tar.addfile(entry,io.BytesIO(raw))
    encoded=archive.with_suffix('.tgz.b64');encoded.write_text(base64.encodebytes(archive.read_bytes()).decode())
    with tempfile.TemporaryDirectory(prefix='workflow-v49-cold-') as tmp:
        subprocess.run(['tar','-xzpf',str(archive),'-C',tmp],check=True)
        bundle=Path(tmp)/NAME
        for name,value in payload.items():assert hashlib.sha256((bundle/name).read_bytes()).hexdigest()==value
        assert all((p.stat().st_mode&0o777)==(0o755 if p.is_dir() else 0o644) for p in bundle.rglob('*'))
        env=dict(os.environ,PYTHONPATH=str(bundle/'modules')+':'+str(bundle),PYTHONDONTWRITEBYTECODE='1')
        subprocess.run(['python3','-B','-m','unittest','discover','-s',str(bundle/'tests'),'-q'],env=env,cwd=bundle,check=True)
        # Reproduce the deployment test layout, which differs from the source tree.
        stage=Path(tmp)/'staged';(stage/'candidate').mkdir(parents=True);(stage/'tests').mkdir();(stage/'work').mkdir()
        for source in (bundle/'modules').glob('*.py'):shutil.copy2(source,stage/'candidate'/source.name)
        shutil.copy2(bundle/'maintenance_daemon.py',stage/'candidate/maintenance_daemon.py')
        shutil.copy2(bundle/'tests/test_workflow.py',stage/'tests/test_workflow.py')
        shutil.copy2(bundle/'source_patch.py',stage/'tests/source_patch.py')
        shutil.copytree(bundle/'baseline',stage/'tests/baseline')
        env['PYTHONPATH']=str(stage/'candidate')
        subprocess.run(['python3','-B','-m','unittest','discover','-s',str(stage/'tests'),'-q'],env=env,cwd=stage/'work',check=True)
    metadata=dict(name=NAME,bytes=archive.stat().st_size,archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
        base64_git_blob=hashlib.sha1(b'blob '+str(encoded.stat().st_size).encode()+b'\0'+encoded.read_bytes()).hexdigest(),files=len(files),offline_tests=44)
    (OUT/(NAME+'-metadata.json')).write_text(json.dumps(metadata,indent=2)+'\n')
    print(json.dumps(metadata,indent=2))

if __name__=='__main__':main()
