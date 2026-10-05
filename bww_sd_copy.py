#!/usr/bin/env python3
"""BWW computer/SD copy tool. No formatting, raw-disk access, or third-party packages."""
import argparse
import base64
import contextlib
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import uuid

ASSETS = ('html', 'css', 'js')
SITE_LIMIT = 512 * 1024
CHUNK_BYTES = 8192
USER_NAME = re.compile(r'[a-z0-9_]{3,32}\Z')
DOMAIN = re.compile(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.bww\Z')
HEX_ID = re.compile(r'[0-9a-f]{32}\Z')

class CopyError(Exception):
    pass


def sha(data):
    return hashlib.sha256(data).hexdigest()


def arduino_json(value):
    """Match ArduinoJson 6 serialization, including legacy control characters."""
    if value is None:
        return 'null'
    if value is True:
        return 'true'
    if value is False:
        return 'false'
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        escapes = {'"': '\\"', '\\': '\\\\', '\b': '\\b', '\f': '\\f',
                   '\n': '\\n', '\r': '\\r', '\t': '\\t', '\0': '\\u0000'}
        return '"' + ''.join(escapes.get(c, c) for c in value) + '"'
    if isinstance(value, list):
        return '[' + ','.join(arduino_json(v) for v in value) + ']'
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return '{' + ','.join(arduino_json(k) + ':' + arduino_json(v) for k, v in value.items()) + '}'
    raise CopyError('Unsupported value in ESP32 metadata')


def digest(value):
    return sha(arduino_json(value).encode('utf-8'))


def json_memory(value):
    """Conservative ArduinoJson pool bound (32-byte host slots; ESP32 uses 16)."""
    strings = set()
    def slots(v):
        if isinstance(v, dict):
            strings.update(v)
            return len(v) + sum(slots(x) for x in v.values())
        if isinstance(v, list):
            return len(v) + sum(slots(x) for x in v)
        if isinstance(v, str):
            strings.add(v)
        return 0
    count = slots(value)
    return count * 32 + sum(len(s.encode('utf-8')) + 1 for s in strings)


def uint(value):
    return type(value) is int and 0 <= value < 2**64


def unhex(value, size):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9a-fA-F]{' + str(size * 2) + '}', value):
        raise CopyError('Invalid stored credential/checksum')
    return bytes.fromhex(value)


def safe_file(root, relative):
    path = root
    for part in Path(relative).parts:
        if part in ('.', '..') or not part or Path(part).is_absolute():
            raise CopyError('Unsafe data path')
        path = path / part
        if path.is_symlink():
            raise CopyError('Refusing a symbolic link in BWW data: ' + str(path))
    return path


@dataclass
class Bundle:
    users: dict = field(default_factory=dict)
    sites: dict = field(default_factory=dict)
    state: dict = field(default_factory=dict)
    active: int = None
    files: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    def read(self, path, maximum):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
            raise CopyError('Missing, unsafe, or oversized data file: ' + str(path))
        data = path.read_bytes()
        if len(data) > maximum:
            raise CopyError('Data file grew while reading; stop the host and retry')
        self.files[path] = sha(data)
        return data

    def read_json(self, path, maximum):
        try:
            def unique(pairs):
                result = {}
                for k, v in pairs:
                    if k in result:
                        raise CopyError('Duplicate JSON key in ' + str(path))
                    result[k] = v
                return result
            return json.loads(self.read(path, maximum).decode('utf-8'), strict=False,
                              object_pairs_hook=unique)
        except (ValueError, UnicodeError) as error:
            raise CopyError('Invalid JSON data: ' + str(path)) from error


