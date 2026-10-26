"""Durable local report queue and opt-in Notion publication. No model calls."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

from research_reports import build_report,project_data,safe_folder,signature
from tree_store import now

VERSION='2026-03-11'


def page_id(value):
    if not isinstance(value,str):raise ValueError('Notion 페이지 URL 또는 ID를 입력하세요.')
    value=value.strip()
    if '://' in value:
        url=urllib.parse.urlsplit(value)
        if url.scheme!='https' or not (url.hostname in {'notion.so','www.notion.so','notion.com','www.notion.com','app.notion.com'} or (url.hostname or '').endswith('.notion.site')):raise ValueError('Notion의 https 페이지 URL을 입력하세요.')
        value=urllib.parse.unquote(url.path).rstrip('/').rsplit('/',1)[-1]
    match=re.search(r'([a-fA-F0-9]{32}|[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12})$',value)
    if not match:raise ValueError('Notion 페이지 ID를 확인하세요.')
    return str(uuid.UUID(match.group(1)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class NotionError(ValueError):pass


class NotionAPI:
    def __init__(self,token,stop=None,guard=None):
        if not isinstance(token,str) or not 10<=len(token)<=1000 or any(ord(c)<33 or ord(c)>126 for c in token):raise ValueError('Notion 토큰을 확인하세요.')
        self.token=token;self.stop=stop or threading.Event();self.guard=guard;self.opener=urllib.request.build_opener(NoRedirect())

    def request(self,method,path,payload=None,content_type=None):
        if not re.fullmatch(r'/[A-Za-z0-9_/?=&%.-]+',path):raise ValueError('Invalid Notion endpoint')
        body=payload if isinstance(payload,bytes) else json.dumps(payload,ensure_ascii=False,allow_nan=False).encode() if payload is not None else None
        headers={'Authorization':'Bearer '+self.token,'Notion-Version':VERSION,'Content-Type':content_type or 'application/json'}
        request=urllib.request.Request('https://api.notion.com/v1'+path,data=body,method=method,headers=headers)
        for attempt in range(3):
            if self.guard and not self.guard():raise NotionError('Notion 연결이 변경되거나 해제되었습니다. 다시 동기화하세요.')
            if self.stop.is_set():raise NotionError('동기화가 중단되었습니다. 다시 동기화하면 이어서 확인합니다.')
            try:
                with self.opener.open(request,timeout=20) as response:return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code==429 and attempt<2:
                    try:delay=min(60,max(1,float(error.headers.get('Retry-After','2'))))
                    except ValueError:delay=2
                    self.stop.wait(delay);continue
                message={401:'Notion 토큰이 유효하지 않습니다.',403:'Notion 페이지의 읽기·삽입 권한을 확인하세요.',404:'Notion 페이지를 찾을 수 없습니다. 페이지의 연결 추가 및 URL을 확인하세요.',429:'Notion 요청 한도에 도달했습니다. 잠시 후 다시 동기화하세요.'}.get(error.code,'Notion 요청을 완료하지 못했습니다. HTTP '+str(error.code))
                raise NotionError(message) from None
            except (OSError,ValueError):raise NotionError('Notion 응답을 확인하지 못했습니다. 다시 동기화하면 게시 위치를 확인해 이어갑니다.') from None

    def children(self,identity):
        result=[];cursor=''
        while True:
            data=self.request('GET','/blocks/'+page_id(identity)+'/children?page_size=100'+('&start_cursor='+urllib.parse.quote(cursor,safe='') if cursor else ''))
            result.extend(data['results'])
            if not data.get('has_more'):return result
            cursor=data['next_cursor']

    def child_page(self,parent,title):
        found=[b for b in self.children(parent) if b.get('type')=='child_page' and b['child_page']['title']==title]
        if len(found)>1:raise NotionError('동일한 이름의 보고서 페이지가 여러 개입니다. Notion에서 중복 페이지를 정리한 뒤 다시 동기화하세요.')
        if found:return page_id(found[0]['id'])
        result=self.request('POST','/pages',dict(parent=dict(type='page_id',page_id=page_id(parent)),properties={'title':{'type':'title','title':[{'type':'text','text':{'content':title}}]}}))
        return page_id(result['id'])

    def upload(self,path,caption):
        content_type='image/png' if path.suffix=='.png' else 'text/markdown' if path.suffix=='.md' else 'application/json'
        if path.stat().st_size>5*1024*1024:raise NotionError('첨부 파일이 5MiB를 초과합니다. 원본은 로컬 보고서에 보존했습니다.')
        upload=self.request('POST','/file_uploads',dict(mode='single_part',filename=path.name,content_type=content_type));identity=page_id(upload['id'])
        boundary='BrainDance'+uuid.uuid4().hex
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{path.name}"\r\nContent-Type: {content_type}\r\n\r\n').encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        sent=self.request('POST','/file_uploads/'+identity+'/send',body,'multipart/form-data; boundary='+boundary)
        if sent.get('status')!='uploaded':raise NotionError('Notion 파일 업로드가 완료되지 않았습니다. 로컬 파일은 보존했습니다.')
        kind='image' if path.suffix=='.png' else 'file'
        return {'object':'block','type':kind,kind:{'type':'file_upload','file_upload':{'id':identity},'caption':rich(caption)}}


def rich(value):return [{'type':'text','text':{'content':value}}]


def blocks_for(record):
    blocks=[]
    for title,body in record['sections']:
        for chunk in chunks(title):blocks.append({'object':'block','type':'heading_2','heading_2':{'rich_text':rich(chunk)}})
        for chunk in chunks(body):blocks.append({'object':'block','type':'paragraph','paragraph':{'rich_text':rich(chunk)}})
    return blocks


def chunks(text):
    # 900 codepoints also fits the 2,000 UTF-16-unit limit for emoji.
    return [text[i:i+900] for i in range(0,len(text),900)] or [' ']


def block_signature(block):
    kind=block['type'];payload=block[kind]
    return (kind,''.join(v.get('plain_text',v.get('text',{}).get('content','')) for v in payload.get('rich_text',payload.get('caption',[]))))


class PublicationService:
    def __init__(self,store,autostart=True):
        self.store=store;self.root=Path(store.db_path).parent/'reports';self.private=Path(store.db_path).parent/'integrations'
        self.private.mkdir(mode=0o700,exist_ok=True);self.db=self.private/'notion.sqlite3';self.secret=self.private/'notion-credentials.json'
        self.lock=threading.RLock();self.execution_lock=threading.RLock();self.stop=threading.Event();self.active=None;self.last_auto=0
        with self.connect() as conn:
            conn.executescript('''
                CREATE TABLE IF NOT EXISTS links(project_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,auto_sync INTEGER NOT NULL,workspace TEXT NOT NULL,checked_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,project_id TEXT NOT NULL,digest TEXT NOT NULL,kind TEXT NOT NULL,parent_id TEXT NOT NULL,state TEXT NOT NULL,message TEXT NOT NULL,snapshot TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,page_id TEXT,page_url TEXT,UNIQUE(project_id,digest,kind,parent_id));
                CREATE TABLE IF NOT EXISTS reports(project_id TEXT NOT NULL,digest TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(project_id,digest));
            ''')
            conn.execute("UPDATE jobs SET state='queued',message='이전 동기화를 이어서 확인합니다.' WHERE state IN ('building','uploading','publishing')")
        os.chmod(self.db,0o600)
        self.thread=threading.Thread(target=self.loop,name='braindance-publications',daemon=True)
        if autostart:self.thread.start()

    @contextmanager
    def connect(self):
        conn=sqlite3.connect(self.db,timeout=15);conn.row_factory=sqlite3.Row
        try:
            with conn:yield conn
        finally:conn.close()

    def token(self):
        if not self.secret.exists():return ''
        return json.loads(self.secret.read_text()).get('token','')

    def configure(self,project_id,parent,token='',auto_sync=False):
        project_data(self.store,project_id);parent=page_id(parent)
        if type(auto_sync) is not bool:raise ValueError('자동 동기화 설정을 확인하세요.')
        token=token or self.token()
        if not token:
            if auto_sync:raise ValueError('토큰을 등록한 뒤 자동 동기화를 켜세요.')
            with self.connect() as conn:conn.execute('INSERT INTO links VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET parent_id=excluded.parent_id,auto_sync=0,workspace=excluded.workspace,checked_at=excluded.checked_at',(project_id,parent,0,'',''))
            return self.state(project_id)
        api=NotionAPI(token,self.stop);user=api.request('GET','/users/me');page=api.request('GET','/pages/'+parent)
        if page.get('archived') or page.get('in_trash'):raise ValueError('휴지통에 있는 Notion 페이지입니다.')
        with self.lock:
            fd,name=tempfile.mkstemp(prefix='.notion-',dir=self.private)
            try:
                with os.fdopen(fd,'w') as stream:json.dump(dict(token=token),stream);stream.flush();os.fsync(stream.fileno())
                os.replace(name,self.secret)
            finally:Path(name).unlink(missing_ok=True)
            with self.connect() as conn:
                conn.execute('INSERT INTO links VALUES(?,?,?,?,?) ON CONFLICT(project_id) DO UPDATE SET parent_id=excluded.parent_id,auto_sync=excluded.auto_sync,workspace=excluded.workspace,checked_at=excluded.checked_at',(project_id,parent,int(auto_sync),user.get('bot',{}).get('workspace_name') or user.get('name') or 'Notion',now()))
        return self.state(project_id)

    def disconnect(self):
        with self.lock,self.connect() as conn:
            self.secret.unlink(missing_ok=True);conn.execute('UPDATE links SET auto_sync=0')
            conn.execute("UPDATE jobs SET state='failed',message='Notion 연결이 해제되었습니다.',updated_at=? WHERE kind='notion' AND state='queued'",(now(),))
        return {'connected':False}

    def state(self,project_id):
        project_data(self.store,project_id)
        with self.connect() as conn:
            link=conn.execute('SELECT * FROM links WHERE project_id=?',(project_id,)).fetchone()
            jobs=[{k:v for k,v in dict(r).items() if k!='snapshot'} for r in conn.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 12',(project_id,))]
            report=conn.execute('SELECT * FROM reports WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(project_id,)).fetchone()
        record=json.loads(self.file(project_id,report['digest'],'manifest.json').read_text()) if report else None
        return dict(connected=bool(self.token()) and bool(link and link['checked_at']),link=dict(link) if link else None,jobs=jobs,report=record)

    def enqueue(self,project_id,publish=False,retry=True):
        data=project_data(self.store,project_id);digest=signature(data);kind='notion' if publish else 'local'
        with self.lock,self.connect() as conn:
            link=conn.execute('SELECT * FROM links WHERE project_id=?',(project_id,)).fetchone()
            if publish and (not link or not self.token()):raise ValueError('프로젝트의 Notion 페이지와 연결 토큰을 먼저 설정하세요.')
            parent=link['parent_id'] if publish else ''
            row=conn.execute('SELECT * FROM jobs WHERE project_id=? AND digest=? AND kind=? AND parent_id=?',(project_id,digest,kind,parent)).fetchone()
            if row:
                if row['state']=='failed' and retry:conn.execute("UPDATE jobs SET state='queued',message='재시도 대기',updated_at=? WHERE id=?",(now(),row['id']))
                return dict(id=row['id'],state='queued' if row['state']=='failed' and retry else row['state'])
            identity=str(uuid.uuid4());stamp=now()
            conn.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,project_id,digest,kind,parent,'queued','보고서 준비 대기',json.dumps(data,ensure_ascii=False,allow_nan=False),stamp,stamp,None,None))
            return dict(id=identity,state='queued')

    def update(self,identity,state,message,**fields):
        with self.connect() as conn:
            conn.execute('UPDATE jobs SET state=?,message=?,updated_at=?'+''.join(','+k+'=?' for k in fields)+' WHERE id=?',(state,message,now(),*fields.values(),identity))

    def process(self,job):
        project_data(self.store,job['project_id'])
        self.update(job['id'],'building','결과와 시각화를 정리합니다.')
        record=build_report(self.root,json.loads(job['snapshot']))
        with self.connect() as conn:conn.execute('INSERT OR IGNORE INTO reports VALUES(?,?,?)',(job['project_id'],job['digest'],record['created_at']))
        if job['kind']=='notion':
            token=self.token()
            if not token:raise ValueError('Notion 연결 토큰을 설정하세요.')
            api=NotionAPI(token,self.stop,guard=lambda:self.token()==token)
            self.update(job['id'],'publishing','Notion 보고서 페이지를 확인합니다.')
            parent=api.child_page(job['parent_id'],('BrainDance · '+record['title'])[:160]+' · '+job['project_id'][:8])
            identity=api.child_page(parent,'결과 보고 · '+job['digest'][:12])
            url='https://www.notion.so/'+identity.replace('-','')
            self.update(job['id'],'uploading','그래프와 결과 파일을 첨부합니다.',page_id=identity,page_url=url)
            blocks=blocks_for(record)
            files=[(c['file'],c['title']+' · '+c['file']) for c in record['charts']]+[('report.md','전체 연구 보고서'),('results.json','보고서에 사용한 측정값과 논문 근거')]
            expected=[block_signature(b) for b in blocks]+[('image' if name.endswith('.png') else 'file',caption) for name,caption in files]
            existing=api.children(identity)
            if len(existing)>len(expected) or [block_signature(b) for b in existing]!=expected[:len(existing)]:raise ValueError('Notion 보고서에 수동 변경이 있습니다. 원본을 보존하기 위해 덮어쓰기를 중단했습니다.')
            offset=len(existing)
            while offset<len(blocks):
                batch=[];size=0
                for b in blocks[offset:offset+80]:
                    encoded=len(json.dumps(b,ensure_ascii=False).encode())
                    if size+encoded>350000:break
                    batch.append(b);size+=encoded
                project_data(self.store,job['project_id'])
                api.request('PATCH','/blocks/'+identity+'/children',dict(children=batch));offset+=len(batch)
            for position,(name,caption) in enumerate(files,len(blocks)):
                if position<len(existing):continue
                project_data(self.store,job['project_id'])
                if not self.token():raise ValueError('Notion 연결이 해제되었습니다.')
                b=api.upload(self.file(job['project_id'],job['digest'],name),caption)
                api.request('PATCH','/blocks/'+identity+'/children',dict(children=[b]))
            self.update(job['id'],'completed','Notion에 결과와 시각화를 정리했습니다.')
        else:self.update(job['id'],'completed','보고서와 시각화를 저장했습니다.')
        # Publication receipts belong to the same project stream; they are not
        # inputs to the report fingerprint, avoiding an automatic-sync loop.
        with self.store._connect() as conn:
            root=conn.execute('SELECT n.id FROM nodes n JOIN node_projects p ON p.node_id=n.id WHERE p.project_id=? AND n.parent_id IS NULL',(job['project_id'],)).fetchone()
            if root:conn.execute('INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?)',('publication:'+job['id'],root['id'],'publication','Notion 결과 정리 완료' if job['kind']=='notion' else '결과 보고서·시각화 생성 완료',url if job['kind']=='notion' else f"시각화 {len(record['charts'])}개 · 결과 탭에서 확인할 수 있습니다.",now()))

    def tick(self):
        with self.connect() as conn:links=[dict(r) for r in conn.execute('SELECT * FROM links WHERE auto_sync=1')]
        if not self.token():return
        for link in links:
            try:self.enqueue(link['project_id'],publish=True,retry=False)
            except (ValueError,KeyError):pass

    def loop(self):
        while not self.stop.is_set():
            try:
                if time.monotonic()-self.last_auto>30:self.last_auto=time.monotonic();self.tick()
                with self.connect() as conn:row=conn.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at LIMIT 1").fetchone()
                if row:
                    with self.execution_lock:
                        self.active=row['project_id']
                        try:self.process(dict(row))
                        except Exception as error:
                            # Never persist request bodies, credentials, or untrusted remote errors.
                            message=str(error) if isinstance(error,(NotionError,ValueError)) else '보고서 처리 중 오류가 발생했습니다. 로컬 원본은 보존했습니다.'
                            self.update(row['id'],'failed',message[:1000])
                            import traceback
                            from research_reports import clean
                            detail=traceback.format_exc();secret=self.token()
                            if secret:detail=detail.replace(secret,'[credential removed]')
                            fd=os.open(self.private/'notion-errors.log',os.O_CREAT|os.O_APPEND|os.O_WRONLY,0o600)
                            with os.fdopen(fd,'a') as stream:stream.write(now()+' '+row['id']+'\n'+clean(detail)+'\n')
                        finally:self.active=None
                    continue
            except (OSError,sqlite3.Error,ValueError):pass
            self.stop.wait(.5)

    def file(self,project_id,digest,name):
        project_data(self.store,project_id)
        folder=safe_folder(self.root,project_id,digest)
        if name not in {'report.md','results.json','manifest.json'} and not re.fullmatch(r'metric-\d{3}-\d{3}\.png',name):raise ValueError('보고서 파일을 찾을 수 없습니다.')
        path=folder/name
        if not path.is_file() or path.is_symlink():raise ValueError('보고서 파일을 찾을 수 없습니다.')
        return path

    def close(self):
        self.stop.set()
        if self.thread.is_alive():self.thread.join(timeout=2)

    def forget(self,project_id):
        with self.connect() as conn:
            for table in ['links','jobs','reports']:conn.execute('DELETE FROM '+table+' WHERE project_id=?',(project_id,))
