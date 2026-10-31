import hashlib,importlib.util,json,stat,tempfile,unittest,uuid,warnings,zipfile
from pathlib import Path
from unittest.mock import patch
import chat_package as p

class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.source=self.base/'source';self.source.mkdir()
        self.archive=self.base/'delivery.zip'
        self.identity={'channel':p.CHANNELS[0],'date':'2026-10-31','request_id':str(uuid.uuid4()),'topic':'Fixture history','topic_key':'fixture-history'}
        self.marker=p.validate_identity(self.identity)
        self.files={'video.mp4':b'fixture video only','thumbnail.jpg':b'fixture thumbnail','review/frame.jpg':b'fixture frame'}
        for name,data in self.files.items():
            path=self.source/name;path.parent.mkdir(exist_ok=True,parents=True);path.write_bytes(data)
        self.metadata={'marker':self.marker,'youtube':{'title':'Fixture','description':self.marker,'tags':['fixture']},'facebook':{'title':'Fixture','description':self.marker},'instagram':{'caption':self.marker}}
        self.review={'origin':'codex_chat','approved':True,'channel':self.identity['channel'],'date':self.identity['date'],
                     'request_id':self.identity['request_id'],'video_sha256':p.digest(self.source/'video.mp4'),
                     'review_reference':'test fixture; no real review asserted','checks':{'fixture_only':True},
                     'image_inputs':[{'path':'review/frame.jpg','sha256':p.digest(self.source/'review/frame.jpg')}]}
        self.write_json('metadata.json',self.metadata);self.write_json('chat-review.json',self.review)
        self.write_json('music_credits.json',{'provider':'manifest','license':'fixture only'})
        self.write_json('sources.json',[{'source':'fixture only'}])
        self.write_json('asset-credits.json',[{'credit':'fixture only'}])
    def write_json(self,name,value):
        (self.source/name).write_text(json.dumps(value))
    def build(self):return p.build(self.source,self.archive,self.identity)
    def check(self,result):return p.inspect_archive(self.archive,result['manifest_sha256'])
    def rewrite_archive(self,transform):
        with zipfile.ZipFile(self.archive) as archive:
            members=[(info,archive.read(info.filename)) for info in archive.infolist()]
        with zipfile.ZipFile(self.archive,'w') as archive:
            for info,data in transform(members):archive.writestr(info,data)
    def test_valid_roundtrip_preserves_identity_and_hashes(self):
        manifest=self.check(self.build())
        self.assertEqual(manifest['channel'],self.identity['channel'])
        self.assertEqual(manifest['files']['video.mp4']['sha256'],p.digest(self.source/'video.mp4'))
    def test_requires_operator_manifest_hash(self):
        self.build()
        with self.assertRaisesRegex(p.InvalidPackage,'manifest_hash_mismatch'):
            p.inspect_archive(self.archive,'0'*64)
    def test_tampered_video_rejected(self):
        result=self.build()
        self.rewrite_archive(lambda members:[(info,b'changed video only' if info.filename=='video.mp4' else data) for info,data in members])
        with self.assertRaises(p.InvalidPackage):self.check(result)
    def test_source_symlinks_rejected(self):
        (self.source/'review/link.jpg').symlink_to(self.source/'thumbnail.jpg')
        with self.assertRaisesRegex(p.InvalidPackage,'symlinks_forbidden'):self.build()
    def test_path_traversal_and_absolute_paths_rejected(self):
        for name in ('../video.mp4','/tmp/video.mp4','review/../../x.jpg','review\\x.jpg','review//x.jpg'):
            with self.subTest(name=name),self.assertRaises(p.InvalidPackage):p.safe_path(name)
    def test_executable_and_transport_files_rejected(self):
        for name in ('review/run.py','.transport.json','approval.json','publication.json','job.json','vision-evidence.json','media/access_token.json'):
            with self.subTest(name=name),self.assertRaises(p.InvalidPackage):p.safe_path(name)
    def test_json_tokens_and_signed_urls_rejected(self):
        for data in ({'access_token':'fixture'},{'x':'https://example.invalid/a?signature=fixture'}):
            self.metadata['private']=data;self.write_json('metadata.json',self.metadata)
            with self.assertRaises(p.InvalidPackage):self.build()
    def test_other_channels_not_accepted(self):
        for channel in ('mathrelaxing','the-books-wanderer'):
            with self.subTest(channel=channel),self.assertRaisesRegex(p.InvalidPackage,'channel_not_allowed'):
                p.validate_identity(dict(self.identity,channel=channel))
    def test_missing_or_failed_review_not_accepted(self):
        for changes in ({'approved':False},{'checks':{}},{'checks':{'visual':None}},{'review_reference':''}):
            self.write_json('chat-review.json',dict(self.review,**changes))
            with self.subTest(changes=changes),self.assertRaises(p.InvalidPackage):self.build()
    def test_cli_evidence_cannot_be_fabricated(self):
        self.write_json('chat-review.json',dict(self.review,successful_agent_exit=True))
        with self.assertRaisesRegex(p.InvalidPackage,'cli_evidence_not_allowed'):self.build()
    def test_review_bound_to_video_and_images(self):
        for changes in ({'video_sha256':'0'*64},{'image_inputs':[{'path':'review/frame.jpg','sha256':'0'*64}]}):
            self.write_json('chat-review.json',dict(self.review,**changes))
            with self.assertRaises(p.InvalidPackage):self.build()
    def test_platform_marker_and_credits_not_truncated(self):
        self.metadata['instagram']['caption']=self.marker+'x'*2200
        self.write_json('metadata.json',self.metadata)
        with self.assertRaisesRegex(p.InvalidPackage,'caption_too_long'):self.build()
        self.metadata['instagram']['caption']='no marker';self.write_json('metadata.json',self.metadata)
        with self.assertRaisesRegex(p.InvalidPackage,'marker_mismatch'):self.build()
    def test_existing_archive_never_overwritten(self):
        self.build();before=p.digest(self.archive)
        with self.assertRaisesRegex(p.InvalidPackage,'archive_already_exists'):self.build()
        self.assertEqual(p.digest(self.archive),before)
    def test_duplicate_json_keys_rejected(self):
        with self.assertRaisesRegex(p.InvalidPackage,'duplicate_json_key'):
            p.strict_json('{"approved":false,"approved":true}')
    def test_package_size_bound(self):
        with patch.object(p,'MAX_TOTAL',1),self.assertRaisesRegex(p.InvalidPackage,'package_too_large'):self.build()
    def test_unlisted_archive_member_rejected(self):
        result=self.build()
        info=zipfile.ZipInfo('review/extra.jpg');info.external_attr=(stat.S_IFREG|0o600)<<16
        self.rewrite_archive(lambda members:members+[(info,b'extra')])
        with self.assertRaisesRegex(p.InvalidPackage,'unlisted_or_missing_members'):self.check(result)
    def test_zip_symlink_rejected(self):
        result=self.build()
        def alter(members):
            for info,_ in members:
                if info.filename=='thumbnail.jpg':info.external_attr=(stat.S_IFLNK|0o777)<<16
            return members
        self.rewrite_archive(alter)
        with self.assertRaisesRegex(p.InvalidPackage,'non_regular_archive_member'):self.check(result)

if __name__=='__main__':unittest.main(verbosity=2)
