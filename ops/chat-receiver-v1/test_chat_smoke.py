"""VPS installation smoke tests; fixtures never reach APIs or production jobs."""
import hashlib,json,tempfile,unittest,uuid
from pathlib import Path
from unittest.mock import patch
import chat_package as p
import chat_receiver as r
import daily_core as c
import daily_remote as remote

class ChatBridgeSmokeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.source=self.root/'source';self.source.mkdir()
        self.identity={'channel':p.CHANNELS[0],'date':'2026-10-31','request_id':str(uuid.uuid4()),'topic':'Test fixture','topic_key':'test-fixture'}
        marker=p.validate_identity(self.identity)
        for name in ('video.mp4','thumbnail.jpg','review/frame.jpg'):
            path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'fixture only')
        self.write('metadata.json',{'marker':marker,'youtube':{'title':'Fixture','description':marker,'tags':[]},'facebook':{'title':'Fixture','description':marker},'instagram':{'caption':marker}})
        self.review={'origin':'codex_chat','approved':True,'channel':self.identity['channel'],'date':self.identity['date'],'request_id':self.identity['request_id'],
            'video_sha256':p.digest(self.source/'video.mp4'),'review_reference':'fixture only','checks':{'fixture':True},'image_inputs':[{'path':'review/frame.jpg','sha256':p.digest(self.source/'review/frame.jpg')}]}
        self.write('chat-review.json',self.review)
        for name in ('music_credits.json','sources.json','asset-credits.json'):self.write(name,{'fixture_only':True})
        self.archive=self.root/'package.zip'
    def write(self,name,value):
        path=self.source/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value))
    def build(self):return p.build(self.source,self.archive,self.identity)
    def test_package_roundtrip(self):
        result=self.build();manifest=p.inspect_archive(self.archive,result['manifest_sha256'])
        self.assertEqual(manifest['files']['video.mp4']['sha256'],self.review['video_sha256'])
    def test_wrong_manifest_hash_rejected(self):
        self.build()
        with self.assertRaises(p.InvalidPackage):p.inspect_archive(self.archive,'0'*64)
    def test_no_other_channels_or_cli_evidence(self):
        for channel in ('mathrelaxing','the-books-wanderer'):
            with self.assertRaises(p.InvalidPackage):p.validate_identity(dict(self.identity,channel=channel))
        self.write('chat-review.json',dict(self.review,successful_agent_exit=True))
        with self.assertRaises(p.InvalidPackage):self.build()
    def test_unsafe_paths_and_secrets_rejected(self):
        for name in ('../video.mp4','approval.json','.transport.json','review/execute.py'):
            with self.assertRaises(p.InvalidPackage):p.safe_path(name)
        with self.assertRaises(p.InvalidPackage):p.no_secrets({'access_token':'fixture'})
    def test_existing_directory_and_missing_acceptance_rejected(self):
        source=self.root/'move';target=self.root/'existing';source.mkdir();target.mkdir()
        with self.assertRaises(p.InvalidPackage):r.rename_new(source,target)
        self.assertTrue(source.exists());self.assertTrue(target.exists())
        with self.assertRaises(p.InvalidPackage):r.receive(self.archive,'0'*64,False)
    def test_local_signature_detects_changed_payload(self):
        with patch.object(r,'ROOT',self.root):
            key=self.root/'runtime/production'/r.KEY_NAME;key.parent.mkdir(parents=True);key.write_bytes(b'k'*32);key.chmod(0o600)
            record=r.signed({'fixture':True});self.assertEqual(r.verified(record),{'fixture':True})
            record['payload']['fixture']=False
            with self.assertRaises(p.InvalidPackage):r.verified(record)
    def test_native_publisher_requires_separate_chat_authorization(self):
        self.write('vision-evidence.json',{'review_origin':'codex_chat'})
        job={'date':self.identity['date'],'channel':self.identity['channel'],'request_id':self.identity['request_id'],'scope':'production'}
        publisher=remote.Publisher({},self.source,job)
        with patch.object(remote,'approval',return_value={}),patch.object(remote,'publish_preflight',side_effect=AssertionError('network_forbidden')) as music:
            with self.assertRaisesRegex(c.Blocked,'chat_publication_not_authorized'):publisher.run()
            music.assert_not_called()
    def test_native_chat_approval_verifies_acceptance_without_cli_exit(self):
        with patch.object(r,'ROOT',self.root),patch.object(c,'ROOT',self.root):
            key=self.root/'runtime/production'/r.KEY_NAME;key.parent.mkdir(parents=True);key.write_bytes(b'k'*32);key.chmod(0o600)
            target=r.destination(c,self.identity['channel'],self.identity['date']);target.parent.mkdir(parents=True);self.source.rename(target);self.source=target
            video_hash=self.review['video_sha256']
            self.write('qa.json',{'technical_checks_passed':True,'sha256':video_hash})
            self.write('visual-review.json',{'approved':True,'video_sha256':video_hash})
            self.write('vision-evidence.json',{'review_origin':'codex_chat','video_sha256':video_hash,'image_inputs':self.review['image_inputs']})
            self.write('chat-manifest.json',{'fixture_only':True})
            approval={'scope':'production','channel':self.identity['channel'],'date':self.identity['date'],'video_sha256':video_hash,
                'artifacts':{path.relative_to(target).as_posix():p.digest(path) for path in target.rglob('*') if path.is_file()}}
            self.write('approval.json',approval)
            payload={'schema':r.ACCEPTANCE_SCHEMA,'acceptance':'operator_cli_manifest_sha256',**{k:self.identity[k] for k in ('channel','date','request_id')},
                'approval_sha256':p.digest(target/'approval.json'),'manifest_sha256':p.digest(target/'chat-manifest.json'),
                'review_sha256':p.digest(target/'chat-review.json'),'video_sha256':video_hash}
            self.write(r.RECEIPT_NAME,r.signed(payload))
            c.approval(target,self.identity['channel'],self.identity['date'])
            approval['scope']='changed';self.write('approval.json',approval)
            with self.assertRaises(c.Blocked):c.approval(target,self.identity['channel'],self.identity['date'])

if __name__=='__main__':unittest.main(verbosity=2)
