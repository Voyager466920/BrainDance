"""Durable local report queue and opt-in Notion publication. No model calls."""
from contextlib import contextmanager
from datetime import datetime
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
from zoneinfo import ZoneInfo

from research_reports import build_report,project_data,safe_folder,signature,quiescent
from tree_store import now

VERSION='2026-03-11'
DATABASE_TITLE='BrainDance 연구 기록'
DATABASE_PROPERTIES={'제목':{'title':{}},'날짜':{'date':{}},'프로젝트':{'rich_text':{}},'측정 상태':{'select':{'options':[{'name':'측정 전','color':'gray'},{'name':'측정 있음','color':'green'},{'name':'실패','color':'red'}]}},'실험 수':{'number':{}},'정상 측정':{'number':{}},'실행 시간(초)':{'number':{'format':'number'}},'보고서 키':{'rich_text':{}}}


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


class NotionError(ValueError):
    def __init__(self,message,retryable=False):
        super().__init__(message);self.retryable=retryable


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
                message={401:'Notion 토큰이 유효하지 않습니다.',403:'Notion 페이지의 읽기·삽입 권한을 확인하세요.',404:'Notion에서 페이지에 접근하지 못했습니다. URL이 맞아도 해당 페이지의 ··· → 연결 추가에서 토큰을 발급한 연결을 추가해야 합니다. 같은 워크스페이스인지도 확인하세요.',429:'Notion 요청 한도에 도달했습니다. 잠시 후 다시 동기화하세요.'}.get(error.code,'Notion 요청을 완료하지 못했습니다. HTTP '+str(error.code))
                raise NotionError(message,retryable=error.code in {409,429,500,502,503,504,529}) from None
            except (OSError,ValueError):raise NotionError('Notion 응답을 확인하지 못했습니다. 게시 위치를 확인해 자동으로 이어갑니다.',retryable=True) from None

    def children(self,identity):
        result=[];cursor=''
        while True:
            data=self.request('GET','/blocks/'+page_id(identity)+'/children?page_size=100'+('&start_cursor='+urllib.parse.quote(cursor,safe='') if cursor else ''))
            for block in data['results']:
                if block.get('type')=='table' and block.get('has_children') and 'children' not in block['table']:block['table']['children']=self.children(block['id'])
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

    def research_database(self,parent):
        """Reconcile by parent/name after an uncertain create, never blindly duplicate."""
        matches=[b for b in self.children(parent) if b.get('type')=='child_database' and b['child_database']['title']==DATABASE_TITLE]
        if len(matches)>1:raise NotionError('같은 이름의 연구 데이터베이스가 여러 개입니다. 게시 대상을 먼저 확인하세요.')
        if matches:database=self.request('GET','/databases/'+page_id(matches[0]['id']))
        else:database=self.request('POST','/databases',dict(parent=dict(type='page_id',page_id=parent),title=rich(DATABASE_TITLE),is_inline=True,initial_data_source=dict(properties=DATABASE_PROPERTIES)))
        identity=page_id(database['id']);sources=database.get('data_sources',[])
        if len(sources)!=1:raise NotionError('연구 데이터베이스의 데이터 소스가 하나가 아닙니다. 기존 내용을 보존했습니다.')
        source_id=page_id(sources[0]['id']);source=self.request('GET','/data_sources/'+source_id);properties=source['properties']
        for name,definition in DATABASE_PROPERTIES.items():
            if name not in properties or properties[name].get('type')!=next(iter(definition)):raise NotionError('같은 이름의 데이터베이스 구조가 BrainDance 연구 기록과 다릅니다. 기존 내용을 보존했습니다.')
        views=[];cursor=''
        while True:
            data=self.request('GET','/views?database_id='+identity+('&start_cursor='+urllib.parse.quote(cursor,safe='') if cursor else ''))
            views.extend(self.request('GET','/views/'+page_id(v['id'])) for v in data['results'])
            if not data.get('has_more'):break
            cursor=data['next_cursor']
        visible=[dict(property_id=properties[name]['id'],visible=name!='보고서 키') for name in DATABASE_PROPERTIES]
        configs=[('날짜별 기록','table',dict(type='table',properties=visible,wrap_cells=True)),('달력','calendar',dict(type='calendar',date_property_id=properties['날짜']['id'],view_range='month',properties=visible))]
        for name,kind,config in configs:
            found=[v for v in views if v.get('name')==name]
            if len(found)>1 or found and found[0].get('type')!=kind:raise NotionError('같은 이름의 보기 구성이 달라 자동 변경하지 않았습니다.')
            if not found:self.request('POST','/views',dict(database_id=identity,data_source_id=source_id,name=name,type=kind,configuration=config,sorts=[dict(property='날짜',direction='descending')],position=dict(type='start' if kind=='table' else 'end')))
        return dict(database_id=identity,data_source_id=source_id,url=database.get('url') or 'https://www.notion.so/'+identity.replace('-',''))

    def research_entry(self,destination,record,data):
        # The remote key identifies the project, never an individual report revision.
        key=record['project_id'];found=self.research_rows(destination,{'equals':key})
        if len(found)>1:raise NotionError('동일 프로젝트의 대표 페이지가 여러 개입니다. 기존 내용을 보존했습니다.')
        stamp=datetime.fromisoformat(record['created_at'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Seoul'));runs=data['runs']
        measured=[r for r in runs if r['state']=='succeeded' and r.get('analysis',{}).get('status') in {'measured','compared'}]
        state='측정 있음' if measured else '실패' if runs else '측정 전'
        properties={'제목':{'title':rich(record['title'][:190])},'날짜':{'date':{'start':stamp.isoformat()}},'프로젝트':{'rich_text':rich(record['title'][:900])},'측정 상태':{'select':{'name':state}},'실험 수':{'number':len(runs)},'정상 측정':{'number':len(measured)},'실행 시간(초)':{'number':sum(max(0,r.get('duration_seconds') or 0) for r in runs)},'보고서 키':{'rich_text':rich(key)}}
        if found:
            identity=page_id(found[0]['id']);prior=found[0].get('properties',{}).get('날짜',{}).get('date') or {}
            if prior.get('start'):
                previous=datetime.fromisoformat(prior['start'].replace('Z','+00:00'))
                if previous.tzinfo is None:previous=previous.replace(tzinfo=ZoneInfo('Asia/Seoul'))
                if stamp<previous:return identity # A delayed retry must not regress latest summary properties.
            self.request('PATCH','/pages/'+identity,dict(properties=properties));return identity
        result=self.request('POST','/pages',dict(parent=dict(type='data_source_id',data_source_id=destination['data_source_id']),properties=properties))
        return page_id(result['id'])

    def research_rows(self,destination,condition):
        rows=[];cursor=None
        while True:
            payload=dict(filter={'property':'보고서 키','rich_text':condition},page_size=100)
            if cursor:payload['start_cursor']=cursor
            result=self.request('POST','/data_sources/'+destination['data_source_id']+'/query',payload)
            rows.extend(result['results'])
            if not result.get('has_more'):return rows
            cursor=result['next_cursor']

    def project_page(self,parent,record):
        suffix=' · '+record['project_id'][:8]
        found=[b for b in self.children(parent) if b.get('type')=='child_page' and b['child_page']['title'].endswith(suffix)]
        if len(found)>1:raise NotionError('동일 프로젝트의 페이지가 여러 개입니다. 기존 내용을 보존했습니다.')
        if found:return page_id(found[0]['id'])
        return self.child_page(parent,('BrainDance · '+record['title'])[:160]+suffix)

    def report_section(self,identity,record,known=None):
        # A self-link carries the revision key without exposing hashes in the visible title.
        marker='https://www.notion.so/'+identity.replace('-','')+'?braindance_report='+record['digest']
        children=self.children(identity)
        if known:
            found=[b for b in children if b.get('id')==known and b.get('type')=='toggle']
            if not found:raise NotionError('Notion의 보고서 구역이 이동되거나 삭제되었습니다. 기존 내용을 보존했습니다.')
        else:found=[b for b in children if b.get('type')=='toggle' and any((t.get('text',{}).get('link') or {}).get('url')==marker for t in b['toggle']['rich_text'])]
        if len(found)>1:raise NotionError('동일한 보고서 구역이 여러 개입니다. 기존 내용을 보존했습니다.')
        if found:return page_id(found[0]['id'])
        stamp=datetime.fromisoformat(record['created_at'].replace('Z','+00:00')).astimezone(ZoneInfo('Asia/Seoul'))
        label=stamp.strftime('%Y-%m-%d %H:%M:%S');title=rich(label+' · 연구 결과');title[0]['text']['link']={'url':marker}
        newer=[b for b in children if b.get('type')=='toggle' and any('braindance_report=' in (t.get('text',{}).get('link') or {}).get('url','') for t in b['toggle']['rich_text']) and block_signature(b)[1][:19]>label]
        position={'type':'after_block','after_block':{'id':newer[-1]['id']}} if newer else {'type':'start'}
        result=self.request('PATCH','/blocks/'+identity+'/children',dict(children=[{'object':'block','type':'toggle','toggle':{'rich_text':title}}],position=position))
        return page_id(result['results'][0]['id'])

    def gather_previous(self,destination,identity,project_id):
        """Move legacy database snapshots intact under this project; no deletion or content copying."""
        rows=self.research_rows(destination,{'starts_with':project_id+':'})
        if not rows:return
        archive=self.child_page(identity,'이전 기록')
        for row in rows:
            self.request('POST','/pages/'+page_id(row['id'])+'/move',dict(parent=dict(type='page_id',page_id=archive)))


def rich(value):return [{'type':'text','text':{'content':value}}]


def inline(value):
    result=[];pattern=r'(\*\*[^*]+\*\*|`[^`]+`|https?://[^\s<>]+)';offset=0
    def add(item,bold=False,code=False,link=None):
        for chunk in chunks(item):
            part={'type':'text','text':{'content':chunk}}
            if link:part['text']['link']={'url':link}
            if bold or code:part['annotations']={'bold':bold,'code':code}
            result.append(part)
    for match in re.finditer(pattern,value):
        if match.start()>offset:add(value[offset:match.start()])
        part=match.group()
        if part.startswith('**'):add(part[2:-2],bold=True)
        elif part.startswith('`'):add(part[1:-1],code=True)
        else:add(part,link=part)
        offset=match.end()
    if offset<len(value):add(value[offset:])
    return result or rich(' ')


def markdown_blocks(body):
    """Render the report's Markdown subset as real Notion formatting."""
    lines=body.splitlines();blocks=[];i=0
    def block(kind,value):
        for chunk in chunks(value):blocks.append({'object':'block','type':kind,kind:{'rich_text':inline(chunk)}})
    while i<len(lines):
        line=lines[i].strip();i+=1
        if not line:continue
        if line.startswith('|') and i<len(lines) and re.fullmatch(r'[\s|:\-]+',lines[i]) and '-' in lines[i]:
            rows=[line];i+=1
            while i<len(lines) and lines[i].strip().startswith('|'):rows.append(lines[i].strip());i+=1
            cells=[[c.strip() for c in r.strip('|').split('|')] for r in rows];width=max(map(len,cells))
            # Notion accepts at most 100 children on creation: split long tables.
            for start in range(1,len(cells),90):
                subset=[cells[0],*cells[start:start+90]]
                children=[{'object':'block','type':'table_row','table_row':{'cells':[inline(c) for c in row+['']*(width-len(row))]}} for row in subset]
                blocks.append({'object':'block','type':'table','table':{'table_width':width,'has_column_header':True,'has_row_header':False,'children':children}})
        elif line.startswith('```'):
            content=[]
            while i<len(lines) and not lines[i].strip().startswith('```'):content.append(lines[i]);i+=1
            i+=1
            for chunk in chunks('\n'.join(content)):blocks.append({'object':'block','type':'code','code':{'language':'plain text','rich_text':rich(chunk)}})
        elif re.match(r'^#{1,6}\s',line):
            depth=len(line)-len(line.lstrip('#'));block('heading_'+str(min(3,depth)),line[depth:].strip())
        elif re.match(r'^[-*]\s+',line):block('bulleted_list_item',re.sub(r'^[-*]\s+','',line))
        elif re.match(r'^\d+\.\s+',line):block('numbered_list_item',re.sub(r'^\d+\.\s+','',line))
        else:block('paragraph',line)
    return blocks


def blocks_for(record):
    blocks=[]
    for title,body in record['sections']:
        for chunk in chunks(title):blocks.append({'object':'block','type':'heading_2','heading_2':{'rich_text':rich(chunk)}})
        blocks.extend(markdown_blocks(body))
    return blocks

def chunks(text):
    # 900 codepoints also fits the 2,000 UTF-16-unit limit for emoji.
    return [text[i:i+900] for i in range(0,len(text),900)] or [' ']


def block_signature(block):
    kind=block['type'];payload=block[kind]
    if kind=='table':return (kind,json.dumps([[''.join(t.get('plain_text',t.get('text',{}).get('content','')) for t in cell) for cell in row['table_row']['cells']] for row in payload.get('children',[])],ensure_ascii=False))
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
            if 'layout' not in {r['name'] for r in conn.execute('PRAGMA table_info(links)')}:conn.execute("ALTER TABLE links ADD COLUMN layout TEXT NOT NULL DEFAULT 'pages'")
            conn.execute('CREATE TABLE IF NOT EXISTS connection_settings(id INTEGER PRIMARY KEY CHECK(id=1),parent_id TEXT NOT NULL,auto_sync INTEGER NOT NULL,workspace TEXT NOT NULL,checked_at TEXT NOT NULL,layout TEXT NOT NULL)')
            old=conn.execute("SELECT parent_id,auto_sync,workspace,checked_at,layout FROM links ORDER BY (checked_at!='') DESC,auto_sync DESC,checked_at DESC,rowid DESC LIMIT 1").fetchone()
            conn.execute('INSERT OR IGNORE INTO connection_settings VALUES(1,?,?,?,?,?)',tuple(old) if old else ('',0,'','','database'))
            columns={r['name'] for r in conn.execute('PRAGMA table_info(jobs)')}
            for name,definition in [('attempts','INTEGER NOT NULL DEFAULT 0'),('next_retry','REAL NOT NULL DEFAULT 0')]:
                if name not in columns:conn.execute('ALTER TABLE jobs ADD COLUMN '+name+' '+definition)
            if 'section_id' not in columns:conn.execute('ALTER TABLE jobs ADD COLUMN section_id TEXT')
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

    def settings(self):
        with self.connect() as conn:return dict(conn.execute('SELECT parent_id,auto_sync,workspace,checked_at,layout FROM connection_settings WHERE id=1').fetchone())

    def inherit_connections(self):
        setting=self.settings()
        if not setting['parent_id']:return
        with self.store._connect() as c:projects=[r[0] for r in c.execute('SELECT p.id FROM projects p LEFT JOIN project_lifecycle l ON l.project_id=p.id WHERE l.deleted_at IS NULL')]
        with self.connect() as conn:
            for project_id in projects:conn.execute('INSERT OR IGNORE INTO links(project_id,parent_id,auto_sync,workspace,checked_at,layout) VALUES(?,?,?,?,?,?)',(project_id,setting['parent_id'],setting['auto_sync'],setting['workspace'],setting['checked_at'],setting['layout']))

    def configure(self,project_id=None,parent=None,token='',auto_sync=False,layout='database'):
        if project_id:project_data(self.store,project_id)
        parent=page_id(parent)
        if type(auto_sync) is not bool:raise ValueError('자동 동기화 설정을 확인하세요.')
        if layout not in {'pages','database'}:raise ValueError('Notion 기록 형식을 확인하세요.')
        token=token or self.token()
        if not token:
            if auto_sync:raise ValueError('토큰을 등록한 뒤 자동 동기화를 켜세요.')
            with self.connect() as conn:
                conn.execute('UPDATE connection_settings SET parent_id=?,auto_sync=0,workspace=?,checked_at=?,layout=? WHERE id=1',(parent,'','',layout))
                conn.execute('UPDATE links SET parent_id=?,auto_sync=0,workspace=?,checked_at=?,layout=?',(parent,'','',layout))
            self.inherit_connections()
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
                values=(parent,int(auto_sync),user.get('bot',{}).get('workspace_name') or user.get('name') or 'Notion',now(),layout)
                conn.execute('UPDATE connection_settings SET parent_id=?,auto_sync=?,workspace=?,checked_at=?,layout=? WHERE id=1',values)
                conn.execute('UPDATE links SET parent_id=?,auto_sync=?,workspace=?,checked_at=?,layout=?',values)
            self.inherit_connections()
        return self.state(project_id)

    def disconnect(self):
        with self.lock,self.connect() as conn:
            self.secret.unlink(missing_ok=True);conn.execute('UPDATE links SET auto_sync=0')
            conn.execute('UPDATE connection_settings SET auto_sync=0 WHERE id=1')
            conn.execute("UPDATE jobs SET state='failed',message='Notion 연결이 해제되었습니다.',updated_at=? WHERE kind IN ('notion','notion-database') AND state='queued'",(now(),))
        return {'connected':False}

    def state(self,project_id=None):
        if not project_id:
            setting=self.settings()
            with self.connect() as conn:jobs=[{k:v for k,v in dict(r).items() if k!='snapshot'} for r in conn.execute('SELECT * FROM jobs ORDER BY updated_at DESC,rowid DESC LIMIT 12')]
            return dict(connected=bool(self.token()) and bool(setting['checked_at']),scope='all_projects',link=setting if setting['parent_id'] else None,jobs=jobs,report=None)
        project_data(self.store,project_id)
        self.inherit_connections()
        with self.connect() as conn:
            link=conn.execute('SELECT * FROM links WHERE project_id=?',(project_id,)).fetchone()
            jobs=[{k:v for k,v in dict(r).items() if k!='snapshot'} for r in conn.execute('SELECT * FROM jobs WHERE project_id=? ORDER BY updated_at DESC,rowid DESC LIMIT 12',(project_id,))]
            report=conn.execute('SELECT * FROM reports WHERE project_id=? ORDER BY created_at DESC LIMIT 1',(project_id,)).fetchone()
        record=json.loads(self.file(project_id,report['digest'],'manifest.json').read_text()) if report else None
        return dict(connected=bool(self.token()) and bool(link and link['checked_at']),scope='all_projects',link=dict(link) if link else None,jobs=jobs,report=record)

    def enqueue(self,project_id,publish=False,retry=True):
        data=project_data(self.store,project_id)
        source=getattr(self,'quota_snapshot',None)
        if source:
            from quota_guard import snapshot
            value=snapshot(source())
            if value['providers']:data['account_usage']=value
        digest=signature(data);kind='notion' if publish else 'local'
        self.inherit_connections()
        with self.lock,self.connect() as conn:
            link=conn.execute('SELECT * FROM links WHERE project_id=?',(project_id,)).fetchone()
            if publish and (not link or not self.token()):raise ValueError('프로젝트의 Notion 페이지와 연결 토큰을 먼저 설정하세요.')
            if publish and link['layout']=='database':kind='notion-database'
            parent=link['parent_id'] if publish else ''
            row=conn.execute('SELECT * FROM jobs WHERE project_id=? AND digest=? AND kind=? AND parent_id=?',(project_id,digest,kind,parent)).fetchone()
            if row:
                queue=row['state']=='failed' and retry or publish and row['state']=='completed' and not row['section_id']
                if queue:conn.execute("UPDATE jobs SET state='queued',message='프로젝트 페이지 동기화 대기',updated_at=? WHERE id=?",(now(),row['id']))
                return dict(id=row['id'],state='queued' if queue else row['state'])
            identity=str(uuid.uuid4());stamp=now()
            conn.execute('INSERT INTO jobs(id,project_id,digest,kind,parent_id,state,message,snapshot,created_at,updated_at,page_id,page_url) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(identity,project_id,digest,kind,parent,'queued','보고서 준비 대기',json.dumps(data,ensure_ascii=False,allow_nan=False),stamp,stamp,None,None))
            return dict(id=identity,state='queued')

    def update(self,identity,state,message,**fields):
        with self.connect() as conn:
            conn.execute('UPDATE jobs SET state=?,message=?,updated_at=?'+''.join(','+k+'=?' for k in fields)+' WHERE id=?',(state,message,now(),*fields.values(),identity))

    def process(self,job):
        project_data(self.store,job['project_id'])
        self.update(job['id'],'building','결과와 시각화를 정리합니다.')
        record=build_report(self.root,json.loads(job['snapshot']))
        with self.connect() as conn:conn.execute('INSERT OR IGNORE INTO reports VALUES(?,?,?)',(job['project_id'],job['digest'],record['created_at']))
        if job['kind'] in {'notion','notion-database'}:
            token=self.token()
            if not token:raise ValueError('Notion 연결 토큰을 설정하세요.')
            api=NotionAPI(token,self.stop,guard=lambda:self.token()==token)
            self.update(job['id'],'publishing','Notion 보고서 페이지를 확인합니다.')
            if job['kind']=='notion-database':
                destination=api.research_database(job['parent_id'])
                identity=api.research_entry(destination,record,json.loads(job['snapshot']))
            else:
                identity=api.project_page(job['parent_id'],record)
            url='https://www.notion.so/'+identity.replace('-','')
            section=api.report_section(identity,record,job.get('section_id'))
            self.update(job['id'],'uploading','프로젝트 페이지에 결과와 시각화를 정리합니다.',page_id=identity,page_url=url,section_id=section)
            items=[]
            for title,body in record['sections']:
                items.extend(blocks_for(dict(sections=[(title,body)])))
                if title=='상세 결과':items.extend((c['file'],c['title']+' · '+c['file']) for c in record['charts'])
            items.append(('report.md','연구 보고서 · Markdown'))
            expected=[block_signature(item) if isinstance(item,dict) else ('image' if item[0].endswith('.png') else 'file',item[1]) for item in items]
            existing=api.children(section)
            if len(existing)>len(expected) or [block_signature(b) for b in existing]!=expected[:len(existing)]:raise ValueError('Notion 보고서에 수동 변경이 있습니다. 원본을 보존하기 위해 덮어쓰기를 중단했습니다.')
            offset=len(existing)
            while offset<len(items):
                project_data(self.store,job['project_id'])
                item=items[offset]
                if isinstance(item,tuple):
                    name,caption=item
                    if not self.token():raise ValueError('Notion 연결이 해제되었습니다.')
                    batch=[api.upload(self.file(job['project_id'],job['digest'],name),caption)]
                else:
                    batch=[];size=0
                    for item in items[offset:offset+80]:
                        if not isinstance(item,dict):break
                        encoded=len(json.dumps(item,ensure_ascii=False).encode())
                        if size+encoded>350000:break
                        batch.append(item);size+=encoded
                api.request('PATCH','/blocks/'+section+'/children',dict(children=batch));offset+=len(batch)
            if job['kind']=='notion-database':api.gather_previous(destination,identity,job['project_id'])
            self.update(job['id'],'completed','Notion에 결과와 시각화를 정리했습니다.')
        else:self.update(job['id'],'completed','보고서와 시각화를 저장했습니다.')
        # Publication receipts belong to the same project stream; they are not
        # inputs to the report fingerprint, avoiding an automatic-sync loop.
        with self.store._connect() as conn:
            root=conn.execute('SELECT n.id FROM nodes n JOIN node_projects p ON p.node_id=n.id WHERE p.project_id=? AND n.parent_id IS NULL',(job['project_id'],)).fetchone()
            if root:conn.execute('INSERT OR IGNORE INTO notes VALUES(?,?,?,?,?,?)',('publication:'+job['id'],root['id'],'publication','Notion 결과 정리 완료' if job['kind'] in {'notion','notion-database'} else '결과 보고서·시각화 생성 완료',url if job['kind'] in {'notion','notion-database'} else f"시각화 {len(record['charts'])}개 · 결과 탭에서 확인할 수 있습니다.",now()))

    def tick(self):
        # A quota stop always gets a local report, even without external integrations.
        # Wait for cancellation receipts so the snapshot includes partial run results.
        with self.store._connect() as c:
            sessions=c.execute("SELECT project_id FROM automatic_sessions WHERE status='stopped' AND json_extract(progress,'$.quota_stop') IS NOT NULL").fetchall()
        for row in sessions:
            try:
                if quiescent(self.store,row['project_id']):self.enqueue(row['project_id'])
            except (ValueError,KeyError):pass
        self.inherit_connections()
        with self.connect() as conn:links=[dict(r) for r in conn.execute('SELECT * FROM links WHERE auto_sync=1')]
        if not self.token():return
        for link in links:
            try:
                data=project_data(self.store,link['project_id'])
                if data.get('execution_state',{}).get('status') in {'stopped','completed'} and not quiescent(self.store,link['project_id']):continue
                from research_reports import TERMINAL
                ended=[r for r in data.get('runs',[]) if r['state'] in TERMINAL]
                if not ended and not data.get('brief') and data.get('execution_state',{}).get('status') not in {'stopped','completed'}:continue
                with self.connect() as conn:previous=conn.execute("SELECT snapshot FROM jobs WHERE project_id=? AND kind IN ('notion','notion-database') ORDER BY rowid DESC LIMIT 1",(link['project_id'],)).fetchone()
                if previous:
                    prior=json.loads(previous['snapshot'])
                    # Internal reviews and brainstorming remain in the journal; publish scientific milestones.
                    if prior.get('schema_version',0)>=2 and [r for r in prior.get('runs',[]) if r['state'] in TERMINAL]==ended and prior.get('brief')==data.get('brief') and prior.get('execution_state')==data.get('execution_state'):continue
                self.enqueue(link['project_id'],publish=True,retry=False)
            except (ValueError,KeyError):pass

    def loop(self):
        while not self.stop.is_set():
            try:
                if time.monotonic()-self.last_auto>30:self.last_auto=time.monotonic();self.tick()
                with self.connect() as conn:row=conn.execute("SELECT * FROM jobs WHERE state='queued' AND next_retry<=? ORDER BY created_at LIMIT 1",(time.time(),)).fetchone()
                if row:
                    with self.execution_lock:
                        self.active=row['project_id']
                        try:self.process(dict(row))
                        except Exception as error:
                            # Never persist request bodies, credentials, or untrusted remote errors.
                            message=str(error) if isinstance(error,(NotionError,ValueError)) else '보고서 처리 중 오류가 발생했습니다. 로컬 원본은 보존했습니다.'
                            if isinstance(error,NotionError) and error.retryable:
                                attempts=row['attempts']+1;delay=min(300,2**min(attempts,9))
                                self.update(row['id'],'queued','자동 재시도 대기 · '+message[:800],attempts=attempts,next_retry=time.time()+delay)
                            else:self.update(row['id'],'failed',message[:1000])
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
