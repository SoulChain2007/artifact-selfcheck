"""Create/verify a complete release inventory and reproducible root-layout ZIP."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

MANIFEST = 'release-manifest.json'
EXCLUDED = {'.git', '__pycache__', '.pytest_cache', '.venv'}


def payload(root):
    return sorted(p for p in root.rglob('*') if p.is_file()
                  and p.name != MANIFEST
                  and not any(x in EXCLUDED or x.startswith('_bak_') for x in p.relative_to(root).parts)
                  and p.suffix not in ('.pyc', '.pyo', '.zip', '.log'))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    version = (root / 'VERSION').read_text(encoding='utf-8').strip()
    if f'版本：**{version}**' not in (root / 'SKILL.md').read_text(encoding='utf-8-sig'):
        raise ValueError('VERSION and SKILL.md differ')
    return {'schema_version': 1, 'name': 'artifact-selfcheck', 'version': version,
            'license': 'MIT', 'files': {p.relative_to(root).as_posix(): digest(p) for p in payload(root)}}


def verify(root):
    expected = json.loads((root / MANIFEST).read_text(encoding='utf-8'))
    actual = inventory(root)
    if not actual['files']:
        raise ValueError('empty payload')
    if expected != actual:
        missing = sorted(set(expected.get('files', {})) - set(actual['files']))
        added = sorted(set(actual['files']) - set(expected.get('files', {})))
        changed = sorted(k for k in set(actual['files']) & set(expected.get('files', {}))
                         if actual['files'][k] != expected['files'][k])
        raise ValueError(f'release mismatch: missing={missing}, added={added}, changed={changed}')
    return actual


def build(root, output):
    verify(root)
    if output.resolve().is_relative_to(root.resolve()):
        raise ValueError('output must be outside skill root')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for p in sorted(payload(root) + [root / MANIFEST]):
            info = zipfile.ZipInfo(p.relative_to(root).as_posix(), (2026, 10, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            z.writestr(info, p.read_bytes())
    return {'file': str(output.resolve()), 'sha256': digest(output)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command', choices=['manifest', 'verify', 'build'])
    ap.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    try:
        root = args.root.resolve()
        if args.command == 'manifest':
            result = inventory(root)
            (root / MANIFEST).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
        elif args.command == 'verify':
            result = verify(root)
        else:
            if args.output is None:
                raise ValueError('--output is required')
            result = build(root, args.output)
        print(json.dumps({'status': 'CLEAN', 'result': result}, ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError) as e:
        print(json.dumps({'status': 'ERROR', 'error': str(e)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    sys.exit(main())
