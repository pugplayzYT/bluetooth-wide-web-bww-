#!/usr/bin/env python3
"""Decode CI signing secrets privately, build a release APK and verify its certificate."""
import base64
import os
from pathlib import Path
import re
import subprocess
import tempfile
import argparse

ROOT = Path(__file__).resolve().parents[1]

def build(gradle, extra, apksigner):
    required = ('BWW_ANDROID_KEYSTORE_BASE64', 'BWW_ANDROID_STORE_PASSWORD', 'BWW_ANDROID_KEY_ALIAS', 'BWW_ANDROID_KEY_PASSWORD')
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise SystemExit('Release signing is not configured. Add GitHub Actions secrets: ' + ', '.join(missing) + '. See ANDROID_SIGNING.md; no unsigned APK will be published.')
    with tempfile.TemporaryDirectory(prefix='bww-signing-') as folder:
        key = Path(folder)/'release.p12'
        key.write_bytes(base64.b64decode(os.environ['BWW_ANDROID_KEYSTORE_BASE64'], validate=True))
        key.chmod(0o600)
        env = os.environ.copy()
        env.pop('BWW_ANDROID_KEYSTORE_BASE64', None)
        env['BWW_ANDROID_KEYSTORE'] = str(key)
        subprocess.run([gradle, '--no-daemon', *extra, 'assembleRelease'], cwd=ROOT/'android', env=env, check=True)
    apk = ROOT/'android/app/build/outputs/apk/release/app-release.apk'
    report = subprocess.run([apksigner, 'verify', '--print-certs', str(apk)], check=True, capture_output=True, text=True).stdout
    actual = re.search(r'certificate SHA-256 digest: ([a-f0-9]+)', report)
    expected = (ROOT/'android/signing-certificate.sha256').read_text().strip()
    if not actual or actual.group(1) != expected:
        raise SystemExit('Signing certificate mismatch: release publication stopped. See ANDROID_SIGNING.md.')
    print('Release APK verified with the pinned public signing certificate.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--gradle', default=str(ROOT/'android/gradlew'))
    parser.add_argument('--gradle-arg', action='append', default=[])
    parser.add_argument('--apksigner', default=str(Path(os.environ.get('ANDROID_HOME', ''))/'build-tools/35.0.0/apksigner'))
    args = parser.parse_args()
    build(args.gradle, args.gradle_arg, args.apksigner)
