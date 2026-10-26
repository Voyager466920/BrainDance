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
    executable=app/'Contents/Resources/BrainDanceServer'
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
            health=json.loads(get('/api/health'))
            assert health['workspace_id']==hashlib.sha256(str(database).encode()).hexdigest()
            pid=health['pid']
            # The first one-file CLI process has exited. Its temp directory must not
            # contain the detached server's only copies of GUI/experiment assets.
            assert 'BrainDance' in get('/')
            assert 'code' in json.loads(get('/api/experiment-template'))
            project=json.loads(run('new','Bundle fixture','--goal','Offline CPU fixture','--json','--db',str(database),'--server',address))
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
            print('PASS: packaged logo, detached assets/CA, shared backend, actual CPU execution and measured PNG reporting; no model/GPU/Notion account calls.')
        finally:
            if pid:
                os.kill(pid,signal.SIGTERM)
                deadline=time.monotonic()+8
                while time.monotonic()<deadline:
                    try:get('/api/health');time.sleep(.1)
                    except OSError:break


if __name__=='__main__':main()
