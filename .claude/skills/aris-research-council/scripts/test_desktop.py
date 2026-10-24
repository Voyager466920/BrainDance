"""Native backend contract; temporary storage, no inference or credential access."""
import http.client
import json
import os
from pathlib import Path
import selectors
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import urlsplit

BACKEND=Path(__file__).resolve().parents[4]/'desktop/backend.py'


class DesktopBackendTests(unittest.TestCase):
    def launch(self,directory,port=0):
        process=subprocess.Popen([sys.executable,str(BACKEND),'--data-dir',str(directory),'--port',str(port)],
            stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True)
        self.addCleanup(self.stop,process)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            self.assertTrue(selector.select(10),'Backend readiness message timed out')
        ready=json.loads(process.stdout.readline())
        self.assertEqual(ready['app'],'BrainDance')
        url=urlsplit(ready['url'])
        self.assertEqual(url.hostname,'127.0.0.1')
        return url.port

    @staticmethod
    def stop(process):
        if process.poll() is None:
            process.terminate()
        process.wait(timeout=5)
        process.stdout.close()

    def request(self,port,path):
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
        try:
            connection.request('GET',path)
            response=connection.getresponse()
            self.assertEqual(response.status,200)
            return response.read()
        finally:connection.close()

    def test_empty_private_workspace_health_and_occupied_port_fallback(self):
        temporary_directory=tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        temporary=temporary_directory.name
        first=Path(temporary)/'first';second=Path(temporary)/'second'
        port=self.launch(first)
        self.assertEqual(json.loads(self.request(port,'/api/health'))['app'],'BrainDance')
        tree=json.loads(self.request(port,'/api/tree'))
        self.assertEqual(tree['projects'],[])
        self.assertEqual(tree['nodes'],[])
        self.assertIn(b'BrainDance',self.request(port,'/'))
        self.assertTrue((first/'tree.sqlite3').is_file())
        other_port=self.launch(second,port)
        self.assertNotEqual(other_port,port)
        self.assertEqual(json.loads(self.request(other_port,'/api/tree'))['nodes'],[])


if __name__=='__main__':unittest.main()
