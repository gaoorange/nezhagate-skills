#!/usr/bin/env python3
"""Make a Seedance video on NezhaGate: check -> submit -> wait -> download. Python 3.8+, standard library only.

    python seedance.py --models                 # Seedance models on sale now, with live prices (no key needed)
    python seedance.py --doc seedance-2.5       # one model's parameters and limits (no key needed)
    python seedance.py --model seedance-2.5 --prompt-file prompt.txt --image hero.png --duration 8 --dry-run
    python seedance.py --model seedance-2.5 --prompt-file prompt.txt --image hero.png --duration 8 --out hero.mp4
    python seedance.py --job img_...            # keep waiting for a job you already submitted
    python seedance.py --balance                # account balance

--dry-run builds the request and prints a check: prompt length, first and last line, how many reference
files, which @Image / @Video / @Audio names the prompt uses, and a cost estimate. It submits nothing and
needs no key. A request that was built wrong is billed like any other, so compare the check with what you
meant to send before you submit. The script refuses to submit when the prompt names a reference that is
not attached, or when the whole prompt is one heading line (the rest of a multi-line prompt was lost);
--force overrides that.

The API key is read from NEZHAGATE_API_KEY and is never printed or sent anywhere but the API host.
NEZHAGATE_BASE_URL overrides the base URL (default https://nezhagate.com/v1).
Progress goes to stderr; the result is JSON on stdout.

Exit codes: 0 ok, 2 bad arguments or the check found a problem, 3 auth, 4 balance, 5 request refused,
            6 rate limited, 7 job failed, 8 still running at timeout (re-run with --job),
            9 network or server error, 10 download failed.
"""
import argparse
import base64
import codecs
import json
import mimetypes
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

VERSION = '1.1.0'
DEFAULT_BASE = 'https://nezhagate.com/v1'
UA = 'nezhagate-seedance-skill/' + VERSION
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
    'result_fetch_failed': 'the video was rendered but its file could not be retrieved (not caused by your input) - '
                           'safe to resubmit as is; you were refunded',
    'invalid_material': 'a reference or the prompt could not be used - fix the material first, then resubmit',
}
KINDS = ('image', 'video', 'audio')
MENTION_RE = re.compile(r'@(image|video|audio)(\d+)', re.I)
# A prompt that is nothing but one heading line ("## Scene 1", "【生成目标】", "Shots:") is almost always the first
# line of a multi-line prompt whose rest was lost on the way (shell quoting, reading one line, a broken here-doc).
HEADING_RE = re.compile(r'^(#.*|【[^】]*】|\[[^\]]*\]|「[^」]*」|.*[:：])$')
BOMS = ((codecs.BOM_UTF8, 'utf-8-sig'), (codecs.BOM_UTF32_LE, 'utf-32'), (codecs.BOM_UTF32_BE, 'utf-32'),
        (codecs.BOM_UTF16_LE, 'utf-16'), (codecs.BOM_UTF16_BE, 'utf-16'))


