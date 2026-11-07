import copy
from datetime import datetime,timezone,timedelta
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

import publish_single as s


class Prepared(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.generation=self.root/'generation';self.jobs=self.root/'jobs'
        self.state=self.generation/s.BATCH;self.job=self.jobs/s.BATCH/s.CHANNEL
        self.state.mkdir(parents=True);self.job.mkdir(parents=True)
        self.task=dict(batch_id=s.BATCH,operation='generate_single_only',requested_channels=[s.CHANNEL],
            topics={s.CHANNEL:'Curie WWI'},publication_allowed=False,date='2026-11-07')
        self.metadata=dict(marker='VO:manual:'+s.BATCH+':'+s.CHANNEL,public_marker=False)
        self.native_job=dict(date=self.task['date'],channel=s.CHANNEL,topic=self.task['topics'][s.CHANNEL],
            scope='production',manual_batch=s.BATCH,generation_only=True,publication_allowed=False)
        for name,value in [('job.json',self.native_job),('metadata.json',self.metadata),('approval.json',{'scope':'production'})]:s.write(self.job/name,value)
        (self.job/'video.mp4').write_bytes(b'approved bytes');(self.job/'thumbnail.jpg').write_bytes(b'approved thumbnail')
        self.approval=s.sha(self.job/'approval.json');self.video=s.sha(self.job/'video.mp4')
        self.status=dict(state='ready',channels={s.CHANNEL:dict(state='ready',approval_sha256=self.approval,
            files={'video':{'sha256':self.video},'thumbnail':{'sha256':s.sha(self.job/'thumbnail.jpg')}})})
        s.write(self.state/'request.json',self.task);s.write(self.state/'status.json',self.status)
        self.calls=[];self.core=types.SimpleNamespace(approval=lambda *a:self.calls.append(a))
        self.pin1=patch.object(s,'APPROVAL',self.approval);self.pin1.start();self.addCleanup(self.pin1.stop)
        self.pin2=patch.object(s,'VIDEO',self.video);self.pin2.start();self.addCleanup(self.pin2.stop)
    def prepared(self):return s.prepared(self.core,self.generation,self.jobs)
    def test_binds_exact_approved_single_video_and_metadata_without_writes(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        manifest=self.prepared()
        self.assertEqual(manifest['channels'],[s.CHANNEL]);self.assertEqual(manifest['platforms'],list(s.PLATFORMS))
        self.assertEqual(manifest['pins']['video.mp4'],self.video);self.assertEqual(len(self.calls),1)
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
    def test_wrong_channel_pair_not_ready_or_superseded_is_rejected(self):
        for change in ('pair','other','not_ready','superseded'):
            task,status=copy.deepcopy(self.task),copy.deepcopy(self.status)
            if change=='pair':task.update(operation='generate_only',requested_channels=[s.CHANNEL,'stunning-revelations'])
            if change=='other':task['topics']={'stunning-revelations':'Curie'}
            if change=='not_ready':status['state']='blocked'
            if change=='superseded':s.write(self.state/'superseded.json',{})
            s.write(self.state/'request.json',task);s.write(self.state/'status.json',status)
            with self.subTest(change=change),self.assertRaises(RuntimeError):self.prepared()
            (self.state/'superseded.json').unlink(missing_ok=True)
    def test_changed_media_approval_thumbnail_or_job_is_rejected(self):
        for name in s.PINNED:
            path=self.job/name;old=path.read_bytes();path.write_bytes(old+b'changed')
            with self.subTest(name=name),self.assertRaises((RuntimeError,ValueError)):self.prepared()
            path.write_bytes(old)


class Guard(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.clock=datetime(2026,11,7,12,tzinfo=timezone.utc)
        self.manifest={'pins':{'video.mp4':s.VIDEO}}
        for n in ('instagram_recovery.py','publication_transport.py'):(self.root/n).write_text(n)
        self.native=types.SimpleNamespace(CONNECTOR_SOURCES=(),controls=lambda:{'PAUSED':'saved'})
        self.auth=dict(operation='publish_prepared_single',request_id=s.REQUEST,channels=[s.CHANNEL],
            platforms=list(s.PLATFORMS),include_tiktok_drafts=False,created_at=self.clock.isoformat(),
            expires_at=(self.clock+timedelta(hours=2)).isoformat(),controls=self.native.controls(),
            publisher_sha256=s.sha(s.__file__),manifest=self.manifest,
            connector_sha256={n:s.sha(self.root/n) for n in ('instagram_recovery.py','publication_transport.py')})
        self.path=self.root/'auth.json';s.write(self.path,self.auth)
        self.controller=s.Controller(object(),object(),self.native,self.auth,self.path,jobs=self.root,
            generation=self.root,state=self.root,clock=lambda:self.clock)
        self.preflight=[]
        gw=types.ModuleType('generation_worker');gw.preflight=lambda:self.preflight.append(True)
        self.patches=[patch.object(s,'ROOT',self.root),patch.dict(sys.modules,{'generation_worker':gw}),patch.object(s,'prepared',return_value=self.manifest)]
        for p in self.patches:p.start();self.addCleanup(p.stop)
    def test_authorization_and_source_bound_guard_accepts_only_the_selected_scope(self):
        self.controller.guard();self.assertEqual(self.preflight,[True])
    def test_rejects_expired_auth_controls_or_changed_source_before_mutation(self):
        for change in ('expired','controls','source','channel','tiktok','auth_file','video'):
            auth=copy.deepcopy(self.auth)
            if change=='expired':self.controller.clock=lambda:self.clock+timedelta(hours=3)
            if change=='controls':auth['controls']={}
            if change=='source':auth['connector_sha256']['instagram_recovery.py']='0'*64
            if change=='channel':auth['channels'].append('stunning-revelations')
            if change=='tiktok':auth['include_tiktok_drafts']=True
            if change=='video':auth['manifest']={}
            self.controller.auth=auth
            if change=='auth_file':s.write(self.path,{'tampered':True})
            with self.subTest(change=change),self.assertRaises(RuntimeError):self.controller.guard()
            self.controller.clock=lambda:self.clock;self.controller.auth=self.auth;s.write(self.path,self.auth)


class Transport(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.folder=self.root/s.BATCH/s.CHANNEL;self.folder.mkdir(parents=True)
        self.job={'channel':s.CHANNEL,'date':'2026-11-07'};s.write(self.folder/'job.json',self.job)
        self.events=[];self.records={};outer=self
        class Blocked(RuntimeError):pass
        class Base:
            def __init__(p,policy,directory,job,dry=False):
                p.directory,p.job,p.dry=Path(directory),job,dry;p.meta={'public_marker':False}
            def mark(p,network,**values):outer.records.setdefault(network,{}).update(values)
            def youtube(p,service):
                if not outer.records.get('youtube',{}).get('video_id'):
                    p.mutate(lambda:outer.events.append('new_youtube_upload'))
                    p.mark('youtube',video_id='abcdefghijk')
                p.mark('youtube',state='published')
            def facebook(p,token):
                if not outer.records.get('facebook',{}).get('video_id'):
                    p.mutate(lambda:outer.events.append('new_facebook_upload'))
                    p.mark('facebook',video_id='123')
                p.mark('facebook',state='published')
            def instagram(p,identity):
                if not outer.records.get('instagram',{}).get('media_id'):
                    p.mutate(lambda:outer.events.append('new_instagram_upload'))
                    p.mark('instagram',media_id='456')
                p.mark('instagram',state='published')
        def identity(channel):outer.events.append('identity_'+channel);return object(),object(),object()
        def music(directory,channel,dry=False):outer.events.append('music_'+str(dry));return True
        self.core=types.SimpleNamespace(Blocked=Blocked,receipt=lambda path:{'platforms':self.records},approval=lambda *a:True)
        self.remote=types.SimpleNamespace(Publisher=Base,identities=identity,publish_preflight=music)
        self.controller=s.Controller.__new__(s.Controller)
        self.controller.core,self.controller.remote,self.controller.jobs=self.core,self.remote,self.root
        self.controller.guard=lambda:self.events.append('guard')
        self.controller.job=lambda:(self.folder,self.job)
        fake=types.ModuleType('instagram_recovery')
        fake.publish_or_recover=lambda p,i,c,original:original()
        p=patch.dict(sys.modules,{'instagram_recovery':fake});p.start();self.addCleanup(p.stop)
    def publisher(self,dry=False):return self.controller.publisher()({},self.folder,self.job,dry=dry)
    def test_dry_preflight_has_no_social_writes_and_is_facts_only(self):
        result=self.publisher(True).run()
        self.assertEqual(result['remote_mutations'],0);self.assertEqual(result['profile'],s.CHANNEL)
        self.assertEqual(self.records,{})
        self.assertNotIn('stunning-revelations',' '.join(self.events))
    def test_uploads_each_selected_network_once_and_skips_completed_receipts(self):
        self.publisher().run();self.publisher().run()
        for network in s.PLATFORMS:self.assertEqual(self.events.count('new_'+network+'_upload'),1)
        self.assertEqual(set(self.records),set(s.PLATFORMS))
    def test_known_youtube_id_is_reused_and_ambiguous_creation_is_blocked(self):
        self.records['youtube']={'video_id':'abcdefghijk','intent':'upload_chunk'}
        self.publisher().run();self.assertNotIn('new_youtube_upload',self.events)
        self.records['youtube']={'intent':'create_private'}
        self.publisher().run()
        self.assertNotIn('new_youtube_upload',self.events)
        self.assertEqual(self.records['youtube']['reason_code'],'youtube_create_ambiguous_reconcile_before_retry')
    def test_wrong_channel_and_dry_mutation_are_rejected(self):
        p=self.publisher();p.job=dict(self.job,channel='stunning-revelations')
        with self.assertRaises(RuntimeError):p.run()
        with self.assertRaisesRegex(RuntimeError,'dry_run_mutation'):self.publisher(True).mutate(lambda:None)
    def test_pending_receipts_are_not_reported_as_complete(self):
        native=types.SimpleNamespace(public_receipts=lambda jobs,batch:{'complete':False,'channels':{
            s.CHANNEL:{n:{'state':'published' if n!='instagram' else 'uploading'} for n in s.PLATFORMS},
            'stunning-revelations':{n:{'state':'not_started'} for n in s.PLATFORMS}}})
        result=s.scoped_receipts(native,self.root)
        self.assertFalse(result['complete']);self.assertEqual(set(result['channels']),{s.CHANNEL})

    def test_identity_failure_during_dry_preflight_prevents_every_social_write(self):
        self.controller.native=types.SimpleNamespace(public_receipts=lambda *a:{'channels':{s.CHANNEL:{n:{'state':'not_started'} for n in s.PLATFORMS}}})
        self.remote.identities=lambda channel:(_ for _ in ()).throw(self.core.Blocked('instagram_identity_mismatch'))
        rules=types.ModuleType('platform_rules');rules.preflight=lambda folder:True
        original=s.read
        def read(path):
            if Path(path).name=='activation-policy.json':return {}
            return original(path)
        with patch.dict(sys.modules,{'platform_rules':rules}),patch.object(s,'read',side_effect=read):
            with self.assertRaisesRegex(self.core.Blocked,'identity_mismatch'):self.controller.run()
        self.assertEqual(self.records,{})
        self.assertFalse(any(e.startswith('new_') for e in self.events))

    def test_facebook_finish_400_reconciles_existing_id_without_another_upload(self):
        attempts=[]
        def facebook(p,token):
            attempts.append(True)
            if len(attempts)==1:
                p.mark('facebook',video_id='123',finish_intent=True,state='uploading')
                raise self.core.Blocked('graph_http_400_code_100')
            self.assertEqual(self.records['facebook']['video_id'],'123')
            p.mark('facebook',state='published',reason_code=None)
        self.remote.Publisher.facebook=facebook
        self.controller.native=types.SimpleNamespace(public_receipts=lambda *a:{'channels':{s.CHANNEL:{
            n:dict(state=self.records.get(n,{}).get('state','not_started'),error_code=self.records.get(n,{}).get('reason_code'))
            for n in s.PLATFORMS}}})
        rules=types.ModuleType('platform_rules');rules.preflight=lambda folder:True
        original=s.read
        def read(path):
            return {} if Path(path).name=='activation-policy.json' else original(path)
        with patch.dict(sys.modules,{'platform_rules':rules}),patch.object(s,'read',side_effect=read),patch.object(s.time,'sleep'):
            result=self.controller.run()
        self.assertTrue(result['complete']);self.assertEqual(len(attempts),2)
        self.assertNotIn('new_facebook_upload',self.events)

class Inspection(unittest.TestCase):
    def test_inspection_does_not_authorize_or_call_a_publisher(self):
        with patch.object(s,'initialize',return_value=(object(),object(),object())),patch.object(s,'prepared',return_value={}),patch.object(s,'write',side_effect=AssertionError('write')),patch.object(s,'scoped_receipts',side_effect=AssertionError('receipt write')):
            result=s.execute(False)
        self.assertEqual(result['state'],'checked');self.assertEqual(result['publication'],'not_requested')

    def test_repeated_claim_returns_same_saved_ids_without_starting_a_new_publisher(self):
        with tempfile.TemporaryDirectory() as name:
            root=Path(name);folder=root/s.BATCH;folder.mkdir()
            (folder/(s.REQUEST+'.claimed')).write_text('already claimed')
            s.write(folder/'status.json',{'state':'pending'})
            receipt=dict(complete=False,channels={s.CHANNEL:{'youtube':{'state':'private_uploaded','video_id':'abcdefghijk'}}})
            with patch.object(s,'STATE',root),patch.object(s,'initialize',return_value=(object(),object(),object())),patch.object(s,'prepared',return_value={}),patch.object(s,'scoped_receipts',return_value=receipt),patch.object(s,'Controller',side_effect=AssertionError('new publisher')):
                result=s.execute(True)
            self.assertEqual(result['channels'][s.CHANNEL]['youtube']['video_id'],'abcdefghijk')
            self.assertEqual(result['state'],'pending')

if __name__=='__main__':unittest.main()
