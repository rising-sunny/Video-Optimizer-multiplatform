import hashlib,json,os,shutil,subprocess,sys,tempfile,unittest
from pathlib import Path

WORK=Path(__file__).parent
class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.repo=self.base/'repo';self.repo.mkdir()
        self.root=self.base/'automation';(self.root/'runtime').mkdir(parents=True)
        (self.repo/'.venv/bin').mkdir(parents=True);(self.repo/'.venv/bin/python').symlink_to(sys.executable)
        ops=self.repo/'ops/chat-receiver-v1';ops.mkdir(parents=True)
        shutil.copy2(WORK/'chat-receiver-kit-v1.tar.xz',ops/'chat-receiver-kit-v1.tar.xz')
        self.git('init','-q');self.git('add','ops')
        self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture')
        self.revision=self.git('rev-parse','HEAD').stdout.strip()
        script=(WORK/'install-vps.sh').read_text()
        script=script.replace('root=/home/videoagent/video-automation','root='+str(self.root))
        script=script.replace('repo=/home/videoagent/Video-Optimizer-multiplatform','repo='+str(self.repo))
        script=script.replace('$(id -un) != videoagent','$(id -un) != '+os.environ.get('USER','agent'))
        script=script.replace('"$python" -B "$destination/install_chat_receiver.py"',"printf 'installer invocation reached\\n'")
        self.script=self.base/'bootstrap.sh';self.script.write_text(script)
    def git(self,*args):return subprocess.run(['git','-C',str(self.repo),*args],check=True,capture_output=True,text=True)
    def run_script(self):return subprocess.run(['bash',str(self.script),self.revision],capture_output=True,text=True)
    def test_verified_archive_extracted_then_installer_is_reached(self):
        result=self.run_script();self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('installer invocation reached',result.stdout)
        destination=self.root/'runtime/chat-receiver-kit-v1'
        checks=json.loads((destination/'KIT-SHA256.json').read_text())
        self.assertTrue(all(hashlib.sha256((destination/name).read_bytes()).hexdigest()==value for name,value in checks.items()))
        self.assertFalse(list((self.root/'runtime').glob('.chat-kit.*')))
    def test_existing_destination_not_replaced(self):
        destination=self.root/'runtime/chat-receiver-kit-v1';destination.mkdir();(destination/'keep').write_text('preserved')
        result=self.run_script();self.assertNotEqual(result.returncode,0)
        self.assertEqual((destination/'keep').read_text(),'preserved')
        self.assertNotIn('installer invocation reached',result.stdout)
    def test_corrupted_payload_never_extracts_or_installs(self):
        path=self.repo/'ops/chat-receiver-v1/chat-receiver-kit-v1.tar.xz';path.write_bytes(b'corrupt fixture')
        self.git('add','ops');self.git('-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','-qm','corrupted fixture')
        self.revision=self.git('rev-parse','HEAD').stdout.strip()
        result=self.run_script();self.assertNotEqual(result.returncode,0)
        self.assertFalse((self.root/'runtime/chat-receiver-kit-v1').exists())
        self.assertNotIn('installer invocation reached',result.stdout)

if __name__=='__main__':unittest.main(verbosity=2)