class Fail(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def money(v):
    whole, _, frac = ('%.4f' % v).rstrip('0').partition('.')
    return '$%s.%s' % (whole, frac.ljust(2, '0'))


def clip_text(s, n=80):
    return s if len(s) <= n else s[:n - 3] + '...'


def read_prompt_file(path):
    """Read a prompt file whatever wrote it: UTF-8 with or without BOM, UTF-16 / UTF-32 with BOM (PowerShell's
    Out-File), or GB18030 (Chinese Windows editors). Returns (text, encoding)."""
    try:
        raw = Path(path).expanduser().read_bytes()
    except OSError as e:
        raise Fail(2, 'cannot read --prompt-file: %s' % e)
    for bom, enc in BOMS:
        if raw.startswith(bom):
            try:
                return raw.decode(enc), enc
            except UnicodeDecodeError as e:
                raise Fail(2, '--prompt-file starts like %s but does not decode: %s' % (enc, e))
    for enc in ('utf-8', 'gb18030'):
        try:
            return raw.decode(enc), enc
        except UnicodeDecodeError:
            pass
    raise Fail(2, '--prompt-file is not readable text; save it as UTF-8 and try again')


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
    if a.prompt is not None and a.prompt_file:
        raise Fail(2, 'use either --prompt or --prompt-file, not both')
    if a.prompt_file:
        prompt, enc = read_prompt_file(a.prompt_file)
        if enc not in ('utf-8', 'utf-8-sig'):
            log('note: %s is not UTF-8; read it as %s - check the first and last line below' % (a.prompt_file, enc))
    else:
        prompt = a.prompt or ''
    prompt = '\n'.join(prompt.splitlines()).strip()
    if not prompt:
        raise Fail(2, 'a prompt is required: write it to a UTF-8 file and pass --prompt-file')
    body = {'model': a.model, 'prompt': prompt}
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


def check_request(body):
    """What will actually be sent, in numbers to compare with what the user asked for, plus the problems that
    almost always mean the request was built wrong. Returns (check, problems, warnings)."""
    p = body['prompt']
    lines = [s.strip() for s in p.split('\n') if s.strip()]
    counts = {'image': len(body.get('images') or []), 'video': len(body.get('video_references') or []),
              'audio': len(body.get('audio_reference') or [])}
    named = sorted({(k.lower(), int(n)) for k, n in MENTION_RE.findall(p)}, key=lambda t: (KINDS.index(t[0]), t[1]))
    problems, warnings = [], []
    for kind in KINDS:
        top = max([n for k, n in named if k == kind] or [0])
        if top > counts[kind]:
            have = counts[kind]
            problems.append('the prompt names @%s%d but %d %s file%s attached'
                            % (kind.capitalize(), top, have, kind, ' is' if have == 1 else 's are'))
    if len(lines) == 1 and HEADING_RE.match(lines[0]):
        problems.append('the whole prompt is one heading line (%s); the rest of a multi-line prompt was probably '
                        'lost - write it to a file and pass --prompt-file' % json.dumps(lines[0][:60], ensure_ascii=False))
    if '\\n' in p and len(lines) == 1:
        warnings.append('the prompt contains a literal \\n; for a multi-line prompt use --prompt-file')
    check = {'model': body['model'],
             'duration': body.get('duration', '(model default)'),
             'resolution': body.get('resolution', '(model default)'),
             'size': body.get('size', '(model default)')}
    if 'audio' in body:
        check['audio'] = body['audio']
    check.update({'prompt_chars': len(p), 'prompt_utf8_bytes': len(p.encode('utf-8')), 'prompt_lines': len(lines),
                  'prompt_first_line': clip_text(lines[0]), 'prompt_last_line': clip_text(lines[-1]),
                  'images': counts['image'], 'videos': counts['video'], 'audio_files': counts['audio'],
                  'mentions': ['@%s%d' % (k.capitalize(), n) for k, n in named]})
    return check, problems, warnings


def plural(n, word):
    return '%d %s%s' % (n, word, '' if n == 1 else 's')


def check_line(c):
    return ('%s, %s s, %s, %s; prompt %d chars / %d UTF-8 bytes / %s; %s, %s, %s'
            % (c['model'], c['duration'], c['resolution'], c['size'], c['prompt_chars'], c['prompt_utf8_bytes'],
               plural(c['prompt_lines'], 'line'), plural(c['images'], 'image'), plural(c['videos'], 'video'),
               plural(c['audio_files'], 'audio file')))


def get_public(url, accept, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': UA, 'Accept': accept})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), r.geturl()


def catalog(site, quiet=False):
    """Video models on sale and their prices, from the public price list (no key). None if it cannot be read."""
    try:
        raw, _ = get_public(site + '/api/pricing', 'application/json')
        models = json.loads(raw.decode('utf-8'))['nezhagate']['models']
        return {m['id']: m for m in models if isinstance(m, dict) and m.get('category') == 'video' and m.get('id')}
    except Exception as e:  # the price list only feeds hints and the estimate; never fail a run over it
        if not quiet:
            log('note: could not read the live price list (%s); no cost estimate' % (getattr(e, 'reason', None) or e))
        return None


def price_text(m):
    clip = m.get('per_clip')
    if isinstance(clip, dict) and clip:
        return ', '.join(('%s per clip' if k == 'default' else k + ' %s per clip') % money(v) for k, v in clip.items())
    rates = m.get('per_second')
    if isinstance(rates, dict) and rates:
        return ', '.join('%s %s/s' % (k, money(v)) for k, v in rates.items())
    return 'see the model page'


def estimate(body, cat):
    m = (cat or {}).get(body['model'])
    if not m:
        return None
    clip = m.get('per_clip')
    if isinstance(clip, dict) and clip:
        return clip.get(body.get('resolution'), clip.get('default', next(iter(clip.values()))))
    rates = m.get('per_second') or {}
    res = body.get('resolution') or ('720P' if '720P' in rates else next(iter(rates), None))
    secs = body.get('duration') or (m.get('seconds') or [None])[0]
    if rates.get(res) is None or not secs:
        return None
    return round(rates[res] * secs, 4)


def hints(body, cat):
    """Warnings from the live price list. They never block: the server has the final word and refuses
    anything out of range with a readable HTTP 400, before charging."""
    if cat is None:
        return []
    m = cat.get(body['model'])
    if not m:
        return ['%s is not on the live price list - check the id with --models' % body['model']]
    out = []
    secs, d = m.get('seconds'), body.get('duration')
    if d is not None and isinstance(secs, list) and len(secs) == 2 and not secs[0] <= d <= secs[1]:
        out.append('duration %s is outside %s-%s s for %s' % (d, secs[0], secs[1], body['model']))
    rates, r = m.get('per_second'), body.get('resolution')
    if r and isinstance(rates, dict) and rates and r not in rates:
        out.append('%s has no %s price right now (priced: %s); that tier may be paused'
                   % (body['model'], r, ', '.join(rates)))
    return out


def list_models(site):
    cat = catalog(site, quiet=True)
    if cat is None:
        raise Fail(9, 'could not read the live price list at %s/api/pricing' % site)
    rows = []
    for mid, m in cat.items():
        if 'seedance' not in mid:
            continue
        secs = m.get('seconds') or []
        rows.append({'id': mid, 'name': m.get('name'),
                     'seconds': ('%s' % secs[0] if len(secs) == 2 and secs[0] == secs[1] else '-'.join(map(str, secs))),
                     'price': price_text(m), 'doc': '%s/en/docs/%s/md' % (site, mid), 'page': m.get('page')})
    print(json.dumps({'models': rows,
                      'note': 'Prices in USD (200 credits = $1). Allowed durations, sizes, reference counts and '
                              'prompt limits differ per model: read --doc <id> before the first use.',
                      'source': site + '/api/pricing'}, ensure_ascii=False, indent=2))
    return 0


def show_doc(site, model):
    model = model.strip()
    url = '%s/en/docs/%s/md' % (site, urllib.parse.quote(model))
    try:
        raw, final = get_public(url, 'text/markdown, text/plain', timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise Fail(5, 'no doc for %s - check the id with --models' % model)
        raise Fail(9, 'could not read %s: HTTP %d' % (url, e.code))
    except (urllib.error.URLError, OSError) as e:
        raise Fail(9, 'network error reading %s: %s' % (url, getattr(e, 'reason', e)))
    if '/docs/%s/' % model not in final:
        log('note: %s is no longer on sale; %s is the doc of the model that replaced it' % (model, final))
    text = raw.decode('utf-8', 'replace')
    sys.stdout.write(text if text.endswith('\n') else text + '\n')
    return 0


def shorten(body):
    def cut(v):
        if isinstance(v, str) and v.startswith('data:') and len(v) > 80:
            return v[:48] + '...(%d chars)' % len(v)
        return v
    return {k: ([cut(x) for x in v] if isinstance(v, list) else cut(v)) for k, v in body.items()}


def api_key():
    key = (os.environ.get('NEZHAGATE_API_KEY') or '').strip()
    if not key:
        raise Fail(3, 'NEZHAGATE_API_KEY is not set (create a key at https://nezhagate.com/keys, then '
                      'export NEZHAGATE_API_KEY=... or on Windows: $env:NEZHAGATE_API_KEY = "...")')
    return key


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
            if j.get('usage'):
                result['usage'] = j['usage']
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
    ap = argparse.ArgumentParser(description='Make a Seedance video on NezhaGate: check, submit, wait, download.')
    ap.add_argument('--model', default='seedance-2.5', help='model id (default seedance-2.5; list them with --models)')
    ap.add_argument('--prompt-file', help='read the prompt from a text file (use this for long or multi-line prompts)')
    ap.add_argument('--prompt', help='prompt text, for a short one-line prompt')
    ap.add_argument('--image', action='extend', nargs='+', metavar='FILE',
                    help='reference image(s): local path, URL or data: URI; @Image1, @Image2... in this order')
    ap.add_argument('--video', action='extend', nargs='+', metavar='FILE',
                    help='reference video(s): local mp4/mov, URL or data: URI; @Video1... in this order')
    ap.add_argument('--audio', action='extend', nargs='+', metavar='FILE',
                    help='reference audio: local mp3/wav/m4a, URL or data: URI; @Audio1... in this order')
    ap.add_argument('--duration', type=int, help='seconds (allowed values: see --doc)')
    ap.add_argument('--resolution', help='480P / 720P / 1080P, where the model offers it')
    ap.add_argument('--ratio', help='aspect ratio such as 16:9 or 9:16 (sent as size)')
    ap.add_argument('--no-audio', action='store_true', help='no generated soundtrack (on models that offer the switch)')
    ap.add_argument('--out', help='where to save the mp4 (default ./seedance-<job id>.mp4)')
    ap.add_argument('--dry-run', action='store_true', help='print the check and the request; submit nothing, no key needed')
    ap.add_argument('--force', action='store_true', help='submit even if the check found a problem')
    ap.add_argument('--no-wait', action='store_true', help='print the job id right after submitting and exit')
    ap.add_argument('--job', help='wait for an existing job id instead of submitting')
    ap.add_argument('--timeout', type=int, default=3600,
                    help='seconds to wait before giving up (default 3600); the job keeps running')
    ap.add_argument('--poll', type=int, default=8, help='seconds between polls (default 8)')
    ap.add_argument('--models', action='store_true', help='list the Seedance models on sale with live prices (no key needed)')
    ap.add_argument('--doc', metavar='MODEL', help="print one model's parameters and limits (no key needed)")
    ap.add_argument('--balance', action='store_true', help='print the account balance')
    ap.add_argument('--version', action='version', version='%(prog)s ' + VERSION)
    a = ap.parse_args(argv)
    base = (os.environ.get('NEZHAGATE_BASE_URL') or DEFAULT_BASE).rstrip('/')
    site = base[:-3] if base.endswith('/v1') else base
    try:
        if a.models:
            return list_models(site)
        if a.doc:
            return show_doc(site, a.doc)
        if a.balance:
            status, j = call('GET', base + '/dashboard/billing/credit_grants', api_key())
            if status != 200:
                raise_for(status, j, 'balance')
            print(json.dumps({'usd': j.get('total_available'), 'credits': j.get('credits')}))
            return 0
        if a.job:
            return wait(base, api_key(), a.job, a)
        body = build_body(a)
        check, problems, warnings = check_request(body)
        if a.dry_run:
            cat = catalog(site)
            print(json.dumps({'dry_run': True, 'check': check, 'problems': problems,
                              'warnings': warnings + hints(body, cat), 'estimated_cost_usd': estimate(body, cat),
                              'endpoint': base + '/videos/generations', 'body': shorten(body)},
                             ensure_ascii=False, indent=2))
            if problems and not a.force:
                log('the check found %s - fix the request before submitting' % plural(len(problems), 'problem'))
                return 2
            return 0
        log('check: ' + check_line(check))
        for p in problems:
            log('problem: ' + p)
        if problems and not a.force:
            raise Fail(2, 'not submitted: fix the problems above, or add --force if this really is what you want to send')
        key = api_key()
        cat = catalog(site)
        for w in warnings + hints(body, cat):
            log('warning: ' + w)
        est = estimate(body, cat)
        if est is not None:
            log('estimated cost: %s (reserved at submit, refunded in full if the render fails)' % money(est))
        status, j = call('POST', base + '/videos/generations', key, body, timeout=300)
        if status not in (200, 202):
            raise_for(status, j, 'submit')
        job_id = j.get('id')
        if not job_id:
            raise Fail(9, 'submit returned no job id: %s' % json.dumps(j)[:300])
        log('submitted %s (%s)' % (job_id, body['model']))
        if a.no_wait:
            print(json.dumps({'job_id': job_id, 'status': j.get('status') or 'queued', 'model': body['model'],
                              'estimated_cost_usd': est,
                              'resume': 'python seedance.py --job %s --out <file.mp4>' % job_id}))
            return 0
        return wait(base, key, job_id, a, est)
    except Fail as e:
        log('error: %s' % e)
        return e.code
    except KeyboardInterrupt:
        log('interrupted; a submitted job keeps running - resume with --job <id>')
        return 8


if __name__ == '__main__':
    sys.exit(main())
