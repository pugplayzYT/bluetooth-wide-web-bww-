#!/usr/bin/env python3
"""Package built Windows sync host and ESP32-only source for direct downloads."""
from pathlib import Path
import hashlib
import re
import zipfile

root = Path(__file__).resolve().parents[1]
version = re.search(r'FIRMWARE_VERSION = "([^"]+)"', (root/'esp32/include/BwwConfig.h').read_text()).group(1)
output = root/'downloads'
exe = root/'artifacts/windows-x64/Bww.Server.exe'
if not exe.is_file() or exe.read_bytes()[:2] != b'MZ':
    raise SystemExit('Publish the Windows self-contained single-file host into artifacts/windows-x64 first')
firmware = sorted([*root.glob('esp32/include/*.h'), *root.glob('esp32/src/*.cpp')])
firmware += [root/p for p in ('esp32/platformio.ini','esp32/README.md','PROTOCOL.md','VALIDATION.md','SYNC_README.md')]
packages = {
    output/f'Bww-ESP32-PlatformIO-{version}.zip': [(p,p.relative_to(root).as_posix()) for p in firmware],
    output/f'Bww-Windows-Sync-{version}.zip': [(exe,'Bww.Server.exe'), *[(root/p,p) for p in ('Sync-BWW.bat','SYNC_README.md','VALIDATION.md')]]
}
for archive, entries in packages.items():
    expected = {}
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for path, name in entries:
            data = path.read_bytes()
            if name.endswith('.bat'): data = data.replace(b'\r\n',b'\n').replace(b'\n',b'\r\n')
            expected[name] = data; z.writestr(name,data)
    with zipfile.ZipFile(archive) as z:
        assert z.testzip() is None
        for name, data in expected.items(): assert z.read(name) == data
    print(f'Verified {archive.name}: {len(entries)} files, {archive.stat().st_size} bytes')
files = sorted([*output.glob('*.zip'), *output.glob('*.apk')])
(output/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in files))
