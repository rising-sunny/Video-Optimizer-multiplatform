"""Add strict owner-broker operations while preserving existing routes."""
import functools
from pathlib import Path
import workflow_common as c

SCHEMAS={
    'generation_workflow_diagnostics':{'operation','kind','job_id','channel','include_saved_response'},
    'generation_workflow_resume':{'operation','request_id','kind','job_id'},
    'generation_workflow_admin':{'operation','action','values'},
    'generation_workflow_poll':{'operation'},
    'generation_workflow_capabilities':{'operation'},
}

def guard_operation(op):
    if not c.busy() or not isinstance(op,str):return False
    readable={'generation_status','generation_media_meta','generation_media_read','generation_cached_media_link','generation_media_link_cache',
        'documentary_status','documentary_media_meta','documentary_media_read','publication_status',
        'generation_workflow_admin','generation_workflow_diagnostics','generation_workflow_capabilities',
        'generation_workflow_poll','generation_cancel','documentary_cancel','publication_cancel'}
    return op=='request_today' or (op not in readable and op.startswith(('generation_','documentary_','publication_')))

def install(cls,operations):
    if getattr(cls,'_workflow_installed',False):return
    operations.update(SCHEMAS)
    original_handle,original_start,original_status=cls.handle,cls.start,cls.status
    @functools.wraps(original_handle)
    def handle(self,request):
        from generation_service import denied,safe_error
        if not isinstance(request,dict):return original_handle(self,request)
        op=request.get('operation')
        if guard_operation(op):
            return denied('workflow_deployment_in_progress')
        if op not in SCHEMAS:return original_handle(self,request)
        if set(request)!=SCHEMAS[op]:return denied('invalid_generation_request')
        try:
            with self.lock:
                if op=='generation_workflow_capabilities':
                    value=dict(version=c.VERSION,maintenance=True,single_channel=True,automatic_recovery=True,native_ready=False)
                    try:
                        from generation_worker import preflight
                        preflight();value['native_ready']=True
                    except Exception as exc:value['native_error']=safe_error(exc)
                    return value
                if op=='generation_workflow_diagnostics':return c.diagnostics(request['kind'],request['job_id'],request['channel'],request['include_saved_response'])
                if op=='generation_workflow_admin':
                    if request['action'] not in ('inventory','source','deploy','status') or not isinstance(request['values'],dict):return denied('workflow_invalid_admin_action')
                    return c.admin_call(request['action'],**request['values'])
                from workflow_jobs import start,poll
                if op=='generation_workflow_poll':return poll(self)
                kind,ident=request['kind'],request['job_id']
                if kind not in ('catarsis','documentary') or not c.valid_id(ident):return denied('workflow_invalid_job')
                doc=getattr(self,'workflow_documentary',None)
                if self.active or (getattr(self,'publication',None) and self.publication.active) or (doc is not None and doc.active):return denied('another_manual_operation_is_running')
                return start(self if kind=='catarsis' else doc,kind,ident,request_id=request['request_id']) if kind=='catarsis' or doc is not None else denied('workflow_documentary_unavailable')
        except Exception as exc:return denied(safe_error(exc))
    @functools.wraps(original_start)
    def start(self,request):
        value=original_start(self,request)
        if value.get('state') in ('accepted','running','ready') and value.get('batch_id'):
            from workflow_jobs import enroll
            enroll('catarsis',value['batch_id'],state_root=self.state)
        return value
    @functools.wraps(original_status)
    def status(self,ident):
        value=original_status(self,ident)
        if value.get('batch_id') and c.valid_id(value['batch_id']):
            path=self.state/value['batch_id']/'workflow.json'
            value['workflow']=dict(version=c.VERSION,maintenance_tools=True,
                tracking=c.read(path) if path.is_file() else None)
            if value.get('state') in ('blocked','partial','interrupted'):
                value['workflow']['diagnostics']={}
                for channel,row in value.get('channels',{}).items():
                    if row.get('state')=='not_requested':continue
                    try:value['workflow']['diagnostics'][channel]=c.diagnostics('catarsis',ident,channel)
                    except (OSError,ValueError,RuntimeError):pass
        return value
    cls.handle,cls.start,cls.status=handle,start,status;cls._workflow_installed=True

def bind_documentary(parent):
    parent.generation.workflow_documentary=parent.documentary
    cls=type(parent.documentary)
    if getattr(cls,'_workflow_installed',False):return
    original=cls.start
    @functools.wraps(original)
    def start(self,request):
        if c.busy():return dict(state='blocked',error_code='workflow_deployment_in_progress',publication_allowed=False)
        value=original(self,request)
        if value.get('state') in ('accepted','running','ready') and value.get('job_id'):
            from workflow_jobs import enroll
            enroll('documentary',value['job_id'],state_root=self.state)
        return value
    cls.start=start;cls._workflow_installed=True
