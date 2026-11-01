#!/usr/bin/env python3
"""Debian ARM64/QEMU lab for macOS; Python 3 standard library only."""

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parent.parent
STATE = ROOT / '.vm'
IMAGE_NAME = 'debian-13-generic-arm64.qcow2'
IMAGE_URL = 'https://cloud.debian.org/images/cloud/trixie/latest'


def run(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(args):
    return run(args, capture_output=True, text=True).stdout.strip()


def need(condition, message):
    if not condition:
        raise RuntimeError(message)


def sha512(path):
    digest = hashlib.sha512()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def integer(name, default, minimum, maximum):
    value = int(os.environ.get(name, default))
    need(minimum <= value <= maximum, f'{name}: attendu entre {minimum} et {maximum}')
    return value


class VM:
    def __init__(self, name=None):
        self.name = name or os.environ.get('MACHINE_NAME', 'debian-test')
        need(re.fullmatch(r'[a-z][a-z0-9-]{0,30}[a-z0-9]|[a-z]', self.name),
             'MACHINE_NAME: 1 à 32 caractères minuscules, chiffres et tirets')
        self.user = os.environ.get('SSH_USER', 'debian')
        need(re.fullmatch(r'[a-z_][a-z0-9_-]{0,30}', self.user), 'SSH_USER invalide')
        self.port = integer('SSH_PORT_LOCAL', '2222', 1024, 65535)
        self.cpus = integer('VM_CPUS', '2', 1, 32)
        self.memory = integer('VM_MEMORY', '2048', 512, 131072)
        self.timeout = integer('VM_TIMEOUT', '300', 10, 3600)
        self.size = os.environ.get('VM_DISK_SIZE', '20G')
        need(re.fullmatch(r'[1-9][0-9]*(G|M|T)', self.size), 'VM_DISK_SIZE invalide')
        self.folder = STATE / 'machines' / self.name
        self.disk = self.folder / 'disk.qcow2'
        self.pidfile = self.folder / 'qemu.pid'
        self.qmp = STATE / f'{self.name}.qmp'
        need(len(os.fsencode(self.qmp)) < 104, 'Chemin trop long pour le socket QEMU')
        self.key = self.folder / 'id_ed25519'
        self.seed = self.folder / 'seed.iso'
        self.serial = self.folder / 'console.log'
        self.inventory = self.folder / 'inventory.json'

    def running(self):
        if not self.pidfile.exists():
            return False
        try:
            pid = int(self.pidfile.read_text().strip())
            need(pid > 1, 'PID invalide')
            result = subprocess.run(['ps', '-p', str(pid), '-o', 'command='],
                                    capture_output=True, text=True, check=False)
            return (result.returncode == 0 and 'qemu-system-aarch64' in result.stdout
                    and str(self.disk) in result.stdout and str(self.qmp) in result.stdout)
        except (OSError, ValueError, RuntimeError):
            return False

    def firmware(self):
        override = os.environ.get('QEMU_FIRMWARE')
        qemu = shutil.which('qemu-system-aarch64')
        candidates = [Path(override)] if override else []
        if qemu:
            candidates.append(Path(qemu).resolve().parent.parent / 'share/qemu/edk2-aarch64-code.fd')
        candidates += [Path('/opt/homebrew/share/qemu/edk2-aarch64-code.fd')]
        for path in candidates:
            if path.is_file():
                return path
        raise RuntimeError('Firmware introuvable ; définir QEMU_FIRMWARE (edk2-aarch64-code.fd)')

    def doctor(self):
        need(platform.system() == 'Darwin' and platform.machine() == 'arm64',
             'Ce laboratoire cible macOS sur Apple Silicon (ARM64)')
        for name in ['qemu-system-aarch64', 'qemu-img', 'hdiutil', 'ssh', 'ssh-keygen', 'curl']:
            location = shutil.which(name)
            need(location, f'Outil absent : {name}')
            print(f'{name}: {location}', flush=True)
        need('hvf' in output(['qemu-system-aarch64', '-accel', 'help']), 'HVF indisponible')
        print(f'Firmware: {self.firmware()}', flush=True)

    def get_image(self):
        cache = STATE / 'images'
        cache.mkdir(parents=True, exist_ok=True)
        image = cache / IMAGE_NAME
        checksum = cache / f'{IMAGE_NAME}.sha512'
        if image.exists() and checksum.exists():
            need(sha512(image) == checksum.read_text().strip(),
                 f'Cache corrompu : supprimer {image} puis relancer')
            print('Image Debian en cache : SHA-512 vérifié.', flush=True)
            return image
        sums = output(['curl', '--fail', '--location', '--silent', '--show-error',
                       '--retry', '3', '--max-time', '60', f'{IMAGE_URL}/SHA512SUMS'])
        expected = None
        for line in sums.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].lstrip('*') == IMAGE_NAME:
                expected = fields[0]
        need(expected and re.fullmatch(r'[a-f0-9]{128}', expected), 'SHA-512 officiel absent')
        temporary = image.with_suffix('.qcow2.part')
        print(f'Téléchargement de {IMAGE_NAME}…', flush=True)
        try:
            run(['curl', '--fail', '--location', '--show-error', '--retry', '3',
                 '--connect-timeout', '20', '--max-time', '1800',
                 '--output', temporary, f'{IMAGE_URL}/{IMAGE_NAME}'])
            need(sha512(temporary) == expected, 'SHA-512 incorrect : téléchargement rejeté')
            temporary.replace(image)
            checksum.write_text(expected + '\n')
        finally:
            temporary.unlink(missing_ok=True)
        return image

    def prepare(self):
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not self.disk.exists():
            image = self.get_image()
            # Independent sparse copy: deleting the download cache never breaks a VM.
            temporary = self.disk.with_suffix('.qcow2.part')
            try:
                run(['qemu-img', 'convert', '-f', 'qcow2', '-O', 'qcow2', image, temporary])
                run(['qemu-img', 'resize', temporary, self.size])
                temporary.replace(self.disk)
            finally:
                temporary.unlink(missing_ok=True)
        if not self.key.exists():
            run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-C', self.name, '-f', self.key])
        public_key = self.key.with_suffix('.pub').read_text().strip()
        instance = self.folder / 'instance-id'
        if not instance.exists():
            instance.write_text(f'{self.name}-{uuid.uuid4()}\n')
        template = (ROOT / 'vm_config/user-data').read_text()
        need('__SSH_USER__' in template and '__SSH_PUBLIC_KEY__' in template,
             'Les marqueurs utilisateur/clé doivent rester dans vm_config/user-data')
        user_data = template.replace('__SSH_USER__', self.user).replace(
            '__SSH_PUBLIC_KEY__', json.dumps(public_key))
        metadata_template = (ROOT / 'vm_config/meta-data').read_text()
        need('__INSTANCE_ID__' in metadata_template and '__MACHINE_NAME__' in metadata_template,
             'Les marqueurs identifiant/nom doivent rester dans vm_config/meta-data')
        metadata = metadata_template.replace('__INSTANCE_ID__', json.dumps(instance.read_text().strip())).replace(
            '__MACHINE_NAME__', json.dumps(self.name))
        fingerprint = hashlib.sha256((user_data + metadata).encode()).hexdigest()
        fingerprint_file = self.folder / 'seed.sha256'
        if not self.seed.exists() or not fingerprint_file.exists() or fingerprint_file.read_text() != fingerprint:
            seed_files = self.folder / 'cloud-init'
            seed_files.mkdir(exist_ok=True, mode=0o700)
            (seed_files / 'user-data').write_text(user_data)
            (seed_files / 'meta-data').write_text(metadata)
            self.seed.unlink(missing_ok=True)
            run(['hdiutil', 'makehybrid', '-iso', '-joliet', '-default-volume-name',
                 'cidata', '-o', self.seed, seed_files], stdout=subprocess.DEVNULL)
            fingerprint_file.write_text(fingerprint)
        self.write_inventory()

    def ssh_command(self):
        return ['ssh', '-F', '/dev/null', '-i', str(self.key), '-p', str(self.port),
                '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=3',
                '-o', 'StrictHostKeyChecking=accept-new',
                '-o', f'UserKnownHostsFile={self.folder / "known_hosts"}',
                f'{self.user}@127.0.0.1']

    def write_inventory(self):
        data = {'debian_lab': {'hosts': {self.name: {
            'ansible_host': '127.0.0.1', 'ansible_port': self.port,
            'ansible_user': self.user, 'ansible_ssh_private_key_file': str(self.key),
            'ansible_python_interpreter': '/usr/bin/python3',
            'ansible_ssh_common_args': '-F /dev/null -o IdentitiesOnly=yes '
                '-o StrictHostKeyChecking=accept-new '
                f'-o UserKnownHostsFile={self.folder / "known_hosts"}',
        }}}}
        self.inventory.write_text(json.dumps(data, indent=2) + '\n')

    def start(self):
        self.doctor()
        if not self.running():
            self.prepare()
            with socket.socket() as probe:
                # Ignore TIME_WAIT from the preceding boot, but reject an active listener.
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                try:
                    probe.bind(('127.0.0.1', self.port))
                except OSError as error:
                    raise RuntimeError(f'Port {self.port} déjà occupé ; choisir SSH_PORT_LOCAL') from error
            self.pidfile.unlink(missing_ok=True)
            self.qmp.unlink(missing_ok=True)
            print(f'Démarrage de {self.name} : {self.cpus} CPU, {self.memory} Mio, SSH {self.port}', flush=True)
            run(['qemu-system-aarch64', '-name', self.name,
                 '-machine', 'virt', '-accel', 'hvf', '-cpu', 'host',
                 '-smp', self.cpus, '-m', self.memory, '-bios', self.firmware(),
                 '-drive', f'if=none,id=os,file={self.disk},format=qcow2',
                 '-device', 'virtio-blk-pci,drive=os',
                 '-drive', f'if=none,id=seed,file={self.seed},format=raw,readonly=on',
                 '-device', 'virtio-blk-pci,drive=seed',
                 '-netdev', f'user,id=net0,hostfwd=tcp:127.0.0.1:{self.port}-:22',
                 '-device', 'virtio-net-pci,netdev=net0',
                 '-device', 'virtio-rng-pci', '-display', 'none', '-monitor', 'none',
                 '-serial', f'file:{self.serial}',
                 '-qmp', f'unix:{self.qmp},server=on,wait=off',
                 '-pidfile', self.pidfile, '-daemonize'])
        else:
            self.write_inventory()
            print(f'{self.name} fonctionne déjà.', flush=True)
        self.wait_ready()

    def wait_ready(self):
        print('Attente de SSH et de cloud-init…', flush=True)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            need(self.running(), f'QEMU est arrêté ; consulter {self.serial}')
            try:
                result = subprocess.run(self.ssh_command() + ['true'], capture_output=True,
                                        timeout=min(8, max(1, deadline - time.monotonic())), check=False)
                if result.returncode == 0:
                    remaining = max(1, deadline - time.monotonic())
                    ready = subprocess.run(self.ssh_command() + [
                        'sudo cloud-init status --wait --long'], capture_output=True,
                        text=True, timeout=remaining, check=False)
                    need(ready.returncode == 0,
                         'cloud-init a signalé une erreur :\n' + ready.stdout + ready.stderr)
                    print(ready.stdout.strip(), flush=True)
                    print(f'Prêt : make ssh — inventaire : {self.inventory}', flush=True)
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(2)
        raise RuntimeError(f'Délai de {self.timeout}s dépassé ; consulter {self.serial}. '
                           'La VM est conservée pour diagnostic.')

    def qmp_command(self, command):
        with socket.socket(socket.AF_UNIX) as connection:
            connection.settimeout(10)
            connection.connect(str(self.qmp))
            with connection.makefile('rwb', buffering=0) as stream:
                greeting = json.loads(stream.readline())
                need('QMP' in greeting, 'Réponse QMP invalide')
                for number, operation in enumerate(['qmp_capabilities', command]):
                    stream.write((json.dumps({'execute': operation, 'id': number}) + '\n').encode())
                    while True:
                        line = stream.readline()
                        need(line, 'QEMU a fermé QMP sans confirmation')
                        reply = json.loads(line)
                        if reply.get('id') == number:
                            need('error' not in reply, f'Erreur QMP : {reply}')
                            break

    def stop(self):
        if not self.running():
            print(f'{self.name} est arrêté.', flush=True)
            return
        print(f'Arrêt propre de {self.name}…', flush=True)
        self.qmp_command('system_powerdown')
        deadline = time.monotonic() + 90
        while self.running() and time.monotonic() < deadline:
            time.sleep(1)
        need(not self.running(), 'Arrêt non confirmé ; disque conservé, aucune suppression forcée')
        self.pidfile.unlink(missing_ok=True)
        self.qmp.unlink(missing_ok=True)

    def snapshot(self, restore=False):
        name = os.environ.get('SNAPSHOT', '')
        need(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', name),
             'Indiquer SNAPSHOT=nom (lettres, chiffres, point, tiret, underscore)')
        need(self.disk.exists(), 'Créer la VM avec make vm_init')
        was_running = self.running()
        if was_running:
            self.stop()
        try:
            run(['qemu-img', 'snapshot', '-a' if restore else '-c', name, self.disk])
            run(['qemu-img', 'snapshot', '-l', self.disk])
        finally:
            if was_running:
                self.start()

    def destroy(self):
        self.stop()
        if self.folder.exists():
            shutil.rmtree(self.folder)
        self.qmp.unlink(missing_ok=True)
        print(f'{self.name} supprimé ; cache image conservé.', flush=True)


