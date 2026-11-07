"""Exercise the actual installed helper's receipt branch, not a mock of its cache."""
import ast
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'modules'))
import workflow_common as c
from workflow_presentation import fresh_render

class NativeReceipt(unittest.TestCase):
    def test_actual_native_receipt_cache_is_reconciled_before_a_fresh_render(self):
        fixture=Path(__file__).with_name('native-render-project.txt')
        if not fixture.exists():fixture=Path(__file__).resolve().parents[1]/'observed/native_render_project.py'
        source=fixture.read_text();tree=ast.parse(source)
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);job=root/'job';job.mkdir();package=root/'package';package.mkdir()
            runtime=root/'runtime';(runtime/'music').mkdir(parents=True)
            music=runtime/'music/track.mp3';music.write_bytes(b'verified music')
            photo=job/'photo.png';photo.write_bytes(b'verified source')
            c.write(package/'music.json',dict(tracks=[dict(title='Track',filename='track.mp3',sha256=c.digest(music))]))
            project=dict(media=[dict(file=str(photo))],sequence=[dict(kind='media',media=0,seconds=3)],music_title='Track',style={})
            calls=[]
            def render(shots,path,**kwargs):
                calls.append(kwargs);Path(path).write_bytes(('new pixels '+str(len(calls))).encode())
            editor=types.SimpleNamespace(build_shots=lambda *_:([object()],dict(break_=None)),render=render)
            editor.build_shots=lambda *_:([object()],{'break':None})
            package_module=types.ModuleType('catharsis');package_module.catharsis_editor=editor
            timeline=types.ModuleType('catharsis.catharsis_timeline');timeline.missing_slots=lambda *_:[]
            def qa(video,directory,smoke=False):
                data=dict(sha256=c.digest(video),technical_checks_passed=True);c.write(directory/'qa.json',data);return data
            namespace=dict(serialized=lambda f:f,inside=lambda p:Path(p),Path=Path,ROOT=root,REPO=root,
                RUNTIME=runtime,PACKAGE=package,load=c.read,digest=c.digest,atomic=c.write,hashlib=hashlib,json=json,sys=sys,qa=qa)
            exec(compile(tree,str(fixture),'exec'),namespace)
            video=job/'video.mp4'
            with patch.dict(sys.modules,{'catharsis':package_module,'catharsis.catharsis_timeline':timeline,
                'catarsis_style':types.SimpleNamespace(video_digest=lambda p:Path(p).read_bytes())}):
                self.assertFalse(namespace['render_project'](project,job,smoke=True)['reused'])
                old_receipt=(job/'receipt.json').read_bytes()
                self.assertTrue(namespace['render_project'](project,job,smoke=True)['reused'])
                self.assertEqual(len(calls),1)
                held=fresh_render(job,lambda:namespace['render_project'](project,job,smoke=True))
                self.assertEqual(len(calls),2)
                self.assertEqual(held.read_bytes(),b'new pixels 1')
                self.assertEqual((job/'workflow-prior-receipt.json').read_bytes(),old_receipt)
                self.assertEqual(c.read(job/'receipt.json')['video_sha256'],c.digest(video))

if __name__=='__main__':unittest.main()
