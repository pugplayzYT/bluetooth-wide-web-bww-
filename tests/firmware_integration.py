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
    def begin_upload(self, token, domain='large'):
        return self.ok('publish_begin',token=token,domain=domain)['transfer']
    def chunk(self, token, transfer, asset, index, content):
        if isinstance(content,str): content=content.encode()
        return self.ok('publish_chunk',token=token,transfer=transfer,asset=asset,index=index,data=content.hex())
    def chunked_site(self, token, domain='large', html='hello', css='', js=''):
        transfer=self.begin_upload(token,domain)
        for asset, content in [('html',html),('css',css),('js',js)]:
            # Split by characters so every request is independently valid UTF-8.
            pending=bytearray(); index=0
            for char in content:
                encoded=char.encode()
                if len(pending)+len(encoded)>8192:
                    self.chunk(token,transfer,asset,index,pending); index+=1; pending.clear()
                pending.extend(encoded)
            if pending: self.chunk(token,transfer,asset,index,pending)
        self.ok('publish_commit',token=token,transfer=transfer)
        return transfer
    def load_chunks(self, domain):
        metadata=self.ok('get',domain=domain); output={}
        for asset, chunks in metadata['chunks'].items():
            content=bytearray()
            for i, item in enumerate(chunks):
                raw=bytes.fromhex(self.ok('get_chunk',domain=domain,revision=metadata['revision'],asset=asset,index=i)['data'])
                self.assertEqual(len(raw),item['bytes']); content.extend(raw)
            output[asset]=content.decode()
        return output
    def test_full_512kib_unicode_site_survives_reboot_using_bounded_chunks(self):
        token=self.register(); html='abcd💚'*(524288//8)
        self.chunked_site(token,html=html)
        self.assertEqual(self.load_chunks('large')['html'],html)
        self.assertTrue(all(p.stat().st_size <= 8192 for p in (self.root/'bww/sites').glob('*.bin')))
        self.assertTrue(all(p.stat().st_size < 24576 for p in (self.root/'bww/sites').glob('*.json')))
        self.stop(); self.start()
        self.assertEqual(self.load_chunks('large')['html'],html)
        transfer=self.begin_upload(token,'too-large')
        for i in range(64): self.chunk(token,transfer,'html',i,'a'*8192)
        self.error('too_large','publish_chunk',token=token,transfer=transfer,asset='css',index=0,data='61')
        self.assertTrue(self.ok('available',domain='too-large')['available'])
        self.ok('publish_cancel',token=token,transfer=transfer)
    def test_three_interleaved_uploads_are_isolated_and_fourth_is_rejected(self):
        token=self.register(); tokens=[token]+[self.ok('login',username='alice',password='correct horse battery')['token'] for _ in range(3)]
        transfers=[self.begin_upload(tokens[i],f'parallel-{i}') for i in range(3)]
        self.error('capacity','publish_begin',token=tokens[3],domain='fourth')
        for i in range(3): self.chunk(tokens[i],transfers[i],'html',0,f'phone-{i}')
        self.error('upload_missing','publish_chunk',token=tokens[1],transfer=transfers[0],asset='html',index=1,data='61')
        self.error('invalid_request','publish_chunk',token=tokens[0],transfer=transfers[0],asset='html',index=0,data='61')
        for i in [2,0,1]: self.ok('publish_commit',token=tokens[i],transfer=transfers[i])
        for i in range(3): self.assertEqual(self.load_chunks(f'parallel-{i}')['html'],f'phone-{i}')
        self.begin_upload(tokens[3],'fourth')
    def test_chunk_upload_collision_checks_owner_at_commit(self):
        alice=self.register(); bob=self.register('bob')
        a=self.begin_upload(alice,'collision'); b=self.begin_upload(bob,'collision')
        self.chunk(alice,a,'html',0,'Alice'); self.chunk(bob,b,'html',0,'Bob')
        self.ok('publish_commit',token=alice,transfer=a)
        self.error('domain_taken','publish_commit',token=bob,transfer=b)
        self.assertEqual(self.load_chunks('collision')['html'],'Alice')
    def test_chunk_failure_and_previous_snapshot_recovery_keep_old_files(self):
        token=self.register(); self.chunked_site(token,html='original')
        transfer=self.begin_upload(token); self.chunk(token,transfer,'html',0,'replacement')
        self.control(_test='fail_next_state'); self.error('storage_error','publish_commit',token=token,transfer=transfer)
        self.assertEqual(self.load_chunks('large')['html'],'original')
        self.ok('publish_commit',token=token,transfer=transfer)
        self.assertEqual(self.load_chunks('large')['html'],'replacement')
        self.stop(); slots=list((self.root/'bww').glob('state-*.json'))
        newest=max(slots,key=lambda p:json.loads(p.read_text())['generation']); newest.write_text('{truncated')
        self.start(); self.assertEqual(self.load_chunks('large')['html'],'original')
    def test_upload_expiry_cancel_and_corrupted_chunk_fail_safely(self):
        token=self.register(); transfer=self.begin_upload(token)
        self.chunk(token,transfer,'html',0,'unfinished')
        self.control(_test='advance',seconds=301)
        self.error('upload_missing','publish_commit',token=token,transfer=transfer)
        self.assertFalse(list((self.root/'bww/sites').glob('*.bin')))
        self.chunked_site(token,html='published')
        metadata=self.ok('get',domain='large')
        chunk=next((self.root/'bww/sites').glob('*.bin')); chunk.write_text('corrupted')
        self.error('storage_error','get_chunk',domain='large',revision=metadata['revision'],asset='html',index=0)
        self.chunked_site(token,html='repaired'); self.assertEqual(self.load_chunks('large')['html'],'repaired')
        self.error('site_changed','get_chunk',domain='large',revision=metadata['revision'],asset='html',index=0)
    def test_invalid_chunks_empty_html_and_abandoned_upload_after_reboot(self):
        token=self.register(); transfer=self.begin_upload(token)
        for data in ['zz','f','c0af','',('61'*8193)]:
            self.error('too_large' if len(data)>16384 else 'invalid_request','publish_chunk',token=token,transfer=transfer,asset='html',index=0,data=data)
        self.chunk(token,transfer,'html',0,'   ')
        self.error('empty_site','publish_commit',token=token,transfer=transfer)
        self.stop(); self.start()
        self.error('upload_missing','publish_commit',token=token,transfer=transfer)
        self.assertFalse(list((self.root/'bww/sites').glob('*.bin')))
    def test_chunk_verification_buffer_is_freed_before_state_commit(self):
        token = self.register()
        self.control(_test='guard_commit_chunk')
        for generation in range(3):
            text = 'x' * 8192 + str(generation)
            self.chunked_site(token, domain='commit-memory', html=text)
            self.assertEqual(self.load_chunks('commit-memory')['html'], text)
        self.stop(); self.start()
        self.assertEqual(self.load_chunks('commit-memory')['html'], 'x' * 8192 + '2')

    def test_state_commit_allows_the_reported_fragmented_heap(self):
        token = self.register()
        # Use the production file-open policy at the exact reported heap values.
        self.control(_test='fragmented_state_reads')
        self.chunked_site(token, domain='fragmented', html='x' * 8192)
        self.assertEqual(self.load_chunks('fragmented')['html'], 'x' * 8192)
        self.stop(); self.start()
        self.assertEqual(self.load_chunks('fragmented')['html'], 'x' * 8192)

    def test_cleanup_uses_one_temporary_json_buffer_and_preserves_generations(self):
        token = self.register()
        self.control(_test='memory_budget', bytes=65536)
        for generation in range(5):
            self.chunked_site(token, domain='memory', html=('x' * 8192) * 4 + str(generation))
            self.assertEqual(self.load_chunks('memory')['html'], ('x' * 8192) * 4 + str(generation))
        stats = self.ok('unused', _test='memory_stats')
        self.assertEqual(stats['rejected'], 0)
        self.assertLessEqual(stats['peak'], 65536)
        self.assertEqual(stats['live'], 40960)
        # A reboot keeps current and fallback generations, and drops old ones.
        self.stop(); self.start()
        self.assertEqual(self.load_chunks('memory')['html'], ('x' * 8192) * 4 + '4')
        self.assertEqual(len(list((self.root/'bww/sites').glob('*.json'))), 2)

    def test_cleanup_streams_many_orphans_and_preserves_live_and_staged_chunks(self):
        token = self.register()
        self.chunked_site(token, domain='retained', html='keep me')
        transfer = self.begin_upload(token, 'staged')
        self.chunk(token, transfer, 'html', 0, 'unfinished')
        directory = self.root/'bww/sites'
        staged = directory / (transfer + '.html.0.bin')
        for index in range(1500): (directory / ('0' * 32 + '.html.' + str(index) + '.bin')).write_text('orphan')
        # Starting another upload runs cleanup while the first remains staged.
        self.ok('register', username='bob', password='correct horse battery')
        self.assertTrue(staged.exists())
        self.assertFalse(list(directory.glob(('0' * 32) + '*.bin')))
        self.assertEqual(self.load_chunks('retained')['html'], 'keep me')
        self.ok('publish_commit', token=token, transfer=transfer)
        self.assertEqual(self.load_chunks('staged')['html'], 'unfinished')

    def test_cleanup_skips_deletion_when_retained_metadata_is_unreadable(self):
        token = self.register()
        self.chunked_site(token, html='keep me')
        metadata = self.ok('get', domain='large')
        path = self.root/'bww/sites'/('large.bww.' + str(metadata['revision']) + '.json')
        original = path.read_bytes(); path.write_text('{broken')
        orphan = self.root/'bww/sites'/('0' * 32 + '.html.0.bin'); orphan.write_text('keep until metadata readable')
        self.begin_upload(token, 'another')
        self.assertTrue(orphan.exists())
        path.write_bytes(original)
        self.begin_upload(token, 'another')
        self.assertFalse(orphan.exists())
        self.assertEqual(self.load_chunks('large')['html'], 'keep me')

    def test_wire_framing_rejects_trailing_json_and_recovers_on_next_line(self):
        for line in ['{bad json}', '{"op":"hello"} {"op":"list"}', '[]', '{"op":"hello"}garbage']:
            self.process.stdin.write(line+'\n'); self.process.stdin.flush()
            self.assertFalse(json.loads(self.process.stdout.readline())['ok'])
        self.assertEqual(self.ok('hello')['protocol'],1)
        self.process.stdin.write('{"op":"hello"}\n{"op":"list"}\n'); self.process.stdin.flush()
        self.assertTrue(json.loads(self.process.stdout.readline())['ok'])
        self.assertTrue(json.loads(self.process.stdout.readline())['ok'])
    def test_accounts_ownership_and_all_operations(self):
        self.assertEqual(self.ok('hello')['maxSiteBytes'],524288)
        self.assertEqual(self.ok('hello')['maxBtClients'],3)
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
