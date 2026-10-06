#!/usr/bin/env python3
"""Install a private signing bundle as GitHub Actions secrets without printing values."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

def configure(bundle, repo, keytool):
    credentials = json.loads((bundle/'credentials.json').read_text())
    key = bundle/'bww-release.p12'
    env = os.environ.copy()
    env['BWW_SETUP_STORE_PASSWORD'] = credentials['storePassword']
    cert = subprocess.run([keytool, '-exportcert', '-keystore', str(key), '-alias', credentials['alias'],
        '-storepass:env', 'BWW_SETUP_STORE_PASSWORD'], env=env, capture_output=True, check=True).stdout
    expected = (bundle/'certificate.sha256').read_text().strip()
    if hashlib.sha256(cert).hexdigest() != expected:
        raise SystemExit('Bundle signing certificate mismatch; nothing uploaded.')
    subprocess.run(['gh', 'auth', 'status'], check=True)
    values = {'BWW_ANDROID_KEYSTORE_BASE64': base64.b64encode(key.read_bytes()).decode(),
        'BWW_ANDROID_STORE_PASSWORD': credentials['storePassword'],
        'BWW_ANDROID_KEY_ALIAS': credentials['alias'],
        'BWW_ANDROID_KEY_PASSWORD': credentials['keyPassword']}
    for name, value in values.items():
        subprocess.run(['gh', 'secret', 'set', name, '--repo', repo], input=value, text=True, check=True)
        print('Configured ' + name)
    print('All four signing secrets are configured. Run the Build and test workflow on main.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, default=Path.cwd())
    parser.add_argument('--repo', required=True, help='Target repository OWNER/NAME; use your own fork')
    parser.add_argument('--keytool', default=shutil.which('keytool') or 'keytool')
    args=parser.parse_args()
    configure(args.bundle,args.repo,args.keytool)
