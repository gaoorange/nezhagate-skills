#!/usr/bin/env python3
"""Rebuild well-known/agent-skills/<skill>.tar.gz and index.json from skills/ (reproducible: same files -> same digest).

    python tools/build_archive.py

Archive layout matches what `npx skills add <site>` expects from an agentskills.io discovery index:
SKILL.md at the archive root, supporting folders beside it."""
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'well-known' / 'agent-skills'
SCHEMA = 'https://schemas.agentskills.io/discovery/0.2.0/schema.json'


def frontmatter(md: str) -> dict:
    m = re.match(r'^---\n(.*?)\n---\n', md, re.S)
    out = {}
    for line in (m.group(1).splitlines() if m else []):
        k, _, v = line.partition(':')
        if v:
            out[k.strip()] = v.strip()
    return out


def build(skill_dir: Path) -> dict:
    files = sorted(p for p in skill_dir.rglob('*') if p.is_file() and '__pycache__' not in p.parts)
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for p in files:
            data = p.read_bytes().replace(b'\r\n', b'\n')
            info = tarfile.TarInfo(p.relative_to(skill_dir).as_posix())
            info.size, info.mtime, info.uid, info.gid, info.uname, info.gname = len(data), 0, 0, 0, '', ''
            info.mode = 0o755 if p.suffix == '.py' else 0o644
            tar.addfile(info, io.BytesIO(data))
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode='wb', mtime=0, filename='') as g:
        g.write(raw.getvalue())
    blob = gz.getvalue()
    name = skill_dir.name
    (OUT / (name + '.tar.gz')).write_bytes(blob)
    fm = frontmatter((skill_dir / 'SKILL.md').read_text(encoding='utf-8'))
    return {'name': fm.get('name', name), 'type': 'archive', 'description': fm.get('description', ''),
            'url': name + '.tar.gz', 'digest': 'sha256:' + hashlib.sha256(blob).hexdigest()}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    skills = [build(d) for d in sorted((ROOT / 'skills').iterdir()) if (d / 'SKILL.md').is_file()]
    (OUT / 'index.json').write_text(json.dumps({'$schema': SCHEMA, 'skills': skills}, ensure_ascii=False, indent=2) + '\n',
                                    encoding='utf-8')
    for s in skills:
        print(s['name'], s['digest'])


if __name__ == '__main__':
    main()
