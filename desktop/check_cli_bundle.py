#!/usr/bin/env python3
"""Check the built macOS CLI/server lifetime using a disposable CPU workspace."""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request


def main():
    app=Path(sys.argv[1] if len(sys.argv)>1 else 'dist/BrainDance.app').resolve()
    executable=app if app.is_file() else app/'Contents/Resources/BrainDanceServer'
    resources=executable.parent
    keymap=json.loads((resources/'BrainDance.itermkeymap').read_text())
    assert len(keymap['Key Mappings'])==3 and all(k['Action']==11 for k in keymap['Key Mappings'].values())
    def run(*args):
        result=subprocess.run([str(executable),'--cli',*args],capture_output=True,text=True,timeout=40)
        if result.returncode:raise RuntimeError(result.stderr)
        return result.stdout
    startup=run()
    assert 'BrainDance' in startup and '▉' in startup
    with tempfile.TemporaryDirectory(prefix='braindance-bundle-check-') as folder:
        database=Path(folder).resolve()/'tree.sqlite3'
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        address='http://127.0.0.1:'+str(port)
        def get(path):
            with urllib.request.urlopen(address+path,timeout=8) as response:return response.read().decode()
        pid=None
        try:
            assert json.loads(run('projects','--json','--db',str(database),'--port',str(port)))==[]
            # Prove the packaged native host can load and speak real MCP framing.
            native_job=Path(folder)/'native-job.json'
            native_job.write_text(json.dumps(dict(native_workspace=str(Path(folder)/'native'),run_dir=folder,db=str(database),mode='lite',council_overrides={},project_session={},session_budget=str(Path(folder)/'budget.json'))))
            messages=''.join(json.dumps(dict(jsonrpc='2.0',id=i,method=m,params={}))+'\n' for i,m in enumerate(['initialize','tools/list']))
            native=subprocess.run([str(executable),'--native-host',str(native_job)],input=messages,capture_output=True,text=True,timeout=20)
            assert native.returncode==0,native.stderr
            replies=[json.loads(line) for line in native.stdout.splitlines()]
            assert {'codex','council','experiment','context','finish'}<={tool['name'] for tool in replies[1]['result']['tools']}
            health=json.loads(get('/api/health'))
            assert health['workspace_id']==hashlib.sha256(str(database).encode()).hexdigest()
            pid=health['pid']
            # The first one-file CLI process has exited. Its temp directory must not
            # contain the detached server's only copies of GUI/experiment assets.
            assert 'BrainDance' in get('/')
            assert 'code' in json.loads(get('/api/experiment-template'))
            project=json.loads(run('new','Bundle fixture','--goal','Offline CPU fixture','--json','--db',str(database),'--server',address))
            interests=json.loads(run('interests','--project',project['project_id'],'--interest','edge adaptation','--bridge','control','--style','scout','--seconds','20','--pilots','1','--json','--db',str(database),'--server',address))
            assert interests['style']=='scout' and interests['interests']==['edge adaptation'] and interests['pilot_seconds']==20
            saved=json.loads(run('interests','--project',project['project_id'],'--json','--db',str(database),'--server',address));assert saved==interests
            status=json.loads(run('status','--project',project['project_id'],'--json','--db',str(database),'--server',address))
            assert status['session'] is None and not status['runs']
            assert json.loads(get('/api/health'))['pid']==pid
            assert 'BrainDance' in get('/')
            csrf=re.search(r"const csrf='([^']+)'",get('/')).group(1)
            def post(path,payload):
                request=urllib.request.Request(address+path,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Origin':address,'X-CSRF-Token':csrf})
                with urllib.request.urlopen(request,timeout=8) as response:return json.load(response)
            # Run a tiny stdlib CPU fixture after the original CLI has exited. It
            # also catches an inherited CA path into the removed CLI directory.
            code="import ssl,os,json\nfrom pathlib import Path\nssl.create_default_context()\nprint('BUNDLE_CPU_AND_CA_OK')\nPath(os.environ['BRAINDANCE_METRICS_PATH']).write_text(json.dumps({'accuracy':0.7}))"
            plan=post('/api/experiment',dict(node_id=project['node']['id'],title='Packaged CPU fixture',timeout_seconds=15,code=code))
            approval=post('/api/experiment/approve',dict(id=plan['id'],digest=plan['digest'],consent=True))
            run_record=post('/api/experiment/run',dict(id=plan['id'],approval_id=approval['id']))
            deadline=time.monotonic()+20
            while time.monotonic()<deadline:
                receipt=json.loads(get('/api/run?id='+run_record['id']))
                if receipt['state'] not in {'queued','running'}:break
                time.sleep(.1)
            assert receipt['state']=='succeeded',receipt
            assert 'BUNDLE_CPU_AND_CA_OK' in receipt['stdout_tail']
            run('report','build','--project',project['project_id'],'--json','--db',str(database),'--server',address)
            deadline=time.monotonic()+30
            while time.monotonic()<deadline:
                reports=json.loads(get('/api/reports?project_id='+project['project_id']))
                if reports['report'] or any(j['state']=='failed' for j in reports['jobs']):break
                time.sleep(.1)
            assert reports['report'],reports['jobs']
            chart=reports['report']['charts'][0]
            with urllib.request.urlopen(address+'/api/reports/file?project_id='+project['project_id']+'&digest='+reports['report']['digest']+'&file='+chart['file']) as response:
                assert response.read().startswith(b'\x89PNG')
            assert 'observed' in get('/api/reports/preview?project_id='+project['project_id']) or 'img' in get('/api/reports/preview?project_id='+project['project_id'])
            # Exercise the shipped CLI against disposable data, including actual
            # report/run cleanup and an unrelated project that must survive.
            common=('--json','--db',str(database),'--server',address)
            other=json.loads(run('new','Keep bundle fixture','--goal','Must survive deletion',*common))
            external=database.parent/'external-input.txt';external.write_text('preserve external source')
            run('delete','--project',project['project_id'],*common)
            assert any(p['id']==project['project_id'] for p in json.loads(run('trash',*common)))
            run('restore','--project',project['project_id'],*common)
            assert Path(receipt['run_dir']).exists()
            run('delete','--project',project['project_id'],*common)
            preview=json.loads(run('purge','--project',project['project_id'],'--preview',*common))
            assert preview['local_file_bytes']>0 and Path(receipt['run_dir']).exists()
            deleted=json.loads(run('purge','--project',project['project_id'],'--confirm-name','Bundle fixture',*common))
            assert not deleted['cleanup_pending'] and deleted['removed_file_bytes']>0
            assert not Path(receipt['run_dir']).exists() and external.exists()
            assert json.loads(run('trash',*common))==[]
            assert [p['id'] for p in json.loads(run('projects',*common))]==[other['project_id']]
            print('PASS: packaged logo, detached assets/CA, shared backend, actual CPU/PNG reporting, Trash/restore/confirmed purge and local space cleanup; no model/GPU/Notion account calls.')
        finally:
            if pid:
                os.kill(pid,signal.SIGTERM)
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:get('/api/health');time.sleep(.1)
                    except OSError:break


if __name__=='__main__':main()
