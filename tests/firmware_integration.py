"""Exercise the ESP32's actual C++ protocol/storage core on a native filesystem."""
import json, os, pathlib, subprocess, tempfile, unittest
HARNESS = os.environ.get('BWW_FIRMWARE_HARNESS', '/tmp/bww-firmware-harness')
class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.root = pathlib.Path(self.temp.name); self.start()
    def start(self):
        self.process = subprocess.Popen([HARNESS, str(self.root)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    def stop(self):
        if self.process.stdin: self.process.stdin.close()
        self.process.wait(timeout=10)
        self.process.stdout.close(); self.process.stderr.close()
    def tearDown(self):
        if self.process.poll() is None: self.stop()
        self.temp.cleanup()
    def call(self, op, **fields):
        self.process.stdin.write(json.dumps(dict(op=op, **fields)) + '\n'); self.process.stdin.flush()
        line = self.process.stdout.readline()
        self.assertTrue(line, 'Firmware harness stopped unexpectedly')
        return json.loads(line)
    def ok(self, op, **fields):
        reply = self.call(op, **fields); self.assertTrue(reply['ok'], reply); return reply['data']
    def error(self, code, op, **fields):
        reply = self.call(op, **fields); self.assertFalse(reply['ok'], reply); self.assertEqual(reply['error'], code)
    def register(self, name='alice'):
        return self.ok('register', username=name, password='correct horse battery')['token']
    def publish(self, token, domain='garden', html='<h1>Hello</h1>'):
        return self.ok('publish', token=token, domain=domain, html=html, css='h1{color:green}', js="localStorage.setItem('score','42')")
    def control(self, **fields):
        self.process.stdin.write(json.dumps(fields)+'\n'); self.process.stdin.flush()
        self.assertTrue(json.loads(self.process.stdout.readline())['ok'])
    def test_wire_framing_rejects_trailing_json_and_recovers_on_next_line(self):
        for line in ['{bad json}', '{"op":"hello"} {"op":"list"}', '[]', '{"op":"hello"}garbage']:
            self.process.stdin.write(line+'\n'); self.process.stdin.flush()
            self.assertFalse(json.loads(self.process.stdout.readline())['ok'])
        self.assertEqual(self.ok('hello')['protocol'],1)
        self.process.stdin.write('{"op":"hello"}\n{"op":"list"}\n'); self.process.stdin.flush()
        self.assertTrue(json.loads(self.process.stdout.readline())['ok'])
        self.assertTrue(json.loads(self.process.stdout.readline())['ok'])
    def test_accounts_ownership_and_all_operations(self):
        self.assertEqual(self.ok('hello')['maxSiteBytes'],16384)
        self.error('weak_password','register',username='short',password='tiny')
        alice = self.register(); bob = self.register('bob')
        self.error('username_taken','register',username='ALICE',password='correct horse battery')
        self.error('invalid_credentials','login',username='alice',password='wrong')
        self.assertTrue(self.ok('available',domain='GARDEN.bww')['available'])
        self.publish(alice)
        self.assertFalse(self.ok('available',domain='garden')['available'])
        self.error('domain_taken','publish',token=bob,domain='garden',html='overwrite',css='',js='')
        self.error('forbidden','delete',token=bob,domain='garden')
        self.assertEqual(self.ok('get',domain='garden')['owner'],'alice')
        self.assertEqual(self.ok('list')[0]['domain'],'garden.bww')
        self.assertEqual(self.ok('mine',token=alice)[0]['domain'],'garden.bww')
        self.ok('logout',token=alice); self.error('unauthorized','me',token=alice)
        alice = self.ok('login',username='alice',password='correct horse battery')['token']
        self.publish(alice,html='<h1>Updated</h1>')
        self.assertEqual(self.ok('get',domain='garden')['html'],'<h1>Updated</h1>')
        self.ok('delete',token=alice,domain='garden'); self.error('not_found','get',domain='garden')
    def test_sites_and_sessions_survive_reboot_without_plaintext_credentials(self):
        token = self.register(); self.publish(token)
        for path in (self.root/'bww').rglob('*.json'):
            text = path.read_text(); self.assertNotIn(token,text); self.assertNotIn('correct horse battery',text)
        self.stop(); self.start()
        self.assertEqual(self.ok('me',token=token)['username'],'alice')
        self.assertEqual(self.ok('get',domain='garden')['html'],'<h1>Hello</h1>')
    def test_powered_time_expiry_is_persistent(self):
        token = self.register(); self.control(_test='advance',seconds=2592001)
        self.error('unauthorized','me',token=token)
        self.stop(); self.start(); self.error('unauthorized','me',token=token)
    def test_sd_write_failure_rolls_back_without_losing_the_previous_site(self):
        token = self.register(); self.publish(token)
        self.control(_test='fail_next_state')
        self.error('storage_error','publish',token=token,domain='garden',html='bad replacement',css='',js='')
        self.assertEqual(self.ok('get',domain='garden')['html'],'<h1>Hello</h1>')
        self.stop(); self.start(); self.assertEqual(self.ok('get',domain='garden')['html'],'<h1>Hello</h1>')
    def test_valid_previous_snapshot_recovers_a_truncated_latest_manifest(self):
        token = self.register(); self.publish(token); self.publish(token,html='new generation')
        self.stop()
        slots=list((self.root/'bww').glob('state-*.json'))
        newest=max(slots,key=lambda p:json.loads(p.read_text())['generation']); newest.write_text('{truncated')
        self.start(); self.assertEqual(self.ok('get',domain='garden')['html'],'<h1>Hello</h1>')
    def test_two_corrupt_manifests_do_not_reset_or_start_the_server(self):
        token = self.register(); self.publish(token); self.stop()
        for p in (self.root/'bww').glob('state-*.json'): p.write_text('{damaged')
        result=subprocess.run([HARNESS,str(self.root)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,2)
        self.assertTrue((self.root/'bww/sites').is_dir())
    def test_invalid_domains_payloads_and_size_limits(self):
        token = self.register()
        for domain in ['../secret','-bad','bad-','a.b','a'*64,'bad\n.bww']:
            self.error('invalid_domain','available',domain=domain)
        self.error('unknown_operation','unknown')
        self.error('invalid_request','get',domain=42)
        self.error('empty_site','publish',token=token,domain='empty',html='   ',css='',js='')
        self.error('too_large','publish',token=token,domain='large',html='a'*16384,css='a',js='')
        html='💚' * 4000
        self.ok('publish',token=token,domain='unicode',html=html,css='',js='')
        self.assertEqual(self.ok('get',domain='unicode')['html'],html)
    def test_session_and_site_quotas_remain_bounded(self):
        first = self.register()
        for _ in range(4): self.ok('login',username='alice',password='correct horse battery')
        self.error('unauthorized','me',token=first)
        active=self.ok('login',username='alice',password='correct horse battery')['token']
        for i in range(8): self.publish(active,domain=f'site-{i}')
        self.error('capacity','publish',token=active,domain='site-9',html='hi',css='',js='')
        self.publish(active,domain='site-0',html='updated at quota')
    def test_site_corruption_returns_error_and_owner_can_repair_it(self):
        token = self.register(); self.publish(token)
        site = next((self.root/'bww/sites').glob('*.json'))
        data=json.loads(site.read_text()); data['data']['html']='changed without checksum'; site.write_text(json.dumps(data))
        self.error('storage_error','get',domain='garden')
        self.publish(token,html='repaired'); self.assertEqual(self.ok('get',domain='garden')['html'],'repaired')
if __name__ == '__main__': unittest.main(verbosity=2)