def checked_site(domain, owner, html, css, js, updated=None):
    if not isinstance(domain, str) or not DOMAIN.fullmatch(domain) or not isinstance(owner, str) or not USER_NAME.fullmatch(owner):
        raise CopyError('Invalid stored domain or owner')
    values = (html, css, js)
    if not all(isinstance(x, str) for x in values):
        raise CopyError('Site assets must be UTF-8 strings: ' + domain)
    try:
        total = sum(len(x.encode('utf-8')) for x in values)
    except UnicodeError as error:
        raise CopyError('Invalid Unicode site: ' + domain) from error
    if total > SITE_LIMIT or not html.strip():
        raise CopyError('Site requires nonblank HTML and at most 512 KiB combined: ' + domain)
    return dict(domain=domain, owner=owner, html=html, css=css, js=js, updated=updated)


def load_desktop(path, allow_empty=False):
    bundle = Bundle()
    if not path.exists():
        if not allow_empty:
            raise CopyError('Select the computer server\'s store.json file')
        bundle.files[path] = None
        bundle.state = {'Users': {}, 'Sessions': {}, 'Sites': {}}
        return bundle
    state = bundle.read_json(path, 64 * 1024 * 1024)
    if not isinstance(state, dict) or not all(isinstance(state.get(k), dict) for k in ('Users', 'Sessions', 'Sites')):
        raise CopyError('This is not a BWW desktop store.json file')
    for name, user in state['Users'].items():
        if not USER_NAME.fullmatch(name) or not isinstance(user, dict) or user.get('Name') != name:
            raise CopyError('Invalid desktop account')
        try:
            salt = base64.b64decode(user['Salt'], validate=True)
            password_hash = base64.b64decode(user['Hash'], validate=True)
        except (KeyError, ValueError, TypeError) as error:
            raise CopyError('Invalid desktop password hash') from error
        if len(salt) != 16 or len(password_hash) != 32:
            raise CopyError('Invalid desktop password hash length')
        bundle.users[name] = dict(name=name, salt=salt.hex(), hash=password_hash.hex())
    for domain, site in state['Sites'].items():
        if not isinstance(site, dict) or site.get('Domain') != domain:
            raise CopyError('Invalid desktop site record')
        item = checked_site(domain, site.get('Owner'), site.get('Html'), site.get('Css'), site.get('Js'), site.get('Updated'))
        if item['owner'] not in bundle.users:
            raise CopyError('Site owner account is missing: ' + domain)
        bundle.sites[domain] = item
    # Sessions belong to this host; preserve destination sessions without copying source sessions.
    for key, session in state['Sessions'].items():
        unhex(key, 32)
        if not isinstance(session, dict) or session.get('User') not in bundle.users or not isinstance(session.get('Expires'), str):
            raise CopyError('Invalid desktop session record')
    bundle.state = state
    return bundle


def state_ok(state):
    if not isinstance(state, dict) or not uint(state.get('generation')) or not uint(state.get('clock')):
        return False
    checksum = state.get('digest')
    plain = {k: v for k, v in state.items() if k != 'digest'}
    if not isinstance(checksum, str) or not hmac.compare_digest(checksum, digest(plain)):
        return False
    if not all(isinstance(state.get(k), list) for k in ('users', 'sessions', 'sites')) or json_memory(state) > 16384:
        return False
    if len(state['users']) > 12 or len(state['sessions']) > 24 or len(state['sites']) > 24:
        return False
    users, domains = set(), set()
    for u in state['users']:
        if not isinstance(u, dict) or not isinstance(u.get('name'), str) or not USER_NAME.fullmatch(u['name']) or u['name'] in users:
            return False
        unhex(u.get('salt'), 16); unhex(u.get('hash'), 32); users.add(u['name'])
    for s in state['sessions']:
        if not isinstance(s, dict) or s.get('user') not in users or not uint(s.get('expires')):
            return False
        unhex(s.get('key'), 32)
    for s in state['sites']:
        if not isinstance(s, dict) or not isinstance(s.get('domain'), str) or not DOMAIN.fullmatch(s['domain']) or s['domain'] in domains or s.get('owner') not in users or not uint(s.get('revision')):
            return False
        domains.add(s['domain'])
    return True


