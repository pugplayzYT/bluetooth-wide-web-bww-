"""Release regressions: isolated jobs, corruption rejection and immutable app versions."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
def module(name):
    spec=importlib.util.spec_from_file_location(name, ROOT/'scripts'/f'{name}.py')
    result=importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result
pack=module('package_downloads'); publish=module('publish_downloads')

class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.build=self.root/'build'; self.fw=self.root/'firmware'; self.out=self.root/'out'
        self.build.mkdir(); self.fw.mkdir()
        self.b={'files':{}, 'android':{'version':'1.0.1','versionCode':2,'file':'app.apk','certificateSha256':'a'*64,'sourceHash':'b'*64}, 'windows':{'version':'1.0','file':'pc.zip'}, 'sdCopy':{'file':'sd.zip'}}
        self.f={'files':{},'firmware':{'version':'1.0','sourceFile':'source.zip','binaryFile':'firmware.zip'}}
        for directory,manifest,names in ((self.build,self.b,('app.apk','pc.zip','sd.zip')),(self.fw,self.f,('source.zip','firmware.zip'))):
            for name in names:
                data=(name+'-current').encode();(directory/name).write_bytes(data)
                manifest['files'][name]=hashlib.sha256(data).hexdigest()
        self.b['android']['sha256']=self.b['files']['app.apk']; self.save()
    def tearDown(self): self.temp.cleanup()
    def save(self):
        (self.build/'build-manifest.json').write_text(json.dumps(self.b))
        (self.fw/'firmware-manifest.json').write_text(json.dumps(self.f))
    def test_latest_index_and_disjoint_packages(self):
        publish.merge(self.build,self.fw,self.out)
        for name in self.b['files']:self.assertEqual((self.out/name).read_bytes(),(self.build/name).read_bytes())
        for name in self.f['files']:self.assertEqual((self.out/name).read_bytes(),(self.fw/name).read_bytes())
        self.assertIn('Android 1.0.1',(self.out/'README.md').read_text())
        self.assertIn('/app.apk',(self.out/'README.md').read_text())
        self.assertEqual(5,len((self.out/'SHA256SUMS.txt').read_text().splitlines()))
    def test_overlapping_artifacts_rejected_before_writing(self):
        self.f['files']['app.apk']=self.b['files']['app.apk'];self.save()
        with self.assertRaisesRegex(ValueError,'overlapping'):publish.merge(self.build,self.fw,self.out)
        self.assertFalse(self.out.exists())
    def test_corrupt_package_rejected_before_writing(self):
        (self.fw/'firmware.zip').write_bytes(b'corrupted')
        with self.assertRaisesRegex(ValueError,'integrity'):publish.merge(self.build,self.fw,self.out)
        self.assertFalse(self.out.exists())
    def test_missing_package_rejected(self):
        (self.build/'pc.zip').unlink()
        with self.assertRaisesRegex(ValueError,'integrity'):publish.merge(self.build,self.fw,self.out)
    def test_invalid_path_rejected(self):
        self.b['sdCopy']['file']='../sd.zip';self.b['files']['../sd.zip']=self.b['files'].pop('sd.zip');self.save()
        with self.assertRaisesRegex(ValueError,'Invalid package name'):publish.merge(self.build,self.fw,self.out)

class AppVersionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.original=pack.ROOT;pack.ROOT=self.root
        self.output=self.root/'isolated'
        for name in ('android/app/build/outputs/apk/release','artifacts/windows-x64','esp32/include','downloads'):(self.root/name).mkdir(parents=True)
        self.write('android/app/build.gradle',"versionName '1.0.1'\nversionCode 2\n")
        self.write('android/signing-certificate.sha256','a'*64)
        self.write('esp32/include/BwwConfig.h','FIRMWARE_VERSION = "1.0.0"')
        for name in ('Sync-BWW.bat','SYNC_README.md','VALIDATION.md','bww_sd_copy.py','BWW_SD_COPY_README.md','Run-BWW-SD-Copy.bat'):self.write(name,'fixture')
        (self.root/'android/app/build/outputs/apk/release/app-release.apk').write_bytes(b'new-apk')
        (self.root/'artifacts/windows-x64/Bww.Server.exe').write_bytes(b'MZ-exe')
        self.signer=self.root/'verify';self.signer.write_text('#!/usr/bin/env python3\nprint("Signer #1 certificate SHA-256 digest: '+ 'a'*64 + '")\n');self.signer.chmod(0o755)
    def write(self,name,text):(self.root/name).write_text(text)
    def tearDown(self):pack.ROOT=self.original;self.temp.cleanup()
    def published(self):
        pack.package(self.output,str(self.signer))
        b=json.loads((self.output/'build-manifest.json').read_text())
        self.write('downloads/release-manifest.json',json.dumps({'android':b['android']}))
        (self.root/'downloads/Bww-Android-1.0.1.apk').write_bytes((self.output/'Bww-Android-1.0.1.apk').read_bytes())
    def test_code_fix_requires_new_version(self):
        self.published();self.write('android/app/build.gradle',"versionName '1.0.1'\nversionCode 2\n// changed build inputs\n")
        with self.assertRaisesRegex(ValueError,'bump versionName'):pack.package(self.output,str(self.signer))
    def test_unchanged_version_reuses_published_signed_apk(self):
        self.published();(self.root/'android/app/build/outputs/apk/release/app-release.apk').write_bytes(b'rebuilt-different-timestamps')
        pack.package(self.output,str(self.signer))
        self.assertEqual(b'new-apk',(self.output/'Bww-Android-1.0.1.apk').read_bytes())
        self.assertEqual({'Bww-Android-1.0.1.apk','Bww-Windows-Sync-1.0.0.zip','Bww-SD-Copy.zip','build-manifest.json'},{p.name for p in self.output.iterdir()})
    def test_wrong_signing_certificate_rejected(self):
        self.write('android/signing-certificate.sha256','c'*64)
        with self.assertRaisesRegex(ValueError,'signing certificate'):pack.package(self.output,str(self.signer))
    def test_new_release_requires_higher_version_code(self):
        self.published();self.write('android/app/build.gradle',"versionName '1.0.2'\nversionCode 2\n")
        with self.assertRaisesRegex(ValueError,'increase versionCode'):pack.package(self.output,str(self.signer))

if __name__=='__main__':unittest.main(verbosity=2)
