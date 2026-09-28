"""Check built documentation and proposed public URLs; optionally check live URLs."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from urllib.request import Request, urlopen


class Page(HTMLParser):
    def __init__(self, content: str):
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.targets: list[str] = []
        self.feed(content)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        data = dict(attrs)
        if data.get('id'):
            self.ids.add(data['id'])
        if tag in {'a', 'img', 'iframe', 'script', 'link'}:
            target = data.get('href') or data.get('src')
            if target:
                self.targets.append(target)


def check(root: Path, html: Path, live: bool = False) -> dict:
    pages = {p.resolve(): Page(p.read_text()) for p in html.rglob('*.html')}
    if not pages:
        raise ValueError('No built HTML pages')
    errors: list[str] = []
    public: set[str] = set()
    authored_urls: set[str] = set()
    checked = 0

    def local(origin: Path, target: str) -> None:
        nonlocal checked
        url = urlsplit(target)
        destination = (origin.parent / unquote(url.path)).resolve() if url.path else origin
        checked += 1
        if not destination.exists():
            errors.append(f'{origin}: missing {target}')
        elif url.fragment and destination in pages and unquote(url.fragment) not in pages[destination].ids:
            errors.append(f'{origin}: missing anchor {target}')

    for path, page in pages.items():
        for target in page.targets:
            url = urlsplit(target)
            if not url.scheme and not url.netloc:
                local(path, target)
            else:
                public.add(target)
    for path in [root / 'README.md', root / 'tutorials/README.md', *root.joinpath('docs').rglob('*.md')]:
        if '_build' in path.parts:
            continue
        for target in re.findall(r'\]\(([^)]+)\)', path.read_text()):
            url = urlsplit(target)
            if url.scheme in {'http', 'https'}:
                public.add(target)
                authored_urls.add(target.split('#')[0])
            elif target and not target.startswith('#'):
                local(path, target)
    for target in public:
        url = urlsplit(target)
        relative = None
        if url.netloc == 'github.com' and url.path.startswith('/jayrun-project/jayrun/blob/main/'):
            relative = url.path.split('/blob/main/', 1)[1]
        elif url.netloc == 'raw.githubusercontent.com' and url.path.startswith('/jayrun-project/jayrun/main/'):
            relative = url.path.split('/main/', 1)[1]
        if relative is not None and not (root / unquote(relative)).is_file():
            errors.append(f'Missing proposed GitHub target: {target}')
        if url.netloc == 'jayrun.readthedocs.io' and url.path.startswith('/en/latest/'):
            path = (html / (url.path[len('/en/latest/'):] or 'index.html')).resolve()
            if not path.is_file() or (url.fragment and unquote(url.fragment) not in pages.get(path, Page('')).ids):
                errors.append(f'Missing proposed documentation target: {target}')
    def fetch(url: str) -> dict:
        try:
            with urlopen(Request(url, headers={'User-Agent': 'Jayrun-release-links'}), timeout=20) as response:
                return {'url': url, 'status': response.status}
        except Exception as exc:
            return {'url': url, 'error': str(exc)}
    live_rows = []
    if live:
        with ThreadPoolExecutor(max_workers=4) as pool:
            live_rows = list(pool.map(fetch, sorted(authored_urls)))
        errors.extend(f"Live URL unavailable: {r['url']}: {r['error']}" for r in live_rows if 'error' in r)
    return {'html_pages': len(pages), 'local_targets': checked, 'public_urls': len(public),
            'errors': errors, 'live': live_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    parser.add_argument('--html', type=Path, required=True)
    parser.add_argument('--live', action='store_true', help='Use only after GitHub and RTD deployment completes')
    parser.add_argument('--receipt', type=Path)
    args = parser.parse_args()
    result = check(args.root.resolve(), args.html.resolve(), args.live)
    data = json.dumps(result, indent=2) + '\n'
    if args.receipt:
        args.receipt.write_text(data)
    print(data)
    if result['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