@contextlib.contextmanager
def locked():
    STATE.mkdir(exist_ok=True, mode=0o700)
    need(not STATE.is_symlink(), '.vm doit être un dossier local, pas un lien symbolique')
    # The lock stays outside .vm so clean cannot unlink a lock held by another process.
    lock_name = hashlib.sha256(str(ROOT).encode()).hexdigest()[:24]
    descriptor = os.open(Path(tempfile.gettempdir()) / f'debian-qemu-{lock_name}.lock',
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Une autre opération sur le laboratoire est en cours') from error
        yield


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['doctor', 'init', 'stop', 'status', 'destroy',
                        'create_snapshot', 'restore_snapshot', 'snapshots', 'ssh',
                        'inventory', 'test', 'converge', 'idempotence', 'verify', 'clean'])
    action = parser.parse_args().action
    vm = VM()
    need(not STATE.is_symlink() and not vm.folder.is_symlink(), 'Dossier VM symbolique refusé')
    if action == 'doctor':
        vm.doctor()
    elif action == 'status':
        print(f'{vm.name}: {"démarré" if vm.running() else "arrêté"} — disque: {vm.disk.exists()}')
    elif action == 'ssh':
        need(vm.running(), 'Démarrer la VM avec make vm_init')
        run(vm.ssh_command())
    elif action == 'inventory':
        need(vm.inventory.exists(), 'Créer la VM avec make vm_init')
        print(vm.inventory)
    elif action in ['test', 'converge', 'idempotence', 'verify']:
        role = os.environ.get('ROLE', 'roles/nginx_demo')
        need(role and Path(role).is_dir(), 'Indiquer ROLE=chemin/vers/le/role')
        local_molecule = ROOT / '.venv/bin/molecule'
        molecule = str(local_molecule) if local_molecule.is_file() else shutil.which('molecule')
        need(molecule, 'Molecule absent ; lancer make tools')
        need((Path(role) / 'molecule').is_dir(), 'Scénario Molecule absent dans ce rôle')
        with locked():
            vm.start()
        environment = dict(os.environ, DEBIAN_VM_INVENTORY=str(vm.inventory))
        # Molecule launches ansible-playbook itself: use the same isolated toolchain.
        environment['PATH'] = str(Path(molecule).parent) + os.pathsep + environment.get('PATH', '')
        run([molecule, action], cwd=role, env=environment)
    else:
        with locked():
            if action == 'init':
                vm.start()
            elif action == 'stop':
                vm.stop()
            elif action == 'destroy':
                vm.destroy()
            elif action in ['create_snapshot', 'restore_snapshot']:
                vm.snapshot(restore=action == 'restore_snapshot')
            elif action == 'snapshots':
                need(vm.disk.exists(), 'Créer la VM avec make vm_init')
                need(not vm.running(), 'Arrêter la VM avec make vm_stop pour lister les snapshots')
                run(['qemu-img', 'snapshot', '-l', vm.disk])
            elif action == 'clean':
                for folder in (STATE / 'machines').glob('*'):
                    need(not folder.is_symlink(), 'Dossier machine symbolique refusé')
                    need(not VM(folder.name).running(), f'Arrêter {folder.name} avant make clean')
                shutil.rmtree(STATE)
                print('Dossier .vm supprimé (images, disques et clés du laboratoire).')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        print(f'ERREUR : {error}', file=sys.stderr)
        sys.exit(1)