def load_sd(root, allow_empty=False):
    bundle = Bundle(); candidates = []; any_slot = False
    for index in (0, 1):
        path = safe_file(root, 'bww/state-' + str(index) + '.json')
        if not path.exists():
            bundle.files[path] = None
            continue
        any_slot = True
        try:
            state = bundle.read_json(path, 65536)
            if state_ok(state) and all(safe_file(root, 'bww/sites/' + s['domain'] + '.' + str(s['revision']) + '.json').is_file() for s in state['sites']):
                candidates.append((state['generation'], index, state))
        except (CopyError, ValueError, TypeError, RecursionError):
            continue
    if not candidates:
        if any_slot or not allow_empty:
            raise CopyError('SD BWW snapshots are missing or damaged. Nothing will be reset; restore a backup first.')
        bundle.state = dict(generation=0, clock=0, users=[], sessions=[], sites=[])
        return bundle
    _, bundle.active, bundle.state = max(candidates, key=lambda c: (c[0], -c[1]))
    if any_slot and len(candidates) < sum(v is not None for v in bundle.files.values()):
        bundle.notes.append('A damaged SD snapshot was ignored; the valid snapshot will be used.')
    bundle.users = {u['name']: dict(name=u['name'], salt=unhex(u['salt'],16).hex(), hash=unhex(u['hash'],32).hex()) for u in bundle.state['users']}
    for record in bundle.state['sites']:
        domain = record['domain']; revision = record['revision']
        path = safe_file(root, 'bww/sites/' + domain + '.' + str(revision) + '.json')
        metadata = bundle.read_json(path, 131072)
        data = metadata.get('data') if isinstance(metadata, dict) else None
        if not isinstance(data, dict) or metadata.get('ok') is not True or metadata.get('digest') != digest(data) or data.get('domain') != domain or data.get('owner') != record['owner'] or data.get('revision') != revision or json_memory(metadata) > 24576:
            raise CopyError('Damaged site metadata: ' + domain)
        if data.get('transferMode') == 'chunk-v1':
            identifier = data.get('transfer'); chunks = data.get('chunks'); assets = {}; total = count = 0
            if not isinstance(identifier, str) or not HEX_ID.fullmatch(identifier) or not isinstance(chunks, dict):
                raise CopyError('Invalid chunked site: ' + domain)
            for asset in ASSETS:
                if not isinstance(chunks.get(asset), list):
                    raise CopyError('Missing chunk list: ' + domain)
                content = bytearray()
                for i, chunk in enumerate(chunks[asset]):
                    if not isinstance(chunk, dict) or type(chunk.get('bytes')) is not int or not 1 <= chunk['bytes'] <= CHUNK_BYTES:
                        raise CopyError('Invalid site chunk: ' + domain)
                    count += 1; total += chunk['bytes']
                    if count > 67 or total > SITE_LIMIT:
                        raise CopyError('Oversized chunked site: ' + domain)
                    raw = bundle.read(safe_file(root, 'bww/sites/' + identifier + '.' + asset + '.' + str(i) + '.bin'), CHUNK_BYTES)
                    if len(raw) != chunk['bytes'] or chunk.get('hash') != sha(raw):
                        raise CopyError('Damaged site chunk: ' + domain)
                    content.extend(raw)
                try:
                    assets[asset] = content.decode('utf-8')
                except UnicodeError as error:
                    raise CopyError('Invalid UTF-8 site: ' + domain) from error
        else:
            assets = {a: data.get(a) for a in ASSETS}
        bundle.sites[domain] = checked_site(domain, record['owner'], **assets)
    return bundle


