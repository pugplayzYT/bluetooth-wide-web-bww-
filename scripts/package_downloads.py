#!/usr/bin/env python3
"""Package available built artifacts (Android, Windows, ESP32, SD-copy) into downloads/ and update SHA256SUMS.txt."""
from pathlib import Path
import hashlib
import re
import shutil
import zipfile

root = Path(__file__).resolve().parents[1]
downloads = root / 'downloads'
downloads.mkdir(exist_ok=True)

def write_zip_deterministic(zip_path, file_entries):
    """Write zip only if contents changed, using a deterministic timestamp."""
    if zip_path.is_file():
        try:
            with zipfile.ZipFile(zip_path, 'r') as existing:
                names = existing.namelist()
                if set(names) == {arc for _, arc in file_entries}:
                    all_match = True
                    for src, arc in file_entries:
                        data = src.read_bytes()
                        if arc.endswith('.bat'):
                            data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
                        if existing.read(arc) != data:
                            all_match = False
                            break
                    if all_match:
                        return False
        except Exception:
            pass

    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as z:
        for src, arc in file_entries:
            data = src.read_bytes()
            if arc.endswith('.bat'):
                data = data.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
            info = zipfile.ZipInfo(arc, (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, data)
    return True

# 1. Package SD Copy
sd_copy_zip = downloads / 'Bww-SD-Copy.zip'
sd_files = ['bww_sd_copy.py', 'BWW_SD_COPY_README.md', 'Run-BWW-SD-Copy.bat']
if all((root / f).is_file() for f in sd_files):
    if write_zip_deterministic(sd_copy_zip, [(root / f, f) for f in sd_files]):
        print(f'Packaged {sd_copy_zip.name}')

# 2. Package Android APK if built
gradle_path = root / 'android/app/build.gradle'
apk_debug = root / 'android/app/build/outputs/apk/debug/app-debug.apk'
if gradle_path.is_file() and apk_debug.is_file():
    m = re.search(r"versionName\s+['\"]([^'\"]+)['\"]", gradle_path.read_text())
    if m:
        android_ver = m.group(1)
        dest_apk = downloads / f'Bww-Android-{android_ver}.apk'
        if not dest_apk.is_file() or dest_apk.read_bytes() != apk_debug.read_bytes():
            shutil.copy2(apk_debug, dest_apk)
            print(f'Packaged {dest_apk.name} ({dest_apk.stat().st_size} bytes)')

# 3. Package Windows Sync if built
exe = root / 'artifacts/windows-x64/Bww.Server.exe'
config_h = root / 'esp32/include/BwwConfig.h'
if exe.is_file() and exe.read_bytes()[:2] == b'MZ' and config_h.is_file():
    m = re.search(r'FIRMWARE_VERSION = "([^"]+)"', config_h.read_text())
    if m:
        firmware_ver = m.group(1)
        win_zip = downloads / f'Bww-Windows-Sync-{firmware_ver}.zip'
        entries = [(exe, 'Bww.Server.exe'), *[(root / p, p) for p in ('Sync-BWW.bat', 'SYNC_README.md', 'VALIDATION.md')]]
        if write_zip_deterministic(win_zip, entries):
            print(f'Packaged {win_zip.name}')

# 4. Package ESP32 PlatformIO sources
if config_h.is_file():
    m = re.search(r'FIRMWARE_VERSION = "([^"]+)"', config_h.read_text())
    if m:
        firmware_ver = m.group(1)
        pio_zip = downloads / f'Bww-ESP32-PlatformIO-{firmware_ver}.zip'
        firmware_files = sorted([*root.glob('esp32/include/*.h'), *root.glob('esp32/src/*.cpp')])
        firmware_files += [root / p for p in ('esp32/platformio.ini', 'esp32/README.md', 'PROTOCOL.md', 'VALIDATION.md', 'SYNC_README.md')]
        entries = [(p, p.relative_to(root).as_posix()) for p in firmware_files]
        if write_zip_deterministic(pio_zip, entries):
            print(f'Packaged {pio_zip.name}')

# 5. Update SHA256SUMS.txt
packages = sorted([*downloads.glob('*.zip'), *downloads.glob('*.apk')])
new_sums = ''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in packages)
sums_file = downloads / 'SHA256SUMS.txt'
if not sums_file.is_file() or sums_file.read_text() != new_sums:
    sums_file.write_text(new_sums)
    print(f'Updated SHA256SUMS.txt with {len(packages)} files.')
