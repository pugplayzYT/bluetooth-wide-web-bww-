#!/usr/bin/env python3
"""Package built ESP32 firmware, matching ELF and standalone PlatformIO sources."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import zipfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--framework', type=Path, default=Path(os.environ.get('PLATFORMIO_CORE_DIR', str(Path.home()/'.platformio')))/'packages/framework-arduinoespressif32')
args = parser.parse_args()
version = re.search(r'FIRMWARE_VERSION = "([^"]+)"', (root/'esp32/include/BwwConfig.h').read_text()).group(1)
build = root/'esp32/.pio/build/esp32dev'
firmware = (build/'firmware.bin').read_bytes()
elf = (build/'firmware.elf').read_bytes()
assert firmware[0] == 0xE9 and elf[:4] == b'\x7fELF'
assert firmware[0xb0:0xd0] == hashlib.sha256(elf).digest(), 'ELF does not match firmware image'
output = root/'downloads'
output.mkdir(exist_ok=True)

def archive(name, contents):
    path = output/name
    with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
        for entry, data in contents.items(): z.writestr(entry, data)
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None
        for entry, data in contents.items(): assert z.read(entry) == data
    print(f'Verified {name}: {path.stat().st_size} bytes')

sources = sorted([*root.glob('esp32/include/*.h'), *root.glob('esp32/src/*.cpp')])
sources += [root/p for p in ('esp32/platformio.ini', 'esp32/README.md', 'PROTOCOL.md', 'VALIDATION.md', 'SYNC_README.md')]
archive(f'Bww-ESP32-PlatformIO-{version}.zip', {p.relative_to(root).as_posix():p.read_bytes() for p in sources})
binaries = {name:(build/name).read_bytes() for name in ('firmware.bin', 'firmware.elf', 'bootloader.bin', 'partitions.bin')}
binaries['boot_app0.bin'] = (args.framework/'tools/partitions/boot_app0.bin').read_bytes()
binaries['SHA256SUMS.txt'] = ''.join(f'{hashlib.sha256(data).hexdigest()}  {name}\n' for name,data in binaries.items()).encode()
binaries['README.txt'] = f'''BWW ESP32 firmware {version}

For original ESP32 with Bluetooth Classic and at least 4 MB flash.
This build uses the BWW huge_app partition layout and GPIO5/18/23/19 SD wiring.

UPGRADE an existing BWW 0.4.x/0.5.x/0.6.x ESP32:
Back up the SD card /bww folder first. Firmware 0.6.0+ migrates the website index
without formatting. Do not downgrade to 0.5.2 or earlier after migration.
Install Android 0.6.0 to list all sites when there are more than 32.

1. Extract this ZIP. Close PlatformIO's serial monitor so COM3 is free.
2. Open PowerShell in the extracted folder. Change COM3 below if needed.
3. With your existing PlatformIO installation, run:

& "$env:USERPROFILE\\.platformio\\penv\\Scripts\\python.exe" "$env:USERPROFILE\\.platformio\\packages\\tool-esptoolpy\\esptool.py" --chip esp32 --port COM3 write_flash 0x10000 .\\firmware.bin

This writes only the application and does not erase flash or format the SD card.
If connection stalls, hold BOOT while connecting; release when writing starts.
Afterward restart the serial monitor at 115200 and confirm firmware {version}.

A fresh board requires its bootloader/partition/OTA-selection files as well:
python -m esptool --chip esp32 --port COM3 write_flash 0x1000 bootloader.bin 0x8000 partitions.bin 0xe000 boot_app0.bin 0x10000 firmware.bin
Use a Python environment with esptool 4.5.1. This full-layout command is for the
original ESP32/4 MB board above; prefer the PlatformIO source ZIP for custom boards.

firmware.elf is the matching crash-decoder file, not a file to flash.
For a prebuilt-image install, copy it to your PlatformIO project's
.pio/build/esp32dev/firmware.elf and use monitor_filters = esp32_exception_decoder.
Do not substitute an ELF from another build.

Physical Bluetooth/SD-card validation remains necessary; see VALIDATION.md.
'''.encode()
binaries['VALIDATION.md'] = (root/'VALIDATION.md').read_bytes()
archive(f'Bww-ESP32-Binaries-{version}.zip', binaries)
packages = sorted([*output.glob('*.zip'), *output.glob('*.apk')])
(output/'SHA256SUMS.txt').write_text(''.join(f'{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n' for p in packages))
