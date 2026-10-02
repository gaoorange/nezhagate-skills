#!/usr/bin/env python3
"""Make a Seedance video on NezhaGate: submit -> poll -> download. Python 3.8+, standard library only.

    python seedance.py --model seedance-2.5 --prompt "A paper boat sails down a rainy street" --duration 6 --out boat.mp4
    python seedance.py --image hero.png --video move.mp4 --prompt "The man from @Image1 copies the moves of @Video1" --out walk.mp4
    python seedance.py --dry-run ...      # print the request (base64 shortened) and a cost estimate; no network, no key
    python seedance.py --job img_...      # keep waiting for a job you already submitted
    python seedance.py --balance          # print the account balance

The API key is read from NEZHAGATE_API_KEY and is never printed or sent anywhere but the API host.
NEZHAGATE_BASE_URL overrides the base URL (default https://nezhagate.com/v1).
Progress goes to stderr; the final result is one JSON line on stdout.

Exit codes: 0 ok, 2 bad arguments, 3 auth, 4 balance, 5 request rejected, 6 rate limited,
            7 job failed, 8 still running at timeout (re-run with --job), 9 network or server error, 10 download failed.
"""
import argparse
import base64
import json
import mimetypes
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

VERSION = '1.0.0'
DEFAULT_BASE = 'https://nezhagate.com/v1'
UA = 'nezhagate-seedance-skill/' + VERSION

# Snapshot of 2026-10-02, used ONLY for local warnings and the cost estimate. The server is the authority: it
# rejects anything out of range with a readable HTTP 400 (nothing is charged), and live prices are on
# https://nezhagate.com/en/pricing. Unknown models are passed through without local checks.
MODELS = {
    'seedance-2.5': {'sec': (4, 30), 'res': ('480P', '720P', '1080P'), 'img': 30, 'video': 10, 'audio': 10,
                     'rate': {'480P': 0.158, '720P': 0.158, '1080P': 0.33}},
    'seedance-2.0': {'sec': (5, 15), 'res': ('480P', '720P'), 'img': 9, 'video': 3, 'audio': 3,
                     'rate': {'480P': 0.12, '720P': 0.15}},
    'seedance-2.0-fast': {'sec': (5, 15), 'res': ('720P',), 'img': 9, 'video': 3, 'audio': 3,
                          'rate': {'720P': 0.075}},
    'seedance-2.5-30s': {'sec': (30, 30), 'res': ('720P',), 'img': 9, 'video': 0, 'audio': 0, 'clip': 1.50,
                         'fixed_audio': True},
}
RATIOS = ('16:9', '9:16', '1:1', '4:3', '3:4')
MB = 1024 * 1024
MAX_FILE = {'image': 16 * MB, 'video': 50 * MB}
MAX_INLINE_VIDEO_TOTAL = 100 * MB
EXT_MIME = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp',
            '.gif': 'image/gif', '.mp4': 'video/mp4', '.mov': 'video/quicktime', '.mp3': 'audio/mpeg',
            '.wav': 'audio/wav', '.m4a': 'audio/mp4'}
