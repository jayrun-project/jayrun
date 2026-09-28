"""Validate or export the public source tree and inspect built distributions."""
from __future__ import annotations

import argparse
import ast
import email
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import tomllib
import zipfile

FOLDERS = {'jayrun', 'docs', 'tutorials', '.github'}
FILES = {'.gitignore', '.readthedocs.yaml', 'LICENSE', 'NOTICE', 'pyproject.toml',
         'README.md', 'MANIFEST.in', 'CHANGELOG.md'}
GENERATED = {'.git', '__pycache__', '.ipynb_checkpoints', '_build', 'build', 'dist', 'graphify-out'}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def source_files(root: Path) -> list[Path]:
    return sorted(p for name in FOLDERS | FILES for p in
                  ((root / name).rglob('*') if (root / name).is_dir() else [root / name])
                  if p.is_file() and not any(part in GENERATED or part.endswith('.egg-info')
                                             for part in p.relative_to(root).parts))


def check_tree(root: Path) -> dict[str, str]:
    extra = {p.name for p in root.iterdir()} - FOLDERS - FILES - GENERATED
    extra = {name for name in extra if not name.endswith('.egg-info')}
    require(not extra, f'Unexpected public roots: {sorted(extra)}')
    require(all((root / name).exists() for name in FOLDERS | FILES), 'Missing public root')
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    tree = ast.parse((root / 'jayrun/__init__.py').read_text())
    versions = [ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == '__version__' for t in n.targets)]
    require(versions == [project['version']], 'Runtime/project versions differ')
    require(f"## [{project['version']}]" in (root / 'CHANGELOG.md').read_text(), 'Missing release changelog')
    require((root / 'docs/_static/dashboard_preview.html').is_file(), 'Missing dashboard capture')
    for manifest, sources, outputs in [('docs/_static/visualizations.json', 'sources', 'outputs'),
                                       ('docs/_static/screenshots/manifest.json', 'sources', 'images')]:
        path = root / manifest
        data = json.loads(path.read_text())
        for name, digest in data[sources].items():
            require(Path(name).parts[0] in {'docs', 'jayrun'}, f'Private asset source: {name}')
            require(hashlib.sha256((root / name).read_bytes()).hexdigest() == digest, f'Stale source: {name}')
        for name, value in data[outputs].items():
            digest = value['sha256'] if isinstance(value, dict) else value
            require(hashlib.sha256((path.parent / name).read_bytes()).hexdigest() == digest, f'Stale asset: {name}')
    files = source_files(root)
    for p in files:
        require(not p.is_symlink(), f'Public symlink: {p}')
        require(p.suffix not in {'.pyc', '.sqlite', '.whl'} and p.name != '.env', f'Unexpected asset: {p}')
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def export_tree(root: Path, destination: Path) -> None:
    require(not destination.exists() or not any(destination.iterdir()), 'Export destination must be empty')
    files = source_files(root)
    require(not destination.is_relative_to(root / 'jayrun') and
            not destination.is_relative_to(root / 'docs') and
            not destination.is_relative_to(root / 'tutorials') and
            not destination.is_relative_to(root / '.github'), 'Export cannot be inside a public source folder')
    for p in files:
        require(not p.is_symlink(), f'Public symlink: {p}')
        target = destination / p.relative_to(root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
    check_tree(destination)


def check_dist(root: Path, dist: Path) -> None:
    wheels, sdists = list(dist.glob('*.whl')), list(dist.glob('*.tar.gz'))
    require(len(wheels) == len(sdists) == 1, 'Expected exactly one wheel and one sdist')
    project = tomllib.loads((root / 'pyproject.toml').read_text())['project']
    with zipfile.ZipFile(wheels[0]) as z:
        names = z.namelist()
        require(all(n.startswith(('jayrun/', f"jayrun-{project['version']}.dist-info/")) for n in names), 'Unexpected wheel roots')
        for p in source_files(root):
            rel = str(p.relative_to(root))
            if rel.startswith('jayrun/'):
                require(rel in names and z.read(rel) == p.read_bytes(), f'Missing/stale wheel file: {rel}')
        metadata = email.message_from_bytes(z.read(next(n for n in names if n.endswith('/METADATA'))))
        require(metadata['Version'] == project['version'], 'Wrong wheel version')
        require(metadata['Requires-Python'] == project['requires-python'], 'Wrong Python requirement')
        require(all(dep in metadata.get_all('Requires-Dist', []) for dep in project['dependencies']), 'Wrong dependencies')
        for name in ('LICENSE', 'NOTICE'):
            require(any(n.endswith('/licenses/' + name) for n in names), f'Missing {name}')
    with tarfile.open(sdists[0]) as t:
        names = t.getnames()
        allowed = {'jayrun', 'jayrun.egg-info', 'LICENSE', 'NOTICE', 'CHANGELOG.md',
                   'README.md', 'MANIFEST.in', 'pyproject.toml', 'PKG-INFO', 'setup.cfg'}
        require(all(len(Path(n).parts) < 2 or Path(n).parts[1] in allowed for n in names), 'Private files in sdist')
        require(any(n.endswith('/CHANGELOG.md') for n in names), 'Missing sdist changelog')
        for p in source_files(root):
            rel = str(p.relative_to(root))
            if rel.startswith('jayrun/'):
                member = next((n for n in names if n.endswith('/' + rel)), None)
                require(member is not None and t.extractfile(member).read() == p.read_bytes(), f'Missing/stale sdist file: {rel}')


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--export', type=Path)
    parser.add_argument('--dist', type=Path)
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.export:
        export_tree(root, args.export.resolve())
        root = args.export.resolve()
    receipt = check_tree(root)
    if args.dist:
        check_dist(root, args.dist.resolve())
    if args.receipt:
        args.receipt.write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'PASS public tree: {len(receipt)} files' + ('; distributions verified' if args.dist else ''))


if __name__ == '__main__':
    main()
