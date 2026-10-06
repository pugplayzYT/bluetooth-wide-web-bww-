#!/usr/bin/env python3
"""Transfer a signing ZIP encrypted to a recipient's public key. Requires cryptography."""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import zipfile
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

CONTEXT = b'BWW signing transfer v1'
MAX_BYTES = 1024 * 1024

def prepare(directory):
    directory.mkdir(parents=True, exist_ok=True)
    private_path = directory/'transfer-private.pem'
    public_path = directory/'transfer-public.pem'
    if private_path.exists() or public_path.exists():
        raise ValueError('Transfer keys already exist. Keep them; do not overwrite the key needed to decrypt your download.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=4096)
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    public = key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    with private_path.open('xb') as f:
        private_path.chmod(0o600)
        f.write(private)
    public_path.write_bytes(public)
    print('Private transfer key saved on your PC. Share only the following PUBLIC key:')
    print(public.decode(), end='')

def encrypt(public_path, bundle, output):
    key = serialization.load_pem_public_key(public_path.read_bytes())
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < 3072:
        raise ValueError('An RSA public key of at least 3072 bits is required')
    if bundle.stat().st_size > MAX_BYTES:
        raise ValueError('Bundle is too large')
    content = bundle.read_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        if z.testzip() is not None or not {'credentials.json','bww-release.p12'}.issubset(z.namelist()):
            raise ValueError('Invalid signing bundle')
    secret = AESGCM.generate_key(bit_length=256)
    nonce = os.urandom(12)
    wrapped = key.encrypt(secret, padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=CONTEXT))
    encrypted = AESGCM(secret).encrypt(nonce, content, CONTEXT)
    envelope = {'version':1, 'key':base64.b64encode(wrapped).decode(), 'nonce':base64.b64encode(nonce).decode(), 'data':base64.b64encode(encrypted).decode()}
    with output.open('x') as f:json.dump(envelope, f)
    print('Encrypted signing bundle created. Only the matching private transfer key can open it.')

def decrypt(private_path, encrypted_path, output):
    if encrypted_path.stat().st_size > MAX_BYTES * 2:
        raise ValueError('Encrypted transfer is too large')
    key = serialization.load_pem_private_key(private_path.read_bytes(), password=None)
    if not isinstance(key, rsa.RSAPrivateKey):
        raise ValueError('RSA private transfer key required')
    envelope = json.loads(encrypted_path.read_text())
    if envelope.get('version') != 1:
        raise ValueError('Unsupported transfer version')
    decode = lambda name:base64.b64decode(envelope[name], validate=True)
    secret = key.decrypt(decode('key'), padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=CONTEXT))
    content = AESGCM(secret).decrypt(decode('nonce'), decode('data'), CONTEXT)
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        if z.testzip() is not None or not {'credentials.json','bww-release.p12'}.issubset(z.namelist()):
            raise ValueError('Invalid signing ZIP')
    with output.open('xb') as f:
        output.chmod(0o600)
        f.write(content)
    print('Decrypted signing ZIP saved. Extract it privately and add its values to GitHub Actions secrets.')

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command', required=True)
    p=sub.add_parser('prepare');p.add_argument('--directory',type=Path,default=Path.cwd())
    p=sub.add_parser('encrypt');p.add_argument('--public-key',type=Path,required=True);p.add_argument('--bundle',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p=sub.add_parser('decrypt');p.add_argument('--private-key',type=Path,default=Path('transfer-private.pem'));p.add_argument('--input',type=Path,default=Path('Bww-Signing.encrypted.json'));p.add_argument('--output',type=Path,default=Path('Bww-Signing.zip'))
    args=parser.parse_args()
    if args.command=='prepare':prepare(args.directory)
    elif args.command=='encrypt':encrypt(args.public_key,args.bundle,args.output)
    else:decrypt(args.private_key,args.input,args.output)