@dataclass
class Plan:
    direction: str
    computer: Path
    sd: Path
    source: Bundle
    destination: Bundle
    added_users: list
    added_sites: list
    updated_sites: list
    same_sites: list

    def describe(self):
        lines = [('Computer → SD card' if self.direction == 'to-sd' else 'SD card → Computer'),
                 'Computer store: ' + str(self.computer), 'SD card folder: ' + str(self.sd),
                 f'Accounts to add: {len(self.added_users)}',
                 f'Sites to add: {len(self.added_sites)}; update: {len(self.updated_sites)}; unchanged: {len(self.same_sites)}']
        lines += ['Add: ' + d for d in self.added_sites] + ['Update: ' + d for d in self.updated_sites]
        lines += self.source.notes + self.destination.notes
        lines += ['Destination-only accounts and sites are kept.', 'No formatting. Existing destination sessions are kept; source sessions are not copied.']
        return '\n'.join(lines)


def plan_copy(computer, sd, direction='to-sd'):
    if direction not in ('to-sd', 'to-computer'):
        raise CopyError('Invalid copy direction')
    computer = Path(computer).expanduser().absolute()
    sd = Path(sd).expanduser().absolute()
    if any(p.is_symlink() for p in (computer, *computer.parents, sd, *sd.parents)):
        raise CopyError('Symbolic links are not supported for transfer paths')
    computer = computer.resolve(); sd = sd.resolve()
    if not sd.is_dir():
        raise CopyError('Select a mounted SD card folder')
    if sd == Path(sd.anchor) and (os.name != 'nt' or sd.drive.lower() == os.environ.get('SystemDrive', 'C:').lower()):
        raise CopyError('Select the SD card, not the system drive')
    if computer == sd or sd in computer.parents:
        raise CopyError('Computer store must be outside the selected SD card')
    if os.name == 'nt' and direction == 'to-sd':
        import ctypes
        filesystem = ctypes.create_unicode_buffer(32)
        if ctypes.windll.kernel32.GetVolumeInformationW(str(Path(sd.anchor)), None, 0, None, None, None, filesystem, 32):
            if filesystem.value.upper() not in ('FAT', 'FAT32'):
                raise CopyError('ESP32 requires a FAT/FAT32 card. This tool does not format cards. Back up and prepare the card separately.')
    pc = load_desktop(computer, allow_empty=direction == 'to-computer')
    card = load_sd(sd, allow_empty=direction == 'to-sd')
    source, dest = (pc, card) if direction == 'to-sd' else (card, pc)
    added_users, added_sites, updated, same = [], [], [], []
    for name, account in source.users.items():
        if name not in dest.users:
            added_users.append(name)
        elif account != dest.users[name]:
            raise CopyError('Account conflict: ' + name + '. Both hosts have different credentials for this name. No accounts will be overwritten.')
    for domain, site in source.sites.items():
        old = dest.sites.get(domain)
        if old is None:
            added_sites.append(domain)
        elif old['owner'] != site['owner']:
            raise CopyError('Domain conflict: ' + domain + ' belongs to a different owner on the destination')
        elif all(old[a] == site[a] for a in ASSETS):
            same.append(domain)
        else:
            updated.append(domain)
    merged = dict(dest.sites); merged.update(source.sites)
    counts = {}
    for site in merged.values():
        counts[site['owner']] = counts.get(site['owner'], 0) + 1
    if direction == 'to-sd' and (len(dest.users) + len(added_users) > 12 or len(merged) > 24 or any(c > 8 for c in counts.values())):
        raise CopyError('ESP32 limits exceeded: 12 accounts, 24 sites total, 8 sites per account')
    if direction == 'to-computer' and (len(dest.users) + len(added_users) > 10000 or any(c > 50 for c in counts.values())):
        raise CopyError('Desktop account/site limits exceeded')
    return Plan(direction, computer, sd, source, dest, added_users, added_sites, updated, same)


def check_unchanged(plan):
    for path, expected in {**plan.source.files, **plan.destination.files}.items():
        if path.is_symlink() or (None if not path.exists() else sha(path.read_bytes())) != expected:
            raise CopyError('Data changed since preview. Stop both hosts and preview again.')


