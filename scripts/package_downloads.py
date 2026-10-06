#!/usr/bin/env python3
"""Package only Android/Windows/SD-copy outputs into an isolated artifact directory."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def archive(path, entries):
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for source, name in entries:
            data = source.read_bytes()
            if name.endswith('.bat'):
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            info = zipfile.ZipInfo(name, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    with zipfile.ZipFile(path) as z:
        if z.testzip() is not None:
            raise ValueError('Package integrity check failed')

def android_source_hash():
    files = sorted(p for p in (ROOT / 'android').rglob('*') if p.is_file()
        and not any(part in ('build', '.gradle') for part in p.relative_to(ROOT / 'android').parts)
        and p.name not in ('local.properties', 'keystore.properties')
        and p.suffix not in ('.jks', '.keystore', '.p12', '.pfx'))
    digest = hashlib.sha256()
    for p in files:
        digest.update(p.relative_to(ROOT).as_posix().encode() + b'\0' + p.read_bytes() + b'\0')
    return digest.hexdigest()

def package(output, apksigner):
    output.mkdir(parents=True, exist_ok=True)
    version = re.search(r"versionName\s+['\"]([^'\"]+)['\"]", (ROOT/'android/app/build.gradle').read_text()).group(1)
    code = int(re.search(r'versionCode\s+(\d+)', (ROOT/'android/app/build.gradle').read_text()).group(1))
    host_version = re.search(r'FIRMWARE_VERSION = "([^"]+)"', (ROOT/'esp32/include/BwwConfig.h').read_text()).group(1)
    apk = ROOT/'android/app/build/outputs/apk/release/app-release.apk'
    certificate = (ROOT/'android/signing-certificate.sha256').read_text().strip()
    report = subprocess.run([apksigner, 'verify', '--print-certs', str(apk)], check=True, capture_output=True, text=True).stdout
    match = re.search(r'certificate SHA-256 digest: ([a-f0-9]+)', report)
    if not match or match.group(1) != certificate:
        raise ValueError('Release APK signing certificate differs from android/signing-certificate.sha256')
    apk_name = f'Bww-Android-{version}.apk'
    source_hash = android_source_hash()
    previous = ROOT/'downloads/release-manifest.json'
    existing = ROOT/'downloads'/apk_name
    if existing.exists():
        if not previous.is_file():
            raise ValueError('Existing APK lacks release metadata; bump Android versionName and versionCode')
        prior = json.loads(previous.read_text())['android']
        if prior['version'] != version or prior['sourceHash'] != source_hash or prior['certificateSha256'] != certificate or prior['sha256'] != sha(existing):
            raise ValueError('An existing Android version changed; bump versionName and versionCode for every fix')
        shutil.copyfile(existing, output/apk_name)
    else:
        if previous.is_file() and code <= json.loads(previous.read_text())['android']['versionCode']:
            raise ValueError('New Android releases must increase versionCode')
        shutil.copyfile(apk, output/apk_name)
    exe = ROOT/'artifacts/windows-x64/Bww.Server.exe'
    if exe.read_bytes()[:2] != b'MZ':
        raise ValueError('Windows executable missing or invalid')
    windows_name = f'Bww-Windows-Sync-{host_version}.zip'
    archive(output/windows_name, [(exe, 'Bww.Server.exe'), *[(ROOT/p, p) for p in ('Sync-BWW.bat', 'SYNC_README.md', 'VALIDATION.md')]])
    archive(output/'Bww-SD-Copy.zip', [(ROOT/p, p) for p in ('bww_sd_copy.py', 'BWW_SD_COPY_README.md', 'Run-BWW-SD-Copy.bat')])
    files = {p.name: sha(p) for p in sorted(output.iterdir()) if p.suffix in ('.zip', '.apk')}
    if set(files) != {apk_name, windows_name, 'Bww-SD-Copy.zip'}:
        raise ValueError('Build artifact directory contains unexpected packages')
    (output/'build-manifest.json').write_text(json.dumps({
        'files': files, 'android': {'version': version, 'versionCode': code, 'file': apk_name, 'sha256': files[apk_name],
            'sourceHash': source_hash, 'certificateSha256': certificate},
        'windows': {'version': host_version, 'file': windows_name},
        'sdCopy': {'file': 'Bww-SD-Copy.zip'}}, indent=2) + '\n')
    print('Verified signed Android release, Windows host and SD-copy packages.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'artifacts/downloads-build')
    parser.add_argument('--apksigner', default=str(Path(os.environ.get('ANDROID_HOME', ''))/'build-tools/35.0.0/apksigner'))
    args = parser.parse_args()
    package(args.output, args.apksigner)
