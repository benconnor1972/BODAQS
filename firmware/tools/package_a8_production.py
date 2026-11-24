"""Build and audit a source-pinned A8 pair. Never connects to or flashes devices."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import zipfile

ENVIRONMENTS = ('bodaqs_a8_production', 'bodaqs_a8_integration_candidate')
OFFSETS = {'bootloader.bin': 0, 'partitions.bin': 0x8000,
           'boot_app0.bin': 0xE000, 'firmware.bin': 0x10000}
FLASH_BYTES = 0x400000
PUBLIC_SOURCE_ROOTS = ('firmware/src/', 'firmware/boards/', 'firmware/variants/',
    'firmware/tools/', 'firmware/test/', 'firmware/can-fd/', 'analysis/bodaqs_analysis/',
    'analysis/tests/', 'docs/firmware/', 'docs/analysis/', 'docs/agents/', 'docs/adr/')
PUBLIC_SOURCE_FILES = ('AGENTS.md', 'agents.md', 'GLOSSARY.md', 'requirements.txt', 'firmware/platformio.ini',
    'firmware/bodaqs_4mb.csv', 'firmware/build.sh', 'analysis/pyproject.toml', 'analysis/pytest.ini')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record(path: Path) -> dict:
    return {'bytes': path.stat().st_size, 'sha256': digest(path)}


def public_source_path(name: str) -> bool:
    if name in PUBLIC_SOURCE_FILES:
        return True
    return (name.startswith(PUBLIC_SOURCE_ROOTS) and Path(name).suffix.lower() in
            ('.c', '.h', '.cpp', '.inc', '.s', '.ld', '.cmd', '.py', '.md', '.json', '.syscfg', '.js', '.toml', '.ini')
            or name.startswith(('firmware/test/', 'firmware/can-fd/')) and Path(name).name.lower() == 'makefile')


def audit_merged(image: bytes, folder: Path, segments: dict) -> None:
    if len(image) != max(s['end'] for s in segments.values()):
        raise ValueError('merged image length mismatch')
    cursor = 0
    for name, segment in sorted(segments.items(), key=lambda item: item[1]['offset']):
        start, end = segment['offset'], segment['end']
        if image[start:end] != (folder / name).read_bytes() or image[cursor:start] != b'\xff' * (start - cursor):
            raise ValueError(f'merged image component or erased gap mismatch: {name}')
        cursor = end


def audit_build_timestamp(image: bytes, epoch: int) -> str:
    """FirmwareInfo uses __DATE__/__TIME__; require their fixed value in actual bytes."""
    date = datetime.fromtimestamp(epoch, timezone.utc)
    months = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
    stamp = f'{months[date.month - 1]} {date.day:2d} {date.year} {date:%H:%M:%S}'
    if stamp.encode('ascii') + b'\0' not in image:
        raise ValueError('firmware timestamp does not match SOURCE_DATE_EPOCH')
    return stamp


def audit_images(folder: Path) -> dict:
    """Reject wrong-chip, overlapping or out-of-partition flash components."""
    segments = {}
    names = list(OFFSETS)
    for index, name in enumerate(names):
        path = folder / name
        data = path.read_bytes()
        limit = OFFSETS[names[index + 1]] if index + 1 < len(names) else FLASH_BYTES
        if name == 'partitions.bin':
            limit = 0x9000  # canonical table slot ends where NVS begins
        if not data or OFFSETS[name] + len(data) > limit:
            raise ValueError(f'{name}: empty or exceeds flash segment bounds')
        entry = {**record(path), 'offset': OFFSETS[name], 'end': OFFSETS[name] + len(data)}
        if name in ('bootloader.bin', 'firmware.bin'):
            if len(data) < 24 or data[0] != 0xE9 or struct.unpack_from('<H', data, 12)[0] != 9:
                raise ValueError(f'{name}: expected ESP32-S3 image (chip ID 9)')
            if data[3] >> 4 != 2:
                raise ValueError(f'{name}: expected 4MB image header')
            entry['chip_id'] = 9
        segments[name] = entry
    partitions = []
    data = (folder / 'partitions.bin').read_bytes()
    for offset in range(0, len(data) - 31, 32):
        magic, kind, subtype, start, size, label, flags = struct.unpack_from('<HBBII16sI', data, offset)
        if magic in (0xFFFF, 0xEBEB):
            break
        if magic != 0x50AA or not size or start + size > FLASH_BYTES:
            raise ValueError('invalid partition table or partition exceeds 4MB')
        if start < 0x9000 or any(start < p['end'] and start + size > p['offset'] for p in partitions):
            raise ValueError('overlapping partition bounds')
        partitions.append({'type': kind, 'subtype': subtype, 'offset': start, 'bytes': size,
                           'end': start + size, 'label': label.rstrip(b'\0').decode('ascii'), 'flags': flags})
    app = next((p for p in partitions if p['type'] == 0 and p['offset'] == 0x10000), None)
    if app is None or segments['firmware.bin']['end'] > app['end']:
        raise ValueError('application exceeds app partition at 0x10000')
    expected = [(1, 2, 0x9000, 0x5000, 'nvs', 0), (1, 0, 0xe000, 0x2000, 'otadata', 0),
                (0, 0x10, 0x10000, 0x3e0000, 'app0', 0), (1, 3, 0x3f0000, 0x10000, 'coredump', 0)]
    actual = [(p['type'], p['subtype'], p['offset'], p['bytes'], p['label'], p['flags']) for p in partitions]
    if actual != expected:
        raise ValueError('partition profile does not match canonical unencrypted A8 4MB layout')
    return {'flash_bytes': FLASH_BYTES, 'chip': 'esp32s3', 'segments': segments, 'partitions': partitions}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--peer-bundle', required=True, type=Path, help='sealed r133 reference bundle')
    parser.add_argument('--node-image', type=Path, help='explicit external node image, still checked against r133 hash')
    parser.add_argument('--node-inputs', type=Path, required=True, help='historical node-inputs.json referenced by r133')
    parser.add_argument('--master-command', type=Path, required=True, help='historical r109 master-command.json')
    parser.add_argument('--pio-python', default=sys.executable)
    parser.add_argument('--esptool', type=Path, required=True, help='PlatformIO esptool.py path')
    parser.add_argument('--source-date-epoch', required=True, type=int)
    parser.add_argument('--jobs', default=4, type=int)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    output = args.output.resolve()

    def git(*argv):
        return subprocess.check_output(['git', *argv], cwd=root, text=True).strip()

    def clean_source():
        if git('status', '--porcelain', '--untracked-files=no'):
            raise ValueError('committed clean tracked source required')
        if any(not p.startswith('.scratch/') for p in git('ls-files', '--others', '--exclude-standard').splitlines()):
            raise ValueError('untracked source files present')

    clean_source()
    commit = git('rev-parse', 'HEAD')
    if output.exists() or output.is_relative_to(root):
        raise ValueError('output must be a new directory outside the source checkout')
    peer_root = args.peer_bundle.resolve()
    peer_manifest = json.loads((peer_root / 'BUILD_MANIFEST.json').read_text(encoding='utf-8'))
    output.mkdir(parents=True)
    manifest = {'schema': 'bodaqs.a8-production-package.v1', 'status': 'building',
                'source_commit': commit, 'source_date_epoch': args.source_date_epoch,
                'qualification': 'pending; candidate override is not strict production admission',
                'installation': 'not performed', 'logger': {}, 'peers': {}, 'commands': []}
    env = {**os.environ, 'SOURCE_DATE_EPOCH': str(args.source_date_epoch), 'PYTHONIOENCODING': 'utf-8'}

    def run(label, argv):
        manifest['commands'].append({'label': label, 'argv': argv, 'cwd': str(root)})
        with (output / f'{label}.log').open('wb') as log:
            subprocess.run(argv, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)

    try:
        run('platformio-version', [args.pio_python, '-m', 'platformio', '--version'])
        pio_home = Path(os.environ.get('PLATFORMIO_CORE_DIR', Path.home() / '.platformio'))
        boot_app = pio_home / 'packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin'
        for environment in ENVIRONMENTS:
            pio = [args.pio_python, '-m', 'platformio', 'run', '-d', 'firmware', '-e', environment]
            build = root / 'firmware/.pio/build' / environment
            first = output / environment
            first.mkdir()
            hashes = []
            for attempt in (1, 2):
                run(f'{environment}-{attempt}-clean', [*pio, '-t', 'clean'])
                run(f'{environment}-{attempt}-build', [*pio, '-j', str(args.jobs)])
                current = {}
                for name in ('firmware.bin', 'bootloader.bin', 'partitions.bin', 'firmware.elf', 'firmware.map', 'identity/build-recipe.json'):
                    source = build / name
                    current[name] = record(source)
                    if attempt == 1:
                        shutil.copyfile(source, first / Path(name).name)
                hashes.append(current)
            # ELF debug data may vary by host path; this comparison deliberately stays strict.
            if hashes[0] != hashes[1]:
                raise ValueError(f'{environment}: clean rebuild artifacts differ')
            shutil.copyfile(boot_app, first / 'boot_app0.bin')
            recipe = json.loads((first / 'build-recipe.json').read_text(encoding='utf-8'))
            if recipe['environment'] != environment:
                raise ValueError('mismatched build recipe environment')
            audit = audit_images(first)
            stamp = audit_build_timestamp((first / 'firmware.bin').read_bytes(), args.source_date_epoch)
            for name in ('firmware.bin', 'bootloader.bin'):
                label = f'{environment}-{name}-image-info'
                run(label, [args.pio_python, str(args.esptool), '--chip', 'esp32s3', 'image_info', str(first / name)])
                # esptool reports invalid checksums/digests in text without a failing exit code.
                if '(invalid' in (output / f'{label}.log').read_text(encoding='utf-8'):
                    raise ValueError(f'{name}: esptool image checksum or validation hash invalid')
            run(f'{environment}-partition-info', [args.pio_python, str(pio_home / 'packages/framework-arduinoespressif32/tools/gen_esp32part.py'), str(first / 'partitions.bin')])
            merged = bytearray(b'\xff' * max(s['end'] for s in audit['segments'].values()))
            for name, entry in audit['segments'].items():
                merged[entry['offset']:entry['end']] = (first / name).read_bytes()
            (first / 'recovery-merged.bin').write_bytes(merged)
            audit_merged((first / 'recovery-merged.bin').read_bytes(), first, audit['segments'])
            manifest['logger'][environment] = {**audit, 'recipe_id': recipe['id'], 'compiler_timestamp': stamp,
                                               'clean_rebuild_equal': True, 'build_artifacts': hashes[0],
                                               'merged': record(first / 'recovery-merged.bin')}
            run(f'{environment}-resolved-packages', [args.pio_python, '-m', 'platformio', 'pkg', 'list', '-d', 'firmware', '-e', environment])
        for role in ('master', 'node'):
            folder = output / role
            folder.mkdir()
            paths = [f'artifacts/{role}/bodaqs_can_{role}.out']
            if role == 'master':
                paths.append('artifacts/master/bodaqs_can_master.map')
            entries = []
            for name in paths:
                expected = next((a for a in peer_manifest['artifacts'] if a['path'] == name), None)
                # r133 node identity lives in its own explicit provenance field.
                if expected is None and role == 'node':
                    expected = peer_manifest['node']
                source = args.node_image.resolve() if role == 'node' and args.node_image else peer_root / name
                if expected is None or digest(source) != expected['sha256']:
                    raise ValueError(f'{role}: reference artifact hash mismatch')
                target = folder / source.name
                shutil.copyfile(source, target)
                entries.append({'path': target.relative_to(output).as_posix(), **record(target)})
            manifest['peers'][role] = {'artifacts': entries, 'provenance': 'exact historical r133 selected image; not rebuilt from logger commit',
                                      'reference_manifest_sha256': digest(peer_root / 'BUILD_MANIFEST.json'),
                                      'reference_source_archive': peer_manifest['source_archive'],
                                      'compatibility': 'selected bulk512/version5 native profiles; physical qualification pending'}
        archive = peer_root / peer_manifest['source_archive']['path']
        if digest(archive) != peer_manifest['source_archive']['sha256']:
            raise ValueError('historical source archive hash mismatch')
        if digest(args.node_inputs) != peer_manifest['node']['input_manifest']['sha256']:
            raise ValueError('historical node build-input hash mismatch')
        shutil.copyfile(args.node_inputs, output / 'node-inputs.json')
        shutil.copyfile(args.master_command, output / 'master-command.json')
        manifest['peer_build_inputs'] = {'node': record(output / 'node-inputs.json'),
                                        'master': {**record(output / 'master-command.json'),
                                                   'status': 'historical supplied command; no independent build attestation'}}
        with zipfile.ZipFile(archive) as source:
            changed = []
            for name in source.namelist():
                if name.startswith(('firmware/can-fd/master/', 'firmware/can-fd/node/', 'firmware/can-fd/common/')) and name.endswith(('.c', '.h', '.syscfg', 'makefile')):
                    current = root / name
                    if not current.exists() or current.read_bytes().replace(b'\r\n', b'\n') != source.read(name).replace(b'\r\n', b'\n'):
                        changed.append(name)
            manifest['peer_source_comparison'] = {'reference_archive_sha256': digest(archive),
                'method': 'LF-normalized reference master/node/common source comparison',
                'different_reference_files': changed,
                'meaning': 'review differences with integrated protocol/lifecycle evidence; not runtime attestation'}
        # Preserve public build provenance only; never include private reference configurations.
        (output / 'PEER_PROVENANCE.json').write_text(json.dumps({
            'schema': peer_manifest['schema'], 'source_commit': peer_manifest['source_commit'],
            'source_note': peer_manifest['source_note'], 'source_archive': peer_manifest['source_archive'],
            'protocol': peer_manifest['protocol'], 'node': peer_manifest['node'],
            'artifacts': [a for a in peer_manifest['artifacts'] if a['path'].startswith('artifacts/master/')],
        }, indent=2) + '\n', encoding='utf-8')
        clean_source()
        if git('rev-parse', 'HEAD') != commit:
            raise ValueError('source changed during build')
        # Filter Git's deterministic archive to an explicit public build/test source set.
        archive_bytes = subprocess.check_output(['git', 'archive', '--format=zip', commit], cwd=root)
        selected = []
        excluded = []
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as full, zipfile.ZipFile(output / 'SOURCE.zip', 'w') as public:
            for info in full.infolist():
                if info.is_dir():
                    continue
                if public_source_path(info.filename):
                    public.writestr(info, full.read(info.filename))
                    selected.append(info.filename)
                else:
                    excluded.append(info.filename)
        manifest['source_archive'] = record(output / 'SOURCE.zip')
        manifest['source_archive'].update({'included_paths': selected, 'excluded_paths': excluded,
            'policy': 'public build/test sources and canonical reference docs; no settings/data/media/other apps',
            'rebuild': 'extract and run PlatformIO; packaging again requires original git commit checkout'})
        manifest['build_hooks'] = {p.relative_to(root).as_posix(): record(p)
                                   for p in (root / 'firmware/tools').glob('configure_*.py')}
        manifest['tool_packages'] = {}
        for folder in ('packages', 'platforms'):
            for path in sorted((pio_home / folder).glob('*/package.json')):
                manifest['tool_packages'][path.relative_to(pio_home).as_posix()] = json.loads(path.read_text(encoding='utf-8'))
        manifest['status'] = 'passed'
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        manifest['status'] = 'failed'
        manifest['error'] = str(error)
    finally:
        (output / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        files = sorted(p for p in output.rglob('*') if p.is_file() and p.name != 'SHA256SUMS.txt')
        (output / 'SHA256SUMS.txt').write_text(''.join(f'{digest(p)}  {p.relative_to(output).as_posix()}\n' for p in files), encoding='utf-8')
    print(f"{manifest['status']}: {output}")
    return 0 if manifest['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
