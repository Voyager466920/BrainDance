"""Local/SSH resource discovery and project assignments. No experiment launcher."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import threading
import uuid


PROBE = r'''
import csv,io,json,platform,shutil,subprocess
devices=[dict(id='cpu',name='CPU',kind='cpu')]
if shutil.which('nvidia-smi'):
 p=subprocess.run(['nvidia-smi','--query-gpu=uuid,name,memory.total,memory.used,utilization.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=12)
 if p.returncode: raise RuntimeError(p.stderr[:2000])
 for row in csv.reader(io.StringIO(p.stdout)):
  if len(row)!=5: continue
  identity,name,total,used,util=[v.strip() for v in row]
  number=lambda value:int(value) if value.isdigit() else None
  devices.append(dict(id=identity,name=name,kind='cuda',memory_total_mb=number(total),memory_used_mb=number(used),utilization_percent=number(util)))
elif platform.system()=='Darwin':
 p=subprocess.run(['system_profiler','SPDisplaysDataType','-json'],capture_output=True,text=True,timeout=15)
 if p.returncode==0:
  for i,item in enumerate(json.loads(p.stdout).get('SPDisplaysDataType',[])):
   name=item.get('sppci_model','')
   if name.startswith('Apple '): devices.append(dict(id='metal:'+str(i),name=name,kind='metal'))
print(json.dumps(dict(platform=platform.system(),devices=devices)))
'''


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def fingerprint(profile):
    return hashlib.sha256(json.dumps(profile,sort_keys=True).encode()).hexdigest()


def validate_profile(profile):
    allowed = {'id','name','kind','host','user','port','identity_file'}
    if not isinstance(profile,dict) or set(profile)-allowed:
        raise ValueError('지원하지 않는 연결 설정입니다.')
    if profile.get('kind') not in {'local','ssh'}:
        raise ValueError('로컬 또는 SSH를 선택하세요.')
    name=profile.get('name','')
    if not isinstance(name,str) or not name.strip() or len(name)>100:
        raise ValueError('연결 이름을 입력하세요 (최대 100자).')
    if profile['kind']=='local':
        return dict(id='local',name='이 Mac',kind='local')
    host=profile.get('host','')
    if not isinstance(host,str) or not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.:\[\]-]{0,252}',host):
        raise ValueError('SSH Host 별칭 또는 호스트 주소를 입력하세요.')
    user=profile.get('user','')
    if not isinstance(user,str) or (user and not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,63}',user)):
        raise ValueError('SSH 사용자 이름이 올바르지 않습니다.')
    port=profile.get('port',None)
    if port is not None and (type(port) is not int or not 1<=port<=65535):
        raise ValueError('포트는 1–65535 범위여야 합니다.')
    identity=profile.get('identity_file','')
    if not isinstance(identity,str) or len(identity)>1024 or '\n' in identity or '\x00' in identity:
        raise ValueError('키 파일 경로가 올바르지 않습니다.')
    if identity:
        path=Path(identity).expanduser()
        if not path.is_absolute() or not path.is_file():
            raise ValueError('존재하는 개인 키 파일의 절대 경로를 입력하세요.')
        identity=str(path)
    return dict(id=profile.get('id') or str(uuid.uuid4()),name=name.strip(),kind='ssh',host=host,user=user,port=port,identity_file=identity)


def ssh_command(profile):
    profile=validate_profile(profile)
    args=['ssh','-T','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
          '-o','ConnectTimeout=8','-o','ConnectionAttempts=1','-o','ForwardAgent=no',
          '-o','ClearAllForwardings=yes','-o','UpdateHostKeys=no']
    if profile.get('port'):
        args+=['-p',str(profile['port'])]
    if profile.get('identity_file'):
        args+=['-i',profile['identity_file']]
    dest=(profile['user']+'@' if profile['user'] else '')+profile['host']
    return args+['--',dest,'python3 -c '+shlex.quote(PROBE)]


class ComputeSettings:
    def __init__(self,path):
        self.path=Path(path)
        self.lock=threading.RLock()
        self.inventories={}
        self.data=json.loads(self.path.read_text()) if self.path.exists() else dict(version=1,
            profiles=[dict(id='local',name='이 Mac',kind='local')],assignments={})
        # Restore timestamped discovery receipts, never silently reconnect on startup.
        history=self.path.with_name('compute-events.jsonl')
        if history.exists():
            for line in history.read_text()[-1000000:].splitlines():
                try:
                    entry=json.loads(line);profile=next((p for p in self.data['profiles'] if p['id']==entry.get('profile_id')),None)
                    if profile and entry.get('fingerprint')==fingerprint(profile):
                        self.inventories[profile['id']]={k:v for k,v in entry.items() if k!='profile_id'}
                except (ValueError,TypeError):
                    continue

    def _save(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temporary=self.path.with_suffix('.tmp')
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as stream:
            json.dump(self.data,stream,ensure_ascii=False,indent=2)
        os.replace(temporary,self.path)

    def state(self):
        with self.lock:
            aliases=[]
            path=Path.home()/'.ssh/config'
            if path.exists():
                for line in path.read_text().splitlines():
                    try: parts=shlex.split(line,comments=True)
                    except ValueError: continue
                    if parts and parts[0].lower()=='host':
                        aliases.extend(h for h in parts[1:] if re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]*',h))
            return {**json.loads(json.dumps(self.data)), 'inventories':dict(self.inventories),
                    'ssh_aliases':list(dict.fromkeys(aliases)),'execution_available':False}

    def save_profile(self,profile):
        clean=validate_profile(profile)
        if clean['kind']=='ssh' and clean['id']=='local':
            raise ValueError('로컬 실행 환경은 SSH 연결로 덮어쓸 수 없습니다.')
        if not isinstance(clean['id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',clean['id']):
            raise ValueError('연결 ID가 올바르지 않습니다.')
        with self.lock:
            existing=next((p for p in self.data['profiles'] if p['id']==clean['id']),None)
            if existing!=clean:
                self.inventories.pop(clean['id'],None)
                for assignment in self.data['assignments'].values():
                    if assignment['profile_id']==clean['id']:
                        assignment['device_ids']=[]
                        assignment['verified']=False
            self.data['profiles']=[p for p in self.data['profiles'] if p['id']!=clean['id']]+[clean]
            self._save()
        return clean

    def probe(self,profile_id):
        with self.lock:
            profile=next((dict(p) for p in self.data['profiles'] if p['id']==profile_id),None)
        if not profile:
            raise ValueError('먼저 연결 설정을 저장하세요.')
        command=[sys.executable,'-c',PROBE] if profile['kind']=='local' else ssh_command(profile)
        try:
            process=subprocess.run(command,capture_output=True,text=True,timeout=35)
            if process.returncode:
                raise ValueError(process.stderr.strip()[:3000] or '연결 또는 GPU 조회에 실패했습니다.')
            inventory=json.loads(process.stdout)
            if not isinstance(inventory.get('devices'),list) or not all(isinstance(d,dict) and isinstance(d.get('id'),str) for d in inventory['devices']):
                raise ValueError('GPU 조회 응답을 해석할 수 없습니다.')
            inventory.update(connected=True,checked_at=timestamp(),fingerprint=fingerprint(profile))
        except (subprocess.TimeoutExpired,ValueError,OSError) as error:
            inventory=dict(connected=False,devices=[],checked_at=timestamp(),error=str(error)[:3000],fingerprint=fingerprint(profile))
        with self.lock:
            current=next((p for p in self.data['profiles'] if p['id']==profile_id),None)
            if current!=profile:
                raise ValueError('연결 설정이 변경되었습니다. 다시 확인하세요.')
            self.inventories[profile_id]=inventory
            self.path.parent.mkdir(parents=True,exist_ok=True)
            with self.path.with_name('compute-events.jsonl').open('a') as stream:
                stream.write(json.dumps(dict(profile_id=profile_id,**inventory),ensure_ascii=False)+'\n')
        return inventory

    def prepare_assignment(self,payload):
        if set(payload)-{'profile_id','device_ids','max_parallel_runs','time_budget_minutes','auto_run'}:
            raise ValueError('지원하지 않는 실행 설정입니다.')
        if payload.get('auto_run',False) is not False:
            raise ValueError('자동 실행은 아직 연결되지 않았습니다.')
        devices=payload.get('device_ids',[])
        if not isinstance(devices,list) or not devices or not all(isinstance(d,str) for d in devices):
            raise ValueError('사용할 CPU 또는 GPU를 선택하세요.')
        if len(set(devices))!=len(devices) or ('cpu' in devices and len(devices)>1):
            raise ValueError('CPU 단독 또는 GPU만 선택하세요.')
        parallel=payload.get('max_parallel_runs',1);minutes=payload.get('time_budget_minutes',30)
        if type(parallel) is not int or not 1<=parallel<=16 or type(minutes) is not int or not 1<=minutes<=1440:
            raise ValueError('동시 실행 1–16개, 시간 예산 1–1440분 범위로 입력하세요.')
        with self.lock:
            profile=next((p for p in self.data['profiles'] if p['id']==payload.get('profile_id')),None)
            if not profile: raise ValueError('실행 환경을 선택하세요.')
            inventory=self.inventories.get(profile['id'],{})
            allowed={'cpu'} if profile['kind']=='local' else set()
            verified=inventory.get('connected') and inventory.get('fingerprint')==fingerprint(profile)
            if verified:
                try:
                    age=(datetime.now(timezone.utc)-datetime.fromisoformat(inventory['checked_at'])).total_seconds()
                    verified=0<=age<=300
                except (KeyError,ValueError,TypeError):
                    verified=False
            if verified: allowed.update(d['id'] for d in inventory['devices'])
            if not set(devices)<=allowed: raise ValueError('먼저 연결을 확인하고 조회된 장치를 선택하세요.')
            assignment=dict(profile_id=profile['id'],device_ids=devices,max_parallel_runs=parallel,
                time_budget_minutes=minutes,auto_run=False,require_approval=True,
                verified=bool(verified),updated_at=timestamp())
            return assignment

    def persist_assignment(self,project_id,assignment):
        with self.lock:
            self.data['assignments'][project_id]=assignment
            self._save()
        return assignment

    def assign(self,project_id,payload):
        with self.lock:
            return self.persist_assignment(project_id,self.prepare_assignment(payload))
