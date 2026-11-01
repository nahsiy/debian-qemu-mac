"""Run unit tests normally; opt into the real Mac/HVF regression with
RUN_VM_INTEGRATION=1 python -m unittest discover -s tests -v.
"""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts import debian_vm as lab


PROBE_SERVER = '''import json,os,socket
from pathlib import Path
server=socket.socket(socket.AF_UNIX)
server.bind('/run/snapshot-probe.sock')
server.listen(4)
value='initial'
boot_id=Path('/proc/sys/kernel/random/boot_id').read_text().strip()
while True:
    connection,_=server.accept()
    with connection:
        request=json.loads(connection.recv(4096))
        if 'value' in request: value=request['value']
        connection.sendall(json.dumps({'value':value,'pid':os.getpid(),'boot_id':boot_id}).encode())
'''


class SnapshotGuards(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.vm = lab.VM()
        self.vm.disk = Path(self.directory.name) / 'disk.qcow2'
        self.vm.disk.touch()

    def test_hmp_error_inside_successful_qmp_reply_is_not_success(self):
        with patch.object(self.vm, 'qmp_command', return_value='Error: snapshot write failed\r\n'):
            with self.assertRaisesRegex(RuntimeError, 'snapshot write failed'):
                self.vm.monitor_action('savevm regression')

    def test_legacy_daemonized_process_is_rejected_before_any_qmp_action(self):
        with patch.dict(os.environ, SNAPSHOT='regression', SNAPSHOT_MODE='live'), \
             patch.object(self.vm, 'running', return_value=True), \
             patch.object(self.vm, 'legacy_launch', return_value=True), \
             patch.object(self.vm, 'qmp_command') as command:
            with self.assertRaisesRegex(RuntimeError, 'Ancien lancement'):
                self.vm.snapshot()
            command.assert_not_called()

    def test_disk_only_snapshot_cannot_be_loaded_as_ram_state(self):
        with patch.dict(os.environ, SNAPSHOT='regression', SNAPSHOT_MODE='live'), \
             patch.object(self.vm, 'running', return_value=True), \
             patch.object(self.vm, 'legacy_launch', return_value=False), \
             patch.object(self.vm, 'qmp_command', return_value={'running': True}), \
             patch.object(self.vm, 'snapshot_info', return_value=[{'name': 'regression', 'vm-state-size': 0}]), \
             patch.object(self.vm, 'monitor_action') as monitor:
            with self.assertRaisesRegex(RuntimeError, 'SNAPSHOT_MODE=disk'):
                self.vm.snapshot(restore=True)
            monitor.assert_not_called()

    def test_missing_snapshot_is_rejected_before_loadvm(self):
        with patch.dict(os.environ, SNAPSHOT='regression', SNAPSHOT_MODE='live'), \
             patch.object(self.vm, 'running', return_value=True), \
             patch.object(self.vm, 'legacy_launch', return_value=False), \
             patch.object(self.vm, 'qmp_command', return_value={'running': True}), \
             patch.object(self.vm, 'snapshot_info', return_value=[]), \
             patch.object(self.vm, 'monitor_action') as monitor:
            with self.assertRaisesRegex(RuntimeError, 'introuvable'):
                self.vm.snapshot(restore=True)
            monitor.assert_not_called()


@unittest.skipUnless(os.environ.get('RUN_VM_INTEGRATION') == '1',
                     'Requires an explicit opt-in: creates a disposable 2 GiB QEMU/HVF VM')
class LiveSnapshotIntegration(unittest.TestCase):
    def setUp(self):
        with socket.socket() as available:
            available.bind(('127.0.0.1', 0))
            port = available.getsockname()[1]
        self.environment = patch.dict(os.environ, {
            'MACHINE_NAME': 'snap-test-' + uuid.uuid4().hex[:8],
            'SSH_PORT_LOCAL': str(port), 'SSH_USER': 'debian',
            'VM_CPUS': '2', 'VM_MEMORY': '2048', 'VM_DISK_SIZE': '20G',
            'SNAPSHOT': 'regression', 'SNAPSHOT_MODE': 'live',
        })
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.vm = lab.VM()
        self.assertFalse(self.vm.folder.exists())
        self.addCleanup(self.cleanup_vm)
        self.vm.start()

    def cleanup_vm(self):
        if self.vm.running():
            # A failed snapshot can leave a guest paused; resume before ACPI shutdown.
            try:
                self.monitor('cont')
            except (OSError, RuntimeError, AssertionError):
                pass
        self.vm.destroy()

    def guest(self, code):
        result = subprocess.run(self.vm.ssh_command() + ['sudo python3 -'],
                                input=code, text=True, capture_output=True,
                                timeout=30, check=True)
        return result.stdout.strip()

    def monitor(self, command):
        # Independent wire-level probe: this exercises the real launcher/savevm
        # crash even before the application's live-snapshot API exists.
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(90)
            connection.connect(str(self.vm.qmp))
            with connection.makefile('rwb', buffering=0) as stream:
                self.assertIn('QMP', json.loads(stream.readline()))
                for number, name, args in [(1, 'qmp_capabilities', None),
                         (2, 'human-monitor-command', {'command-line': command})]:
                    request = {'execute': name, 'id': number}
                    if args is not None:
                        request['arguments'] = args
                    stream.write((json.dumps(request) + '\n').encode())
                    while True:
                        line = stream.readline()
                        self.assertTrue(line, 'QEMU closed QMP before replying (savevm crash)')
                        response = json.loads(line)
                        if response.get('id') == number:
                            self.assertNotIn('error', response)
                            result = response['return']
                            break
                return result

    def memory(self, value=None):
        request = {} if value is None else {'value': value}
        return json.loads(self.guest(f'''import socket
s=socket.socket(socket.AF_UNIX)
s.settimeout(5)
s.connect('/run/snapshot-probe.sock')
s.sendall({json.dumps(request).encode()!r})
print(s.recv(4096).decode())
'''))

    def test_real_ram_and_disk_roundtrip(self):
        self.guest(f'''from pathlib import Path
import subprocess,time,os
p=Path('/var/tmp/snapshot-probe.py')
p.write_text({PROBE_SERVER!r})
subprocess.run(['systemd-run','--unit=snapshot-probe','--property=Restart=no',
                '/usr/bin/python3',str(p)],check=True)
for _ in range(50):
    if Path('/run/snapshot-probe.sock').exists(): break
    time.sleep(0.1)
assert Path('/run/snapshot-probe.sock').exists()
Path('/var/tmp/snapshot-disk').write_text('before')
os.sync()
''')
        before = self.memory('before')
        # This exact call killed a daemonized HVF QEMU process on the target Mac.
        self.assertEqual(self.monitor('savevm launcher_regression'), '')
        self.assertIn('launcher_regression', self.monitor('info snapshots'))
        self.assertEqual(self.monitor('delvm launcher_regression'), '')

        self.vm.snapshot()
        self.assertEqual(self.memory('after')['value'], 'after')
        self.guest("from pathlib import Path; import os; Path('/var/tmp/snapshot-disk').write_text('after'); os.sync()")
        self.vm.snapshot(restore=True)
        self.assertEqual(self.memory(), before, 'Must restore RAM, process PID and boot ID')
        # Discard clean guest caches: a RAM-only rollback must not disguise a
        # disk rollback failure by serving the old file from restored RAM.
        self.assertEqual(self.guest("from pathlib import Path; Path('/proc/sys/vm/drop_caches').write_text('3\\n'); print(Path('/var/tmp/snapshot-disk').read_text())"), 'before')
        self.vm.list_snapshots()

        # The explicitly selected cold mode must still restore disk and reboot.
        with patch.dict(os.environ, SNAPSHOT='cold-regression', SNAPSHOT_MODE='disk'):
            self.vm.snapshot()
            boot_before_restore = self.guest("from pathlib import Path; print(Path('/proc/sys/kernel/random/boot_id').read_text().strip())")
            self.guest("from pathlib import Path; import os; Path('/var/tmp/snapshot-disk').write_text('cold-after'); os.sync()")
            self.vm.snapshot(restore=True)
            self.assertEqual(self.guest("from pathlib import Path; print(Path('/var/tmp/snapshot-disk').read_text())"), 'before')
            self.assertNotEqual(self.guest("from pathlib import Path; print(Path('/proc/sys/kernel/random/boot_id').read_text().strip())"), boot_before_restore)
        self.vm.stop()
        self.vm.list_snapshots()


if __name__ == '__main__':
    unittest.main()
