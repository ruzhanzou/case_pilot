"""Briefly pause only the synthetic acceptance Redis; independent watchdog resumes it."""
import os
import signal
import subprocess
import sys
import time

from redis import Redis


def verified(pid):
    command = subprocess.check_output(['ps', '-p', str(pid), '-o', 'command='], text=True).strip()
    if command != 'redis-server 127.0.0.1:6392':
        raise SystemExit('Refusing to signal a process other than the isolated acceptance broker')


if sys.argv[1] == 'resume_after':
    pid = int(sys.argv[2])
    time.sleep(15)
    verified(pid)
    os.kill(pid, signal.SIGCONT)
else:
    pid = int(Redis(host='127.0.0.1', port=6392, socket_timeout=2).info('server')['process_id'])
    verified(pid)
    subprocess.Popen([sys.executable, __file__, 'resume_after', str(pid)],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)
    os.kill(pid, signal.SIGSTOP)
    print(pid)
