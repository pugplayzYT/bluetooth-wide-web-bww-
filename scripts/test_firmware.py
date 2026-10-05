#!/usr/bin/env python3
"""Build and exercise the portable ESP32 core; requires g++, libssl-dev, ArduinoJson."""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arduinojson', type=Path, default=root / 'esp32/.pio/libdeps/esp32dev/ArduinoJson/src')
args = parser.parse_args()
subprocess.run(['python3', str(root / 'tests/test_bt_startup.py')], check=True)
if not (args.arduinojson / 'ArduinoJson.h').is_file():
    parser.error('ArduinoJson headers missing: run pio run -d esp32, or pass --arduinojson /path/to/ArduinoJson/src')
with tempfile.TemporaryDirectory(prefix='bww-firmware-tests-') as temporary:
    harness = str(Path(temporary) / 'firmware-harness')
    subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'esp32/include'), '-I' + str(args.arduinojson),
                    str(root / 'tests/firmware_harness.cpp'), str(root / 'esp32/src/BwwCore.cpp'), str(root / 'esp32/src/BwwTransfers.cpp'),
                    '-lcrypto', '-o', harness], check=True)
    subprocess.run([harness, '--crypto-check'], check=True)
    subprocess.run([harness, '--slots-check'], check=True)
    subprocess.run(['python3', str(root / 'tests/firmware_integration.py')],
                   env=dict(os.environ, BWW_FIRMWARE_HARNESS=harness), check=True)
    subprocess.run(['python3', str(root / 'tests/test_sd_copy.py')],
                   env=dict(os.environ, BWW_FIRMWARE_HARNESS=harness), check=True)
