"""Exercise the real PC sync client against the C++ firmware core over loopback."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import threading
import unittest
from datetime import datetime
from test_sd_copy import account, site
ROOT = Path(__file__).resolve().parents[1]
DOTNET = os.environ.get('BWW_DOTNET') or shutil.which('dotnet')
HARNESS = os.environ.get('BWW_FIRMWARE_HARNESS')
DLL = ROOT/'server/bin/Release/net8.0/Bww.Server.dll'
PASSWORD = 'correct horse battery'

@unittest.skipUnless(DOTNET and HARNESS and DLL.is_file(), 'Requires built PC server, dotnet and firmware harness')
class SyncTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.pc = self.root/'store.json'; self.sd = self.root/'sd'; self.sd.mkdir()
        self.pc.write_text(json.dumps(dict(Users={'alice':account()}, Sessions={}, Sites={})))
        self.fw = subprocess.Popen([HARNESS,str(self.sd)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.token = self.call(op='register',username='alice',password=PASSWORD)['data']['token']
    def tearDown(self):
        self.fw.stdin.close(); self.fw.wait(timeout=5); self.fw.stdout.close(); self.fw.stderr.close(); self.temp.cleanup()
    def call(self, **request):
        self.fw.stdin.write(json.dumps(request)+'\n'); self.fw.stdin.flush(); return json.loads(self.fw.stdout.readline())
    def pc_site(self, html, domain='garden.bww', owner='alice'):
        value=json.loads(self.pc.read_text()); value['Sites'][domain]=site(domain,owner,html); self.pc.write_text(json.dumps(value))
    def fw_site(self, html, domain='garden.bww', token=None):
        result=self.call(op='publish',token=token or self.token,domain=domain,html=html,css='',js=''); self.assertTrue(result['ok'],result)
    def run_sync(self, choices, accept=True, hook=None):
        listener=socket.socket(); listener.bind(('127.0.0.1',0));listener.listen();listener.settimeout(5)
        port=listener.getsockname()[1]; errors=[]
        def bridge():
            try:
                connection,_=listener.accept()
                with connection, connection.makefile('rwb') as stream:
                    while line:=stream.readline():
                        request=json.loads(line)
                        if hook: hook(request)
                        result=self.call(**request)
                        stream.write((json.dumps(result)+'\n').encode());stream.flush()
            except Exception as e: errors.append(e)
        thread=threading.Thread(target=bridge);thread.start()
        data='alice\n'+PASSWORD+'\n'+PASSWORD+'\n'+''.join(c+'\n' for c in choices)
        if choices:data+=('APPLY' if accept else 'cancel')+'\n'
        result=subprocess.run([DOTNET,str(DLL),'--sync','--sync-tcp',str(port),'--data',str(self.pc)],input=data,text=True,capture_output=True,timeout=90)
        thread.join(5);listener.close();self.assertFalse(thread.is_alive());self.assertFalse(errors,errors)
        return result
    def test_pc_sync_reads_all_pages_beyond_32_websites(self):
        for i in range(35): self.fw_site('site '+str(i),domain=f'page-{i}.bww')
        result=self.run_sync(['D']*35)
        self.assertEqual(result.returncode,0,result.stderr)
        sites=json.loads(self.pc.read_text())['Sites']
        self.assertEqual(len(sites),35); self.assertEqual(sites['page-34.bww']['Html'],'site 34')

    def test_preview_cancel_and_pc_to_esp_then_noop(self):
        self.pc_site('<h1>PC 💚</h1>');before=json.loads(self.pc.read_text())['Sites']
        r=self.run_sync(['P'],accept=False);self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn('PC only',r.stdout);self.assertEqual(self.call(op='list')['data'],[])
        after=json.loads(self.pc.read_text())['Sites']
        for collection in (before,after):
            for value in collection.values():value['Updated']=datetime.fromisoformat(value['Updated'])
        self.assertEqual(after,before)
        r=self.run_sync(['P']);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(self.call(op='sync_manifest',token=self.token)['data'][0]['domain'],'garden.bww')
        r=self.run_sync([]);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('already in sync',r.stdout)
    def test_device_to_pc_conflict_choice_preserves_credentials_and_backups(self):
        self.pc_site('old');self.fw_site('device new')
        original=json.loads(self.pc.read_text())['Users']
        r=self.run_sync(['D']);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('different content',r.stdout)
        value=json.loads(self.pc.read_text());self.assertEqual(value['Sites']['garden.bww']['Html'],'device new');self.assertEqual(value['Users'],original)
        backups=list(self.root.glob('store.json.sync-backup-*'));self.assertEqual(len(backups),1)
        self.assertEqual(json.loads(backups[0].read_text())['Sites']['garden.bww']['Html'],'old')
    def test_full_512kib_unicode_round_trip(self):
        html='abcd💚'*(524288//8);self.pc_site(html)
        value=json.loads(self.pc.read_text());value['Sites']['garden.bww']['Css']='';value['Sites']['garden.bww']['Js']='';self.pc.write_text(json.dumps(value))
        r=self.run_sync(['P']);self.assertEqual(r.returncode,0,r.stderr)
        value=json.loads(self.pc.read_text());value['Sites']={};self.pc.write_text(json.dumps(value))
        r=self.run_sync(['D']);self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(self.pc.read_text())['Sites']['garden.bww']['Html'],html)
    def test_destination_changed_before_commit_refuses_overwrite(self):
        self.pc_site('PC version');self.fw_site('old device')
        def hook(request):
            if request['op']=='publish_commit':self.fw_site('changed during sync')
        r=self.run_sync(['P'],hook=hook);self.assertNotEqual(r.returncode,0);self.assertIn('changed since comparison',r.stderr)
        self.assertEqual(self.call(op='get',domain='garden.bww')['data']['html'],'changed during sync')
    def test_source_changed_after_comparison_refuses_copy(self):
        self.fw_site('original')
        changed=False
        def hook(request):
            nonlocal changed
            if request['op']=='get' and not changed:changed=True;self.fw_site('new source')
        r=self.run_sync(['D'],hook=hook);self.assertNotEqual(r.returncode,0);self.assertIn('Source changed',r.stderr)
        self.assertEqual(json.loads(self.pc.read_text())['Sites'],{})
    def test_other_owner_cannot_be_overwritten(self):
        bob=self.call(op='register',username='bob',password=PASSWORD)['data']['token'];self.fw_site('Bob',token=bob)
        self.pc_site('Alice');r=self.run_sync([]);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('blocked: domain belongs to another account',r.stdout)
        self.assertEqual(self.call(op='get',domain='garden.bww')['data']['html'],'Bob')
    def test_manifest_authentication_corrupt_chunks_and_segmentation(self):
        self.assertEqual(self.call(op='sync_manifest',token='wrong')['error'],'unauthorized')
        begin=self.call(op='publish_begin',token=self.token,domain='garden.bww')['data']['transfer']
        for index,html in enumerate(['he','llo💚']):self.assertTrue(self.call(op='publish_chunk',token=self.token,transfer=begin,asset='html',index=index,data=html.encode().hex())['ok'])
        self.assertTrue(self.call(op='publish_commit',token=self.token,transfer=begin)['ok'])
        self.pc_site('hello💚');value=json.loads(self.pc.read_text());value['Sites']['garden.bww']['Css']='';value['Sites']['garden.bww']['Js']='';self.pc.write_text(json.dumps(value))
        r=self.run_sync([]);self.assertEqual(r.returncode,0,r.stderr);self.assertIn('already in sync',r.stdout)
        next((self.sd/'bww/sites').glob('*.bin')).write_bytes(b'damaged')
        self.assertEqual(self.call(op='sync_manifest',token=self.token)['error'],'storage_error')
if __name__=='__main__':unittest.main(verbosity=2)
