#!/usr/bin/env python3
"""Generate a private signing bundle; optionally initialize a fork's public signing pin."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def create(output, keytool, init_fork=False, application_id=None):
    output=output.expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError('Keep private signing material outside the Git checkout')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Output folder is not empty; existing keys will not be overwritten')
    if application_id and not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',application_id):
        raise ValueError('Use an application ID such as com.yourname.bww')
    gradle=ROOT/'android/app/build.gradle'
    text=gradle.read_text()
    if init_fork:
        match=re.search(r"versionName '([0-9]+)\.([0-9]+)\.([0-9]+)'",text)
        code=re.search(r'versionCode (\d+)',text)
        if not match or not code:raise ValueError('Could not locate Android version fields')
        version=f'{match[1]}.{match[2]}.{int(match[3])+1}'
        text=text.replace(match[0],f"versionName '{version}'",1).replace(code[0],f'versionCode {int(code[1])+1}',1)
        if application_id:text=re.sub(r"applicationId '[^']+'",f"applicationId '{application_id}'",text,count=1)
    output.mkdir(parents=True,mode=0o700,exist_ok=True)
    password=secrets.token_urlsafe(36)
    env=os.environ.copy();env['BWW_NEW_STORE_PASSWORD']=password
    key=output/'bww-release.p12'
    subprocess.run([keytool,'-genkeypair','-noprompt','-storetype','PKCS12','-keystore',str(key),'-alias','bww',
        '-keyalg','RSA','-keysize','3072','-validity','10000','-dname','CN=BWW fork release',
        '-storepass:env','BWW_NEW_STORE_PASSWORD','-keypass:env','BWW_NEW_STORE_PASSWORD'],env=env,capture_output=True,check=True)
    key.chmod(0o600)
    cert=subprocess.run([keytool,'-exportcert','-keystore',str(key),'-alias','bww','-storepass:env','BWW_NEW_STORE_PASSWORD'],env=env,capture_output=True,check=True).stdout
    fingerprint=hashlib.sha256(cert).hexdigest()
    credentials=output/'credentials.json';credentials.write_text(json.dumps({'alias':'bww','storePassword':password,'keyPassword':password}));credentials.chmod(0o600)
    (output/'certificate.sha256').write_text(fingerprint+'\n')
    if init_fork:
        (ROOT/'android/signing-certificate.sha256').write_text(fingerprint+'\n')
        gradle.write_text(text)
        print('Fork public certificate pin and Android version updated. Commit those two public files to YOUR fork.')
    print('Private bundle saved outside the repository:',output)
    print('Public certificate SHA-256:',fingerprint)
    print('Configure the four Actions secrets in YOUR fork. Keep this private bundle backed up.')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--keytool',default=shutil.which('keytool') or 'keytool')
    parser.add_argument('--init-fork',action='store_true')
    parser.add_argument('--application-id',help='Optional separate fork app ID (requires --init-fork)')
    args=parser.parse_args()
    if args.application_id and not args.init_fork:parser.error('--application-id requires --init-fork')
    create(args.output,args.keytool,args.init_fork,args.application_id)