ADVICE = {
    'content_policy': 'refused by content review - change the prompt or references; do not resubmit as is',
    'render_timeout': 'the render did not finish (not caused by your input) - safe to resubmit as is; you were refunded',
    'upstream_unstable': 'the render connection dropped (not caused by your input) - safe to resubmit as is; you were refunded',
    'wait_timeout': 'the render took too long (not caused by your input) - safe to resubmit as is; you were refunded',
    'invalid_material': 'a reference or the prompt could not be used - fix the material first, then resubmit',
}


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def media_item(spec, kind):
    """A URL or data: URI passes through; a local path becomes a data: URI. Returns (value, local_bytes)."""
    if spec.startswith(('http://', 'https://', 'data:')):
        return spec, 0
    p = Path(spec).expanduser()
    if not p.is_file():
        raise Fail(2, '%s file not found: %s' % (kind, spec))
    size = p.stat().st_size
    limit = MAX_FILE.get(kind)
    if limit and size > limit:
        raise Fail(2, '%s %s is %.1f MB, over the %d MB limit per file' % (kind, p.name, size / MB, limit // MB))
    mime = EXT_MIME.get(p.suffix.lower()) or mimetypes.guess_type(p.name)[0]
    if not mime or not mime.startswith(kind + '/'):
        raise Fail(2, '%s does not look like a %s file (extension %s)' % (p.name, kind, p.suffix or 'none'))
    return 'data:%s;base64,%s' % (mime, base64.b64encode(p.read_bytes()).decode('ascii')), size


def build_body(a):
    prompt = a.prompt
    if a.prompt_file:
        try:
            prompt = Path(a.prompt_file).expanduser().read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError) as e:
            raise Fail(2, 'cannot read --prompt-file: %s' % e)
    if not prompt or not prompt.strip():
        raise Fail(2, 'a prompt is required (--prompt or --prompt-file)')
    body = {'model': a.model, 'prompt': prompt.strip()}
    if a.duration is not None:
        body['duration'] = a.duration
    if a.resolution:
        body['resolution'] = a.resolution.upper()
    if a.ratio:
        body['size'] = a.ratio
    if a.no_audio:
        body['audio'] = False
    video_bytes = 0
    if a.image:
        body['images'] = [media_item(s, 'image')[0] for s in a.image]
    if a.video:
        vids = [media_item(s, 'video') for s in a.video]
        video_bytes = sum(n for _, n in vids)
        body['video_references'] = [v for v, _ in vids]
    if a.audio:
        body['audio_reference'] = [media_item(s, 'audio')[0] for s in a.audio]
    if video_bytes > MAX_INLINE_VIDEO_TOTAL:
        raise Fail(2, 'local reference videos add up to %.0f MB; the inline limit is %d MB per request '
                      '(use public URLs for some of them)' % (video_bytes / MB, MAX_INLINE_VIDEO_TOTAL // MB))
    return body


def warnings_for(body):
    """Local hints from the snapshot table. They never block: the server has the final word."""
    m = MODELS.get(body['model'])
    if not m:
        return ['model %s is not in the local table - skipping local checks' % body['model']]
    out = []
    d = body.get('duration')
    if d is not None and not (m['sec'][0] <= d <= m['sec'][1]):
        out.append('duration %s is outside %d-%d s for %s' % (d, m['sec'][0], m['sec'][1], body['model']))
    r = body.get('resolution')
    if r and r not in m['res']:
        out.append('resolution %s is not open on %s (open: %s)' % (r, body['model'], ', '.join(m['res'])))
    if body.get('size') and body['size'] not in RATIOS:
        out.append('size %s is not one of %s' % (body['size'], ', '.join(RATIOS)))
    for field, key, label in (('images', 'img', 'reference images'), ('video_references', 'video', 'reference videos'),
                              ('audio_reference', 'audio', 'reference audio files')):
        n = len(body.get(field) or [])
        if n > m[key]:
            out.append('%d %s, %s takes at most %d' % (n, label, body['model'], m[key]))
    if body.get('audio_reference') and not (body.get('images') or body.get('video_references')):
        out.append('reference audio needs at least one reference image or video')
    if m.get('fixed_audio') and 'audio' in body:
        out.append('%s always has native audio and rejects the audio field' % body['model'])
    return out


def estimate(body):
    m = MODELS.get(body['model'])
    if not m:
        return None
    if 'clip' in m:
        return m['clip']
    res = body.get('resolution') or ('720P' if '720P' in m['res'] else m['res'][-1])
    rate = m['rate'].get(res)
    if rate is None:
        return None
    return round(rate * (body.get('duration') or m['sec'][0]), 4)


def shorten(body):
    def cut(v):
        if isinstance(v, str) and v.startswith('data:') and len(v) > 80:
            return v[:48] + '...(%d chars)' % len(v)
        return v
    return {k: ([cut(x) for x in v] if isinstance(v, list) else cut(v)) for k, v in body.items()}


def call(method, url, key, body=None, timeout=120):
    data = json.dumps(body).encode('utf-8') if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': UA})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return r.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except ValueError:
            return e.code, {'error': {'message': raw[:300].decode('utf-8', 'replace') or e.reason}}
    except (urllib.error.URLError, OSError) as e:
        raise Fail(9, 'network error talking to %s: %s' % (url.split('/v1')[0], getattr(e, 'reason', e)))


def api_message(obj):
    err = obj.get('error') if isinstance(obj, dict) else None
    if isinstance(err, dict):
        return err.get('code') or '', err.get('message') or json.dumps(err, ensure_ascii=False)
    if isinstance(obj, dict) and obj.get('detail'):
        return '', str(obj['detail'])
    return '', str(err or obj)


def raise_for(status, obj, what):
    code, msg = api_message(obj)
    tag = '%s: HTTP %d%s - %s' % (what, status, (' ' + code) if code else '', msg)
    if status in (401, 403):
        raise Fail(3, tag)
    if status == 402:
        raise Fail(4, tag + ' (top up at https://nezhagate.com/billing)')
    if status == 429:
        raise Fail(6, tag)
    if 400 <= status < 500:
        raise Fail(5, tag)
    raise Fail(9, tag)


def download(url, out):
    # The result host serves public links: never forward the API key to it.
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    part = out.with_name(out.name + '.part')
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=600) as r, open(part, 'wb') as f:
            shutil.copyfileobj(r, f, 1 << 20)
        part.replace(out)
    except (urllib.error.URLError, OSError) as e:
        try:
            part.unlink()
        except OSError:
            pass
        raise Fail(10, 'download failed (%s); the link stays valid for 60 days: %s' % (getattr(e, 'reason', e), url))


def wait(base, key, job_id, a, est=None):
    deadline = time.time() + a.timeout
    last, misses = None, 0
    while True:
        try:
            status, j = call('GET', '%s/videos/jobs/%s' % (base, job_id), key, timeout=60)
        except Fail as e:
            status, j = 0, {'error': {'message': str(e)}}
        if status != 200:
            if status in (401, 403, 404):
                raise_for(status, j, 'poll ' + job_id)
            misses += 1                                  # a network blip or 5xx: the job is still running
            if misses >= 10:
                raise Fail(9, 'polling keeps failing (%s); resume later with --job %s' % (api_message(j)[1], job_id))
            time.sleep(min(60, a.poll * misses))
            continue
        misses = 0
        s = j.get('status')
        if s == 'queued':
            note = 'queued' + (' #%s' % j['queue_position'] if j.get('queue_position') else '') + \
                   (' eta %ss' % j['eta_seconds'] if j.get('eta_seconds') else '')
            if note != last:
                log(note)
                last = note
        elif s != last:
            log(s)
            last = s
        if s == 'succeeded':
            items = j.get('data') or []
            url = items[0].get('url') if items and isinstance(items[0], dict) else None
            if not url:
                raise Fail(9, 'job %s succeeded but returned no url: %s' % (job_id, json.dumps(j)[:300]))
            out = Path(a.out).expanduser() if a.out else Path('seedance-%s.mp4' % job_id)
            download(url, out)
            result = {'job_id': job_id, 'status': 'succeeded', 'model': j.get('model'), 'url': url,
                      'file': str(out.resolve())}
            if est is not None:
                result['estimated_cost_usd'] = est
            print(json.dumps(result, ensure_ascii=False))
            return 0
        if s == 'failed':
            err = j.get('error') or {}
            code = err.get('code', '') if isinstance(err, dict) else ''
            msg = err.get('message', '') if isinstance(err, dict) else str(err)
            print(json.dumps({'job_id': job_id, 'status': 'failed', 'code': code, 'message': msg,
                              'advice': ADVICE.get(code, 'read the message; failed jobs are refunded')},
                             ensure_ascii=False))
            raise Fail(7, 'job %s failed (%s)' % (job_id, code or 'no code'))
        if time.time() > deadline:
            print(json.dumps({'job_id': job_id, 'status': s or 'unknown',
                              'resume': 'python seedance.py --job %s' % job_id}))
            raise Fail(8, 'still %s after %ds; the job keeps running - resume with --job %s' % (s, a.timeout, job_id))
        time.sleep(a.poll)


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description='Make a Seedance video on NezhaGate (submit, wait, download).')
    ap.add_argument('--model', default='seedance-2.5', help='model id (default seedance-2.5)')
    ap.add_argument('--prompt', help='prompt text; name references as @Image1 / @Video1 / @Audio1')
    ap.add_argument('--prompt-file', help='read the prompt from a UTF-8 text file')
    ap.add_argument('--image', action='append', help='reference image: local path, URL or data: URI (repeatable)')
    ap.add_argument('--video', action='append', help='reference video: local mp4/mov, URL or data: URI (repeatable)')
    ap.add_argument('--audio', action='append', help='reference audio: local mp3/wav/m4a, URL or data: URI (repeatable)')
    ap.add_argument('--duration', type=int, help='seconds (model range; seedance-2.5-30s is always 30)')
    ap.add_argument('--resolution', help='480P / 720P / 1080P (where the model offers it)')
    ap.add_argument('--ratio', help='aspect ratio: 16:9 / 9:16 / 1:1 / 4:3 / 3:4')
    ap.add_argument('--no-audio', action='store_true', help='no generated soundtrack (not on seedance-2.5-30s)')
    ap.add_argument('--out', help='where to save the mp4 (default ./seedance-<job id>.mp4)')
    ap.add_argument('--timeout', type=int, default=2700, help='seconds to wait before giving up (default 2700)')
    ap.add_argument('--poll', type=int, default=8, help='seconds between polls (default 8)')
    ap.add_argument('--job', help='resume waiting for an existing job id instead of submitting')
    ap.add_argument('--balance', action='store_true', help='print the balance and exit')
    ap.add_argument('--dry-run', action='store_true', help='print the request and a cost estimate; no network')
    ap.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    a = ap.parse_args(argv)
    base = (os.environ.get('NEZHAGATE_BASE_URL') or DEFAULT_BASE).rstrip('/')
    try:
        if a.dry_run:
            body = build_body(a)
            for w in warnings_for(body):
                log('warning: ' + w)
            print(json.dumps({'dry_run': True, 'endpoint': base + '/videos/generations', 'body': shorten(body),
                              'estimated_cost_usd': estimate(body)}, ensure_ascii=False, indent=2))
            return 0
        key = (os.environ.get('NEZHAGATE_API_KEY') or '').strip()
        if not key:
            raise Fail(3, 'NEZHAGATE_API_KEY is not set (create a key at https://nezhagate.com/keys, then '
                          'export NEZHAGATE_API_KEY=... or on Windows: $env:NEZHAGATE_API_KEY = "...")')
        if a.balance:
            status, j = call('GET', base + '/dashboard/billing/credit_grants', key)
            if status != 200:
                raise_for(status, j, 'balance')
            print(json.dumps({'usd': j.get('total_available'), 'credits': j.get('credits')}))
            return 0
        if a.job:
            return wait(base, key, a.job, a)
        body = build_body(a)
        for w in warnings_for(body):
            log('warning: ' + w)
        est = estimate(body)
        if est is not None:
            log('estimated cost: $%.2f (reserved at submit, refunded in full if the render fails)' % est)
        status, j = call('POST', base + '/videos/generations', key, body, timeout=300)
        if status not in (200, 202):
            raise_for(status, j, 'submit')
        job_id = j.get('id')
        if not job_id:
            raise Fail(9, 'submit returned no job id: %s' % json.dumps(j)[:300])
        log('submitted %s (%s)' % (job_id, body['model']))
        return wait(base, key, job_id, a, est)
    except Fail as e:
        log('error: %s' % e)
        return e.code
    except KeyboardInterrupt:
        log('interrupted; a submitted job keeps running - resume with --job <id>')
        return 8


if __name__ == '__main__':
    sys.exit(main())