@contextlib.contextmanager
def lock(path):
    if path.is_symlink():
        raise CopyError('Refusing a symbolic link for the transfer lock')
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        file = path.open('a+b')
    except OSError as error:
        raise CopyError('Close the BWW server and other copy tools before copying') from error
    try:
        if os.name == 'nt':
            import msvcrt
            if not file.seek(0, os.SEEK_END):
                file.write(b'\0'); file.flush()
            file.seek(0)
            msvcrt.locking(file.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as error:
        file.close()
        raise CopyError('The BWW server or another copy tool is using this data. Close it first.') from error
    try:
        yield
    finally:
        file.close()


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix='.bww-copy-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
        if path.read_bytes() != data:
            raise CopyError('Written file did not verify: ' + str(path))
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def chunks(text):
    raw = text.encode('utf-8'); start = 0
    while start < len(raw):
        end = min(start + CHUNK_BYTES, len(raw))
        if end < len(raw):
            while raw[end] & 0xc0 == 0x80:
                end -= 1
        yield raw[start:end]; start = end


def prepare_sd(plan):
    state = {k: copy.deepcopy(v) for k, v in plan.destination.state.items() if k != 'digest'}
    generation = state['generation'] + 1
    # A failed previous copy may have left an unreferenced generation. Never
    # overwrite it; choose a fresh generation so a safe retry can proceed.
    for _ in range(1024):
        if not any(safe_file(plan.sd, 'bww/sites/' + d + '.' + str(generation) + '.json').exists() for d in plan.added_sites + plan.updated_sites):
            break
        generation += 1
    else:
        raise CopyError('Too many unreferenced site generations; check the SD card before retrying')
    if not uint(generation):
        raise CopyError('SD generation counter cannot be advanced')
    state['generation'] = generation
    state['users'] += [copy.deepcopy(plan.source.users[n]) for n in plan.added_users]
    files = {}
    for domain in plan.added_sites + plan.updated_sites:
        site = plan.source.sites[domain]; identifier = uuid.uuid4().hex
        data = dict(domain=domain, owner=site['owner'], revision=generation, updated=None,
                    transferMode='chunk-v1', transfer=identifier, chunks={})
        for asset in ASSETS:
            entries = []
            for i, raw in enumerate(chunks(site[asset])):
                files['bww/sites/' + identifier + '.' + asset + '.' + str(i) + '.bin'] = raw
                entries.append(dict(bytes=len(raw), hash=sha(raw)))
            data['chunks'][asset] = entries
        metadata = dict(ok=True, data=data, digest=digest(data))
        if json_memory(metadata) > 24576:
            raise CopyError('Site metadata exceeds ESP32 memory limit: ' + domain)
        files['bww/sites/' + domain + '.' + str(generation) + '.json'] = arduino_json(metadata).encode('utf-8')
        state['sites'] = [s for s in state['sites'] if s['domain'] != domain]
        state['sites'].append(dict(domain=domain, owner=site['owner'], revision=generation))
    state['digest'] = digest(state)
    if not state_ok(state):
        raise CopyError('Merged account/site metadata exceeds ESP32 storage limits')
    return state, files


def backup(plan, directory):
    directory = Path(directory).expanduser().absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise CopyError('Symbolic links are not supported for backup folders')
    directory = directory.resolve()
    if directory == plan.sd or plan.sd in directory.parents or directory == plan.computer.parent or plan.computer in directory.parents:
        raise CopyError('Choose a separate backup folder on the computer, outside the SD card and server store folder')
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / ('bww-copy-' + uuid.uuid4().hex[:12]); output.mkdir(mode=0o700)
    if plan.direction == 'to-sd':
        data = safe_file(plan.sd, 'bww')
        if data.exists():
            for path in data.rglob('*'):
                if path.is_symlink() or not (path.is_file() or path.is_dir()):
                    raise CopyError('Unsafe file in SD data; backup was not completed')
            shutil.copytree(data, output / 'bww')
    elif plan.computer.exists():
        shutil.copy2(plan.computer, output / 'store.json')
    (output / 'COPY_PLAN.txt').write_text(plan.describe(), encoding='utf-8')
    return output


def apply_copy(plan, backup_dir=None):
    if not (plan.added_users or plan.added_sites or plan.updated_sites):
        return None
    backup_dir = backup_dir or Path.home() / 'BwwBackups'
    with lock(plan.computer.with_name(plan.computer.name + '.lock')), lock(plan.sd / '.bww-copy.lock'):
        check_unchanged(plan)
        prepared = prepare_sd(plan) if plan.direction == 'to-sd' else None
        saved = backup(plan, backup_dir)
        check_unchanged(plan)
        try:
            if plan.direction == 'to-sd':
                state, files = prepared
                # New immutable site generations first; leave both old snapshots intact
                # until the final commit. No cleanup/deletion of destination site data.
                targets = [(safe_file(plan.sd, name), content) for name, content in files.items()]
                if any(path.exists() for path, _ in targets):
                    raise CopyError('A new site filename already exists; preview again')
                for path, content in targets:
                    atomic_write(path, content)
                check_unchanged(plan)
                encoded = arduino_json(state).encode('utf-8')
                slot = 0 if plan.destination.active is None else 1 - plan.destination.active
                atomic_write(safe_file(plan.sd, 'bww/state-' + str(slot) + '.json'), encoded)
                if plan.destination.active is None:
                    atomic_write(safe_file(plan.sd, 'bww/state-' + str(1 - slot) + '.json'), encoded)
                load_sd(plan.sd)
            else:
                state = copy.deepcopy(plan.destination.state)
                for name in plan.added_users:
                    u = plan.source.users[name]
                    state['Users'][name] = dict(Name=name, Salt=base64.b64encode(bytes.fromhex(u['salt'])).decode(),
                                               Hash=base64.b64encode(bytes.fromhex(u['hash'])).decode())
                for domain in plan.added_sites + plan.updated_sites:
                    s = plan.source.sites[domain]
                    state['Sites'][domain] = dict(Domain=domain, Owner=s['owner'], Html=s['html'], Css=s['css'], Js=s['js'],
                                                 Updated=s['updated'] or datetime.now(timezone.utc).isoformat())
                check_unchanged(plan)
                atomic_write(plan.computer, json.dumps(state, ensure_ascii=False, separators=(',', ':')).encode('utf-8'))
                load_desktop(plan.computer)
        except (OSError, CopyError) as error:
            raise CopyError('Copy did not complete. Do not start either host until checking the data. Backup: ' + str(saved) + '\n' + str(error)) from error
    return saved


def gui():
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
        window = tk.Tk()
    except Exception as error:
        raise CopyError('A desktop and Python with Tkinter are required for the window. Use --help for command-line copying.') from error
    window.title('BWW — Copy computer and SD card'); window.geometry('760x520')
    frame = ttk.Frame(window, padding=16); frame.pack(fill='both', expand=True)
    direction = tk.StringVar(value='to-sd')
    default = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'Bww' / 'store.json'
    computer = tk.StringVar(value=str(default)); sd = tk.StringVar(); stopped = tk.BooleanVar()
    ttk.Label(frame, text='Copy websites and accounts. This tool never formats your SD card.', wraplength=710).pack(anchor='w')
    row = ttk.Frame(frame); row.pack(fill='x', pady=12)
    ttk.Radiobutton(row, text='Computer → SD card', value='to-sd', variable=direction).pack(side='left')
    ttk.Radiobutton(row, text='SD card → Computer', value='to-computer', variable=direction).pack(side='left', padx=20)
    def browse_computer():
        method = filedialog.askopenfilename if direction.get() == 'to-sd' else filedialog.asksaveasfilename
        selected = method(title='Select BWW computer store.json', initialfile='store.json', defaultextension='.json', filetypes=[('BWW store', '*.json')])
        if selected: computer.set(selected)
    def browse_sd():
        selected = filedialog.askdirectory(title='Select your mounted SD card drive root (for example E:\\)', mustexist=True)
        if selected: sd.set(selected)
    for title, variable, command in [('Computer store.json', computer, browse_computer), ('SD card drive / folder', sd, browse_sd)]:
        ttk.Label(frame, text=title).pack(anchor='w')
        row = ttk.Frame(frame); row.pack(fill='x', pady=(2, 10))
        ttk.Entry(row, textvariable=variable).pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Browse…', command=command).pack(side='left', padx=(8, 0))
    ttk.Label(frame, text='Stop the C# server. Power off the ESP32 and put its FAT32 card in a computer card reader.', wraplength=710).pack(anchor='w')
    ttk.Checkbutton(frame, text='The desktop server is stopped and the ESP32 is powered off.', variable=stopped).pack(anchor='w', pady=8)
    status = tk.Text(frame, height=10, wrap='word'); status.pack(fill='both', expand=True)
    def preview():
        try:
            if not computer.get().strip() or not sd.get().strip(): raise CopyError('Choose both the computer store and the SD card first')
            plan = plan_copy(computer.get(), sd.get(), direction.get())
            status.delete('1.0', 'end'); status.insert('end', plan.describe()); return plan
        except (CopyError, OSError, ValueError, TypeError, RecursionError) as error:
            messagebox.showerror('Cannot copy', str(error)); return None
    def run_copy():
        if not stopped.get(): messagebox.showinfo('Stop the hosts', 'Stop the desktop server and power off the ESP32 before copying.'); return
        plan = preview()
        if plan is None: return
        if not messagebox.askyesno('Review copy', plan.describe() + '\n\nCreate a backup and apply this copy?'): return
        try:
            window.configure(cursor='watch')
            status.insert('end', '\n\nBacking up and copying… Keep the SD card connected.')
            window.update_idletasks()
            saved = apply_copy(plan)
            messagebox.showinfo('Copy finished', ('Verified copy complete. Backup: ' + str(saved) if saved else 'Everything already matches; no changes made.') + '\nSafely eject the SD card before returning it to the ESP32.')
        except (CopyError, OSError, ValueError) as error: messagebox.showerror('Copy stopped', str(error))
        finally: window.configure(cursor='')
    row = ttk.Frame(frame); row.pack(fill='x', pady=(12, 0))
    ttk.Button(row, text='Preview', command=preview).pack(side='left')
    ttk.Button(row, text='Back up and copy', command=run_copy).pack(side='right')
    window.mainloop()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--computer', type=Path, help='Desktop server store.json path')
    parser.add_argument('--sd', type=Path, help='Mounted SD card root folder')
    parser.add_argument('--direction', choices=('to-sd', 'to-computer'), default='to-sd')
    parser.add_argument('--backup-dir', type=Path, help='Computer backup folder; default ~/BwwBackups')
    parser.add_argument('--apply', action='store_true', help='Apply the previewed copy after making a backup; stop both hosts first')
    args = parser.parse_args(argv)
    try:
        if args.computer is None and args.sd is None:
            gui(); return 0
        if args.computer is None or args.sd is None:
            parser.error('Specify both --computer and --sd, or neither for the window')
        plan = plan_copy(args.computer, args.sd, args.direction)
        print(plan.describe())
        if args.apply:
            saved = apply_copy(plan, args.backup_dir)
            print('Verified copy complete. Backup: ' + str(saved) if saved else 'No changes needed.')
        else: print('Preview only. Add --apply to create a backup and copy.')
        return 0
    except (CopyError, OSError, ValueError, TypeError, RecursionError) as error:
        print('Copy stopped: ' + str(error), file=sys.stderr); return 1

if __name__ == '__main__':
    sys.exit(main())
