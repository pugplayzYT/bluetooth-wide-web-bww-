#!/usr/bin/env python3
"""Test the production password HMAC against OpenSSL using real Mbed TLS 2.x."""
import argparse
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--arduinojson', type=Path, required=True)
parser.add_argument('--mbedtls-source', type=Path, help='Mbed TLS 2.x source tree; otherwise use installed libmbedtls-dev')
args = parser.parse_args()
with tempfile.TemporaryDirectory(prefix='bww-password-tests-') as temporary:
    folder = Path(temporary)
    extra = []
    if args.mbedtls_source:
        for name in ('sha256', 'platform_util'):
            output = folder / (name + '.o')
            subprocess.run(['cc', '-O2', '-I' + str(args.mbedtls_source / 'include'), '-c',
                            str(args.mbedtls_source / 'library' / (name + '.c')), '-o', str(output)], check=True)
            extra.append(str(output))
        extra.append('-I' + str(args.mbedtls_source / 'include'))
    else:
        extra.append('-lmbedcrypto')
    executable = str(folder / 'password-hash')
    subprocess.run(['g++', '-std=c++17', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-I' + str(root / 'esp32/include'), '-I' + str(args.arduinojson),
                    str(root / 'tests/password_hash_harness.cpp'), *extra, '-lcrypto', '-o', executable], check=True)
    subprocess.run([executable], check=True)
