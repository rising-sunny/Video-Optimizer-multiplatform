"""Isolated installation transaction tests; never accesses the real VPS."""
import contextlib,hashlib,io,json,sys,tempfile,unittest
from pathlib import Path
import install_chat_receiver as installer
from test_chat_receiver import CORE,REMOTE

class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.root=self.base/'vps';self.kit=self.base/'kit';self.kit.mkdir();self.root.mkdir()
        root=self.root;work=Path(installer.__file__).parent
        csource=CORE.replace("p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))", "p=Path(p)\n if v.get('chat_receiver_validation') and (ROOT/'FAIL_READY').exists():raise RuntimeError('fixture_readiness_write_failed')\n p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v))")
        (root/'daily_core.py').write_text(csource)
        (root/'daily_remote.py').write_text('from daily_core import *\ndef publish_preflight(*a,**kw):raise AssertionError(\'network_forbidden\')\n'+REMOTE)
        (root/'helpers').mkdir();(root/'helpers/__init__.py').write_text('')
        (root/'helpers/daily.py').write_text('import contextlib\nlocked=contextlib.nullcontext\n')
        (root/'requests.py').write_text('''class Session:
 def request(*a,**kw):raise AssertionError('network_forbidden')
class sessions:
 Session=Session
''')
        tests='import unittest\nclass ActivationTests(unittest.TestCase):\n'
        for i in range(26):tests+=f' def test_fixture_{i}(self):self.assertTrue(True)\n'
        (root/'test_activation.py').write_text(tests)
        prod=root/'runtime/production';prod.mkdir(parents=True)
        ready={'checked_at':'preserved_time','checks':{'legacy':True},'code_sha256':{n:self.sha(root/n) for n in ('daily_core.py','daily_remote.py')}}
        (prod/'readiness.json').write_text(json.dumps(ready))
        (prod/'generation-mode.json').write_text(json.dumps({'generation':'on_demand_codex_chat','vps_generation':'disabled'}))
        (prod/'activation.json').write_text(json.dumps({'status':'enabled'}))
        for name in (*installer.RUNTIME_FILES,*installer.TEST_FILES,'chat_bridge_patch.py','install_chat_receiver.py'):
            source=(work/name).read_text()
            if name in ('chat_receiver.py','install_chat_receiver.py'):
                source=source.replace("Path('/home/videoagent/video-automation')",f'Path({str(root)!r})')
            (self.kit/name).write_text(source)
        (self.kit/'KIT-SHA256.json').write_text(json.dumps({p.name:self.sha(p) for p in self.kit.iterdir()}))
        self.original={n:(root/n).read_bytes() for n in ('daily_core.py','daily_remote.py','runtime/production/readiness.json','runtime/production/generation-mode.json','runtime/production/activation.json')}
        self.previous={n:sys.modules.pop(n,None) for n in ('daily_core','helpers','helpers.daily')}
        def restore():
            for name,module in self.previous.items():
                if module is None:sys.modules.pop(name,None)
                else:sys.modules[name]=module
        self.addCleanup(restore)
        self.ns={'__name__':'fixture_installer','__file__':str(self.kit/'install_chat_receiver.py')}
        exec(compile((self.kit/'install_chat_receiver.py').read_text(),'fixture_installer','exec'),self.ns)
    def sha(self,p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
    def run_install(self):
        with contextlib.redirect_stdout(io.StringIO()):self.ns['main']()
    def assert_restored(self):
        for name,value in self.original.items():self.assertEqual((self.root/name).read_bytes(),value,name)
        for name in installer.RUNTIME_FILES:self.assertFalse((self.root/name).exists())
        self.assertFalse((self.root/'runtime/production/.chat-acceptance-key').exists())
    def test_install_passes_candidate_tests_and_receiver_self_check(self):
        self.run_install()
        ready=json.loads((self.root/'runtime/production/readiness.json').read_text())
        self.assertEqual(ready['checked_at'],'preserved_time')
        self.assertEqual(ready['chat_receiver_validation']['tests_run'],34)
        for name in (*installer.RUNTIME_FILES,'daily_core.py','daily_remote.py'):
            self.assertEqual(ready['code_sha256'][name],self.sha(self.root/name))
        for name in ('runtime/production/generation-mode.json','runtime/production/activation.json'):
            self.assertEqual((self.root/name).read_bytes(),self.original[name])
    def test_failed_regression_leaves_live_files_unchanged(self):
        path=self.root/'test_activation.py';path.write_text(path.read_text()+" def test_failure(self):self.fail('fixture')\n")
        with self.assertRaisesRegex(RuntimeError,'candidate_tests_failed'):self.run_install()
        self.assert_restored()
    def test_failed_readiness_write_restores_all_sources_and_removes_new_key(self):
        (self.root/'FAIL_READY').touch()
        with self.assertRaisesRegex(RuntimeError,'fixture_readiness_write_failed'):self.run_install()
        self.assert_restored()

if __name__=='__main__':unittest.main(verbosity=2)
