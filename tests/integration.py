"""Real wire-protocol integration checks; no Bluetooth hardware required."""
import json, os, pathlib, socket, subprocess, tempfile, time, unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOTNET = os.environ.get('BWW_DOTNET', 'dotnet')
DLL = ROOT / 'server/bin/Release/net8.0/Bww.Server.dll'

class ProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.data = pathlib.Path(cls.temp.name) / 'store.json'
        cls.start()
    @classmethod
    def start(cls):
        with socket.socket() as s:
            s.bind(('127.0.0.1',0)); cls.port=s.getsockname()[1]
        cls.log=open(pathlib.Path(cls.temp.name)/'server.log','a')
        cls.proc=subprocess.Popen([DOTNET,str(DLL),'--tcp','--port',str(cls.port),'--data',str(cls.data)],stdout=cls.log,stderr=cls.log)
        for _ in range(100):
            if cls.proc.poll() is not None: raise RuntimeError('Server failed to start')
            try:
                s=socket.create_connection(('127.0.0.1',cls.port),timeout=.2); s.close(); return
            except OSError: time.sleep(.05)
        raise RuntimeError('Server did not become ready')
    @classmethod
    def stop(cls):
        cls.proc.terminate(); cls.proc.wait(timeout=5); cls.log.close()
    @classmethod
    def tearDownClass(cls):
        cls.stop(); cls.temp.cleanup()
    def setUp(self):
        self.sock=socket.create_connection(('127.0.0.1',self.port),timeout=10)
        self.file=self.sock.makefile('rwb')
    def test_06_sync_manifest_and_conditional_publish(self):
        import hashlib
        self.error('unauthorized','sync_manifest',token='invalid')
        token=self.ok('register',username='sync_guard',password='correct horse battery')['token']
        html='a'*8191+'💚'+'b'
        self.ok('publish',token=token,domain='sync-guard',html=html,css='',js='')
        metadata=self.ok('sync_manifest',token=token)[0]
        first=b'a'*8191;last='💚b'.encode()
        manifest='html:'+''.join(f'{len(c)}:{hashlib.sha256(c).hexdigest()},' for c in (first,last))+';css:;js:;'
        self.assertEqual(metadata['fingerprint'],hashlib.sha256(manifest.encode()).hexdigest())
        self.ok('publish',token=token,domain='sync-guard',html='changed',css='',js='')
        self.error('sync_conflict','sync_publish',token=token,domain='sync-guard',expectedFingerprint=metadata['fingerprint'],html='stale copy',css='',js='')
        self.error('sync_conflict','sync_publish',token=token,domain='sync-guard',expectedFingerprint='missing',html='stale copy',css='',js='')
        self.assertEqual(self.ok('get',domain='sync-guard')['html'],'changed')
        current=self.ok('sync_manifest',token=token)[0]['fingerprint']
        self.ok('sync_publish',token=token,domain='sync-guard',expectedFingerprint=current,html='approved copy',css='',js='')
        self.assertEqual(self.ok('get',domain='sync-guard')['html'],'approved copy')
    def tearDown(self): self.file.close(); self.sock.close()
    def call(self,op,**fields):
        self.file.write((json.dumps(dict(op=op,**fields))+'\n').encode()); self.file.flush()
        return json.loads(self.file.readline())
    def ok(self,op,**fields):
        r=self.call(op,**fields); self.assertTrue(r['ok'],r); return r['data']
    def error(self,code,op,**fields):
        r=self.call(op,**fields); self.assertFalse(r['ok'],r); self.assertEqual(r['error'],code)
    def test_01_accounts_sites_and_restart(self):
        self.assertEqual(self.ok('hello')['protocol'],1)
        self.error('weak_password','register',username='alice',password='short')
        alice=self.ok('register',username='alice',password='correct horse battery')['token']
        bob=self.ok('register',username='bob',password='another safe password')['token']
        self.error('username_taken','register',username='ALICE',password='correct horse battery')
        self.error('invalid_credentials','login',username='alice',password='wrong')
        self.assertTrue(self.ok('available',domain='Hello')['available'])
        self.error('unauthorized','publish',token='fake',domain='hello',html='hi',css='',js='')
        fields=dict(domain='hello',html='<h1>Hello</h1>',css='h1 { color: green; }',js="console.log('works')")
        self.ok('publish',token=alice,**fields)
        self.assertFalse(self.ok('available',domain='HELLO.bww')['available'])
        self.error('domain_taken','publish',token=bob,**fields)
        self.error('forbidden','delete',token=bob,domain='hello')
        self.assertEqual(self.ok('get',domain='hello')['html'],fields['html'])
        self.assertEqual(self.ok('mine',token=alice)[0]['domain'],'hello.bww')
        self.ok('publish',token=alice,**dict(fields,html='<h1>Updated</h1>'))
        self.assertEqual(self.ok('list')[0]['owner'],'alice')
        persisted=json.loads(self.data.read_text())
        self.assertNotIn(alice,self.data.read_text())
        self.assertNotIn('correct horse battery',self.data.read_text())
        self.assertNotEqual(persisted['Users']['alice']['Salt'],persisted['Users']['bob']['Salt'])
        self.tearDown(); self.stop(); self.start(); self.setUp()
        self.assertEqual(self.ok('me',token=alice)['username'],'alice')
        self.assertEqual(self.ok('get',domain='hello')['html'],'<h1>Updated</h1>')
        self.ok('logout',token=alice)
        self.error('unauthorized','me',token=alice)
        alice=self.ok('login',username='alice',password='correct horse battery')['token']
        self.ok('delete',token=alice,domain='hello')
        self.error('not_found','get',domain='hello')
    def test_02_bad_requests_and_limits(self):
        self.file.write(b'{bad json}\n'); self.file.flush()
        self.assertEqual(json.loads(self.file.readline())['error'],'invalid_json')
        self.file.write(b'[]\n'); self.file.flush()
        self.assertEqual(json.loads(self.file.readline())['error'],'invalid_request')
        self.error('unknown_operation','not-real')
        for domain in ['../secret','-bad','bad-','a.b','a'*64,'https://bad','💥','bad\n.bww','bad\r.bww']:
            self.error('invalid_domain','available',domain=domain)
        for domain in ['a','a-b','9','a'*63]: self.assertTrue(self.ok('available',domain=domain)['available'])
        token=self.ok('register',username='limits',password='password for limits')['token']
        self.error('too_large','publish',token=token,domain='large',html='a'*524288,css='a',js='')
        self.error('empty_site','publish',token=token,domain='empty',html='',css='',js='')
    def test_03_atomic_domain_claim(self):
        a=self.ok('register',username='racer_a',password='safe racing password')['token']
        b=self.ok('register',username='racer_b',password='safe racing password')['token']
        import concurrent.futures
        def publish(token):
            with socket.create_connection(('127.0.0.1',self.port),timeout=10) as s:
                with s.makefile('rwb') as f:
                    f.write((json.dumps(dict(op='publish',token=token,domain='race',html='hi',css='',js=''))+'\n').encode()); f.flush()
                    return json.loads(f.readline())
        with concurrent.futures.ThreadPoolExecutor() as pool: results=list(pool.map(publish,[a,b]))
        self.assertEqual(sum(r['ok'] for r in results),1)
        self.assertEqual([r['error'] for r in results if not r['ok']],['domain_taken'])
    def test_04_expired_session(self):
        token=self.ok('register',username='expired',password='expired session password')['token']
        self.tearDown(); self.stop()
        import hashlib
        state=json.loads(self.data.read_text())
        state['Sessions'][hashlib.sha256(token.encode()).hexdigest().upper()]['Expires']='2000-01-01T00:00:00+00:00'
        self.data.write_text(json.dumps(state)); self.start(); self.setUp()
        self.error('unauthorized','me',token=token)
    def test_05_fragmented_and_multiple_frames(self):
        self.file.write(b'{"op":'); self.file.flush()
        self.file.write(b'"hello"}\n{"op":"list"}\n'); self.file.flush()
        self.assertEqual(json.loads(self.file.readline())['data']['protocol'],1)
        self.assertTrue(json.loads(self.file.readline())['ok'])

if __name__=='__main__': unittest.main(verbosity=2)
