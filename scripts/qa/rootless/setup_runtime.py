"""Rootless, loopback-only test dependency setup using SHA-pinned Debian packages.
Run with Python 3 on Debian 13 amd64. Writes only to the selected runtime directory.
Does not install system packages or start services. Requires curl and dpkg-deb.
"""
import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

here = Path(__file__).resolve().parent
runtime = Path(sys.argv[1] if len(sys.argv) > 1 else '/tmp/casepilot-runtime').resolve()
for name in ('packages', 'root', 'data', 'logs'):
    (runtime / name).mkdir(parents=True, exist_ok=True)
manifest = json.loads((here / 'package-manifest.json').read_text())


def fetch(package):
    target = runtime / 'packages' / Path(package['Filename']).name
    if not target.exists() or hashlib.sha256(target.read_bytes()).hexdigest() != package['SHA256']:
        subprocess.run(['curl', '-fsSL', '--max-time', '90',
                        'https://deb.debian.org/debian/' + package['Filename'], '-o', str(target)],
                       check=True)
    if hashlib.sha256(target.read_bytes()).hexdigest() != package['SHA256']:
        raise RuntimeError('Package checksum mismatch: ' + target.name)
    subprocess.run(['dpkg-deb', '-x', str(target), str(runtime / 'root')], check=True)
    print(package['Package'], package['Version'], 'verified', flush=True)


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    list(executor.map(fetch, manifest['packages']))
environment = dict(os.environ, LD_LIBRARY_PATH=str(runtime / 'root/usr/lib/x86_64-linux-gnu'))
if not (runtime / 'data/postgres/PG_VERSION').exists():
    subprocess.run([str(runtime / 'root/usr/lib/postgresql/17/bin/initdb'),
                    '-D', str(runtime / 'data/postgres'),
                    '-L', str(runtime / 'root/usr/share/postgresql/17'),
                    '-U', 'casepilot', '--auth=trust', '--no-locale', '-E', 'UTF8'],
                   env=environment, check=True)
print('Ready. Local trust authentication is for this isolated test runtime only.')
