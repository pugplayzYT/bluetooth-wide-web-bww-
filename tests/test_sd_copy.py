"""Temporary-folder copy tests plus actual C++/C# reader compatibility checks."""
import base64
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bww_sd_copy as tool
HARNESS = os.environ.get('BWW_FIRMWARE_HARNESS')
DOTNET = os.environ.get('BWW_DOTNET') or shutil.which('dotnet')
DLL = ROOT / 'server/bin/Release/net8.0/Bww.Server.dll'
PASSWORD = 'correct horse battery'

def account(name='alice', salt=b'0123456789abcdef'):
    return dict(Name=name, Salt=base64.b64encode(salt).decode(),
                Hash=base64.b64encode(hashlib.pbkdf2_hmac('sha256', PASSWORD.encode(), salt, 210000)).decode())

def store(users=None, sites=None):
    return dict(Users=users or {'alice': account()}, Sessions={}, Sites=sites or {})

def site(domain='garden.bww', owner='alice', html='<h1>💚</h1>'):
    return dict(Domain=domain, Owner=owner, Html=html, Css='h1 { color: green; }', Js="localStorage.setItem('score','42');",
                Updated=datetime.now(timezone.utc).isoformat())

class CopyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = Path(self.temp.name)
        self.pc = self.root/'computer'/'store.json'; self.pc.parent.mkdir()
        self.sd = self.root/'card'; self.sd.mkdir(); self.backups = self.root/'backups'
        self.write_pc(store(sites={'garden.bww':site()}))
    def tearDown(self): self.temp.cleanup()
    def write_pc(self, value): self.pc.write_text(json.dumps(value), encoding='utf-8')
    def copy(self, direction='to-sd', pc=None):
        plan=tool.plan_copy(pc or self.pc,self.sd,direction)
        return tool.apply_copy(plan,self.backups)
    def card_bytes(self):
        return {str(p.relative_to(self.sd)):p.read_bytes() for p in self.sd.rglob('*') if p.is_file() and p.name!='.bww-copy.lock'}
    def test_preview_is_read_only_and_both_directions_preserve_accounts_and_assets(self):
        (self.sd/'holiday.jpg').write_bytes(b'photo')
        plan=tool.plan_copy(self.pc,self.sd)
        self.assertEqual(plan.added_sites,['garden.bww']); self.assertFalse((self.sd/'bww').exists())
        saved=self.copy(); self.assertTrue((saved/'COPY_PLAN.txt').exists())
        self.assertEqual((self.sd/'holiday.jpg').read_bytes(),b'photo')
        loaded=tool.load_sd(self.sd); self.assertEqual(loaded.sites['garden.bww']['html'],'<h1>💚</h1>')
        exported=self.root/'other'/'store.json'; self.copy('to-computer',exported)
        result=json.loads(exported.read_text()); original=json.loads(self.pc.read_text())
        self.assertEqual(result['Users'],original['Users']); self.assertEqual(result['Sites']['garden.bww']['Html'],original['Sites']['garden.bww']['Html'])
        self.assertEqual(result['Sessions'],{})
    def test_512kib_unicode_chunks_are_valid_and_sd_checksums_detect_corruption(self):
        data=site(html='abcd💚'*(524288//8)); data['Css']=data['Js']=''
        self.write_pc(store(sites={'garden.bww':data})); self.copy()
        self.assertEqual(tool.load_sd(self.sd).sites['garden.bww']['html'],data['Html'])
        chunks=list((self.sd/'bww/sites').glob('*.bin')); self.assertEqual(len(chunks),64)
        self.assertTrue(all(p.stat().st_size<=8192 for p in chunks))
        chunks[0].write_bytes(b'corrupt')
        with self.assertRaises(tool.CopyError): tool.load_sd(self.sd)
    def test_updates_back_up_old_sd_keep_unrelated_sites_and_preserve_previous_snapshot(self):
        self.copy()
        self.write_pc(store(sites={'other.bww':site('other.bww')})); self.copy()
        self.write_pc(store(sites={'garden.bww':site(html='changed')})); saved=self.copy()
        current=tool.load_sd(self.sd); self.assertEqual(len(current.sites),2)
        self.assertEqual(current.sites['garden.bww']['html'],'changed')
        backed=tool.load_sd(saved); self.assertEqual(backed.sites['garden.bww']['html'],'<h1>💚</h1>')
        active=self.sd/f'bww/state-{current.active}.json'; active.write_text('{damaged')
        restored=tool.load_sd(self.sd); self.assertEqual(restored.sites['garden.bww']['html'],'<h1>💚</h1>')
    def test_sessions_are_not_copied_but_destination_sessions_are_preserved(self):
        state=json.loads(self.pc.read_text()); state['Sessions']['A'*64]=dict(User='alice',Expires='2099-01-01T00:00:00+00:00'); self.write_pc(state)
        self.copy(); loaded=tool.load_sd(self.sd); self.assertEqual(loaded.state['sessions'],[])
        state=json.loads(self.pc.read_text()); state['Sites']={}; self.write_pc(state)
        self.copy('to-computer'); self.assertEqual(json.loads(self.pc.read_text())['Sessions'],state['Sessions'])
        self.assertNotIn(PASSWORD, ''.join(p.read_text() for p in (self.sd/'bww').rglob('*.json')))
    def test_conflicting_credentials_or_domain_owner_refuse_without_writes(self):
        self.copy(); before=self.card_bytes()
        self.write_pc(store(users={'alice':account(salt=b'different-salt!!')}))
        with self.assertRaisesRegex(tool.CopyError,'Account conflict'): tool.plan_copy(self.pc,self.sd)
        self.assertEqual(self.card_bytes(),before)
        self.write_pc(store(users={'bob':account('bob')},sites={'garden.bww':site(owner='bob')}))
        with self.assertRaisesRegex(tool.CopyError,'Domain conflict'): tool.plan_copy(self.pc,self.sd)
        self.assertEqual(self.card_bytes(),before)
    def test_card_limits_invalid_stores_and_corrupt_snapshots_fail_without_reset(self):
        self.write_pc(store(sites={f'site-{i}.bww':site(f'site-{i}.bww') for i in range(9)}))
        self.copy(); self.assertEqual(len(tool.load_sd(self.sd).sites),9)
        self.write_pc(store(sites={'garden.bww':site()})); self.copy()
        for path in (self.sd/'bww').glob('state-*.json'): path.write_text('{broken')
        before=self.card_bytes()
        with self.assertRaises(tool.CopyError): tool.plan_copy(self.pc,self.sd)
        self.assertEqual(self.card_bytes(),before)
        self.pc.write_text('{"not":"a store"}')
        with self.assertRaises(tool.CopyError): tool.load_desktop(self.pc)
    def test_copy_more_than_24_sites_uses_sd_catalog_pages(self):
        self.write_pc(store(sites={f'site-{i}.bww':site(f'site-{i}.bww') for i in range(41)}))
        self.copy(); loaded=tool.load_sd(self.sd)
        self.assertEqual(len(loaded.sites),41); self.assertEqual(loaded.state['sites'],[])
        self.assertEqual(loaded.state['catalogPages'],6)
        self.write_pc(store(sites={'site-40.bww':site('site-40.bww',html='updated')}))
        self.copy(); self.assertEqual(len(tool.load_sd(self.sd).sites),41)
        self.assertEqual(tool.load_sd(self.sd).sites['site-40.bww']['html'],'updated')

    def test_fifty_site_quota_round_trips_and_blocks_growth_on_both_hosts(self):
        fifty={f'quota-{i}.bww':site(f'quota-{i}.bww') for i in range(50)}
        self.write_pc(store(sites=fifty)); self.copy()
        exported=self.root/'exported.json'; self.copy('to-computer',exported)
        result=json.loads(exported.read_text()); self.assertEqual(len(result['Sites']),50)
        self.assertEqual(result['Users'],json.loads(self.pc.read_text())['Users'])
        self.assertEqual(result['Sites']['quota-49.bww']['Html'],fifty['quota-49.bww']['Html'])
        extra=dict(fifty); extra['extra.bww']=site('extra.bww'); self.write_pc(store(sites=extra))
        before=self.card_bytes()
        with self.assertRaisesRegex(tool.CopyError,'50 sites'): tool.plan_copy(self.pc,self.sd)
        self.assertEqual(self.card_bytes(),before)
        # Simulate a valid pre-quota 0.6.0 card; the new tool must read it but
        # must not grow a fresh PC account beyond fifty.
        with patch.object(tool,'ACCOUNT_SITE_LIMIT',1000): self.copy()
        over=self.card_bytes(); fresh=self.root/'fresh.json'
        with self.assertRaisesRegex(tool.CopyError,'50 sites'): tool.plan_copy(fresh,self.sd,'to-computer')
        self.assertFalse(fresh.exists()); self.assertEqual(self.card_bytes(),over)
        extra['extra.bww']=site('extra.bww',html='edited existing over-quota site')
        self.write_pc(store(sites=extra)); self.copy()
        self.assertEqual(tool.load_sd(self.sd).sites['extra.bww']['html'],'edited existing over-quota site')
        # Existing PC collections over the quota can also be updated without
        # silently deleting or rejecting their existing websites.
        stale=dict(extra); stale['extra.bww']=site('extra.bww',html='stale PC contents')
        self.write_pc(store(sites=stale)); self.copy('to-computer',self.pc)
        restored=json.loads(self.pc.read_text()); self.assertEqual(len(restored['Sites']),51)
        self.assertEqual(restored['Sites']['extra.bww']['Html'],'edited existing over-quota site')

    def test_desktop_collection_above_64mib_can_be_read_with_fifty_valid_sites(self):
        html='💚'*(524288//4)
        # Escaped Unicode makes this valid fifty-site JSON store exceed 64 MiB,
        # even though every website remains within its 512 KiB asset limit.
        with self.pc.open('w',encoding='utf-8') as out:
            out.write('{"Users":'+json.dumps({'alice':account()})+',"Sessions":{},"Sites":{')
            for i in range(50):
                if i: out.write(',')
                domain=f'unicode-{i}.bww'; value=site(domain,html=html); value['Css']=value['Js']=''
                out.write(json.dumps(domain)+':'+json.dumps(value))
            out.write('}}')
        self.assertGreater(self.pc.stat().st_size,64*1024*1024)
        loaded=tool.load_desktop(self.pc)
        self.assertEqual(len(loaded.sites),50); self.assertEqual(loaded.sites['unicode-49.bww']['html'],html)

    def test_preview_changes_backup_inside_card_and_symlinks_are_rejected(self):
        plan=tool.plan_copy(self.pc,self.sd); self.write_pc(store(sites={'changed.bww':site('changed.bww')}))
        with self.assertRaisesRegex(tool.CopyError,'changed since preview'): tool.apply_copy(plan,self.backups)
        self.assertFalse((self.sd/'bww').exists())
        plan=tool.plan_copy(self.pc,self.sd)
        with self.assertRaises(tool.CopyError): tool.apply_copy(plan,self.sd/'backups')
        if os.name!='nt':
            outside=self.root/'outside'; outside.mkdir(); (self.sd/'bww').symlink_to(outside,target_is_directory=True)
            with self.assertRaisesRegex(tool.CopyError,'symbolic link'): tool.plan_copy(self.pc,self.sd)
            self.assertEqual(list(outside.iterdir()),[])
    def test_failed_snapshot_commit_keeps_old_readable_site_and_backup(self):
        self.copy(); self.write_pc(store(sites={'garden.bww':site(html='new')}))
        real=tool.atomic_write
        def fail(path,data):
            if path.name.startswith('state-'): raise OSError('Simulated full SD card')
            real(path,data)
        with patch.object(tool,'atomic_write',side_effect=fail):
            with self.assertRaisesRegex(tool.CopyError,'Backup:'): self.copy()
        self.assertEqual(tool.load_sd(self.sd).sites['garden.bww']['html'],'<h1>💚</h1>')
        self.assertTrue(any((p/'bww').exists() for p in self.backups.iterdir()))
        self.copy()
        self.assertEqual(tool.load_sd(self.sd).sites['garden.bww']['html'],'new')
    def test_cli_preview_and_apply_then_repeat_make_no_unnecessary_changes(self):
        command=[sys.executable,str(ROOT/'bww_sd_copy.py'),'--computer',str(self.pc),'--sd',str(self.sd),'--backup-dir',str(self.backups)]
        result=subprocess.run(command,capture_output=True,text=True); self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('Preview only',result.stdout); self.assertFalse((self.sd/'bww').exists())
        result=subprocess.run(command+['--apply'],capture_output=True,text=True); self.assertEqual(result.returncode,0,result.stderr)
        before=self.card_bytes(); result=subprocess.run(command+['--apply'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr); self.assertIn('No changes needed',result.stdout); self.assertEqual(before,self.card_bytes())
    @unittest.skipUnless(HARNESS,'Native firmware harness is not configured')
    def test_real_cpp_core_reads_import_and_authenticates_original_password(self):
        data=site(html='abcd💚'*(524288//8)); data['Css']=data['Js']=''
        self.write_pc(store(sites={'garden.bww':data})); self.copy()
        process=subprocess.Popen([HARNESS,str(self.sd)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def call(op,**fields):
            process.stdin.write(json.dumps(dict(op=op,**fields))+'\n'); process.stdin.flush()
            response=json.loads(process.stdout.readline()); self.assertTrue(response['ok'],response); return response['data']
        try:
            self.assertEqual(call('login',username='alice',password=PASSWORD)['username'],'alice')
            meta=call('get',domain='garden'); output=bytearray()
            for i in range(len(meta['chunks']['html'])):
                output.extend(bytes.fromhex(call('get_chunk',domain='garden',revision=meta['revision'],asset='html',index=i)['data']))
            self.assertEqual(output.decode(),data['Html'])
        finally:
            process.stdin.close(); process.wait(timeout=10); process.stdout.close(); process.stderr.close()
        # Preserve a firmware-issued destination session during a subsequent update.
        previous=tool.load_sd(self.sd).state['sessions']; self.write_pc(store(sites={'garden.bww':site(html='second import')})); self.copy()
        self.assertEqual(tool.load_sd(self.sd).state['sessions'],previous)
    @unittest.skipUnless(HARNESS,'Native firmware harness is not configured')
    def test_legacy_firmware_json_control_characters_and_passwords_export_correctly(self):
        process=subprocess.Popen([HARNESS,str(self.sd)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        def call(op,**fields):
            process.stdin.write(json.dumps(dict(op=op,**fields))+'\n'); process.stdin.flush()
            response=json.loads(process.stdout.readline(),strict=False); self.assertTrue(response['ok'],response); return response['data']
        content='<p>🌿\0\x01\n</p>'
        try:
            token=call('register',username='alice',password=PASSWORD)['token']
            call('publish',token=token,domain='legacy',html=content,css='',js='')
        finally:
            process.stdin.close(); process.wait(timeout=10); process.stdout.close(); process.stderr.close()
        self.assertEqual(tool.load_sd(self.sd).sites['legacy.bww']['html'],content)
        exported=self.root/'legacy-computer'/'store.json'; self.copy('to-computer',exported)
        self.assertEqual(json.loads(exported.read_text())['Sites']['legacy.bww']['Html'],content)
    @unittest.skipUnless(DOTNET and DLL.is_file(),'Built desktop server/.NET is not configured')
    def test_real_csharp_server_reads_sd_export_and_login_works(self):
        self.copy(); self.write_pc(store(sites={}))
        self.copy('to-computer')
        with socket.socket() as probe: probe.bind(('127.0.0.1',0)); port=probe.getsockname()[1]
        process=subprocess.Popen([DOTNET,str(DLL),'--tcp','--port',str(port),'--data',str(self.pc)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        try:
            for _ in range(100):
                if process.poll() is not None: self.fail('Desktop server failed to read exported store')
                try: connection=socket.create_connection(('127.0.0.1',port),timeout=.2); break
                except OSError: time.sleep(.05)
            else: self.fail('Desktop server did not start')
            with connection, connection.makefile('rwb') as wire:
                def call(op,**fields):
                    wire.write((json.dumps(dict(op=op,**fields))+'\n').encode()); wire.flush()
                    response=json.loads(wire.readline()); self.assertTrue(response['ok'],response); return response['data']
                self.assertEqual(call('login',username='alice',password=PASSWORD)['username'],'alice')
                self.assertEqual(call('get',domain='garden')['html'],'<h1>💚</h1>')
                plan=tool.plan_copy(self.pc,self.sd)
                # Force a valid pending site rewrite so apply reaches the shared lock.
                plan.updated_sites.append('garden.bww')
                before=self.card_bytes()
                with self.assertRaisesRegex(tool.CopyError,'server|using'): tool.apply_copy(plan,self.backups)
                self.assertEqual(before,self.card_bytes())
        finally: process.terminate(); process.wait(timeout=10)

if __name__=='__main__': unittest.main(verbosity=2)
