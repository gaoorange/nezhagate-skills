---
name: nezhagate-seedance
description: Generate videos with ByteDance Seedance 2.5 and Seedance 2.0 through the NezhaGate API (https://nezhagate.com/v1) - text-to-video, image-to-video with up to 30 reference images, reference videos and audio, 4-30 seconds, 480P/720P/1080P, native soundtrack. Use when the user asks to make, render or script a Seedance video, mentions seedance / Seedance 2.5 / Seedance 2.0 / NezhaGate, or wants text-to-video, image-to-video or video generation from a coding agent. Covers model choice, limits, local files, submit, polling, download, cost and error handling.
---

# Seedance video on NezhaGate

NezhaGate serves ByteDance's Seedance video models behind one OpenAI-style async endpoint.
This skill covers picking a model, sending local reference files, submitting a job, waiting for
it, downloading the mp4 and handling failures.

中文版：[references/zh.md](references/zh.md)

## Critical rules

1. **Read the key from `NEZHAGATE_API_KEY`.** Never paste it into chat, code, logs or commits.
   Every request sends `Authorization: Bearer $NEZHAGATE_API_KEY`. Keys: <https://nezhagate.com/keys>.
2. **Video is asynchronous.** `POST /v1/videos/generations` returns HTTP **202** with a job id.
   Poll `GET /v1/videos/jobs/{id}` until `status` is `succeeded` or `failed`. Never wait on the POST.
3. **Do not trust model ids or limits from memory.** The catalogue changes. Before using a model
   you have not used in this session, check `GET /v1/models` (with the key) and the model's public
   doc `https://nezhagate.com/en/docs/<model>/md`. The table below is a snapshot.
4. **Images are references, never first frames.** No Seedance model on NezhaGate has first-frame
   or last-frame control: images set the characters, objects, scene and style. Refer to them in the
   prompt as `@Image1`, `@Image2`... and likewise `@Video1`, `@Audio1`.
5. **Out-of-range parameters are rejected with HTTP 400 and a readable message, never silently
   downgraded.** Read the message, fix the request, resubmit. Do not retry the same body.
6. **Failed jobs are refunded in full.** A `content_policy` failure is final for that content:
   change the prompt or references instead of resubmitting.
7. **Download the result right away.** Result links are kept for 60 days; reference files that
   NezhaGate hosts for you are kept for 7 days.

## Models (snapshot 2026-10-02 - verify on the model page)

| Model | Duration | Resolution | References img / video / audio | Prompt limit | Price |
|---|---|---|---|---|---|
| `seedance-2.5` | 4-30 s, any integer (default 4) | 480P, 720P (default), 1080P (sometimes paused: the API then answers `model_coming_soon`, use 720P) | 30 / 10 / 10 | 11,000 characters | $0.158/s at 480P and 720P, $0.33/s at 1080P |
| `seedance-2.0` | 5-15 s (default 5) | 480P, 720P (default); 1080P is announced but not open yet | 9 / 3 / 3 | 5,000 UTF-8 bytes | $0.12/s at 480P, $0.15/s at 720P |
| `seedance-2.0-fast` | 5-15 s (default 5) | 720P | 9 / 3 / 3 | 5,000 UTF-8 bytes | $0.075/s |
| `seedance-2.5-30s` | exactly 30 s | 720P | 9 / 0 / 0 | 5,000 UTF-8 bytes | $1.50 per clip |

All four: aspect `size` 16:9 (default), 9:16, 1:1, 4:3 or 3:4 (no 21:9). `audio` (boolean,
default `true`) switches the generated soundtrack on or off; `seedance-2.5-30s` always has native
audio and rejects the `audio` field. A Chinese character counts as 3 bytes against a byte limit.
Reference videos: each at most 30 s, together at most 30 s on `seedance-2.5` and 15 s on the
2.0 models. Live prices: <https://nezhagate.com/en/pricing>.

Which one:

- Best quality, longest clips, 1080P, many references -> `seedance-2.5`
- Cheapest drafts and tests -> `seedance-2.0-fast`
- One 30-second take at a flat price -> `seedance-2.5-30s`

## Check the balance first

```bash
curl -s https://nezhagate.com/v1/dashboard/billing/credit_grants \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY"
# -> {"total_available": 12.34, "credits": 2468, ...}   (USD; 200 credits = $1)
```

Estimate before submitting: per-second models cost `rate x duration`
(a 10 s `seedance-2.5` clip at 720P is $1.58); `seedance-2.5-30s` is $1.50 flat. The amount is
reserved at submit; a submit with too little balance gets HTTP 402.

## Submit

`POST https://nezhagate.com/v1/videos/generations`

| Field | Type | Notes |
|---|---|---|
| `model` | string | Required. One of the ids above. |
| `prompt` | string | Required. Shot, subject, action, camera, light, sound. Name references as `@Image1` / `@Video1` / `@Audio1`. |
| `duration` | integer | Seconds, inside the model's range. Alias `seconds`. |
| `resolution` | string | `480P` / `720P` / `1080P` where the model offers it. |
| `size` | string | Aspect ratio. Alias `aspect_ratio`. |
| `audio` | boolean | Generated soundtrack on/off (not on `seedance-2.5-30s`). |
| `image` | string | One reference image. |
| `images` | array | Several reference images, in `@Image1`, `@Image2`... order. Alias `reference_images`. |
| `video_references` | array | Reference videos (motion, camera, choreography). Can be combined with images. |
| `audio_reference` | string or array | Reference audio. Needs at least one image or video reference. Alias `audio_references` (send one of the two, not both). |

Media can be a public `https://` URL or inline data:

- Images: jpg / png / webp / gif, up to 16 MB each, as a URL, a `data:image/...;base64,...` URI or bare base64.
- Videos: mp4 / mov, as a URL or `data:video/mp4;base64,...`, up to 50 MB each and 100 MB inline per request.
- Audio: mp3 / wav / m4a, as a URL or `data:audio/mpeg;base64,...`.

For a local file, read the bytes and send a data URI; NezhaGate hosts it and passes the link on.
`scripts/seedance.py` does this for you.

```bash
curl -s https://nezhagate.com/v1/videos/generations \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"seedance-2.5","prompt":"Golden hour on a rooftop. The woman from @Image1 turns to the camera and smiles; slow dolly in, warm rim light, distant city hum.","images":["https://example.com/woman.png"],"duration":8,"resolution":"720P","size":"16:9"}'
# -> 202 {"id":"img_3f9a...","object":"video.generation.job","status":"queued","created":1790000000,"model":"seedance-2.5"}
```

You may submit several jobs; each account runs a batch at once and the rest wait in the queue.

## Poll and download

```bash
curl -s https://nezhagate.com/v1/videos/jobs/img_3f9a... -H "Authorization: Bearer $NEZHAGATE_API_KEY"
```

| `status` | Meaning | Extra fields |
|---|---|---|
| `queued` | Waiting for a slot | `queue_position`, `eta_seconds` |
| `processing` | Rendering | - |
| `succeeded` | Done | `data[0].url` (mp4), `usage` |
| `failed` | Done, refunded | `error` = `{message, type, code, param}` |

Poll every 5-10 seconds. Renders usually take a few minutes; 30-second clips and 1080P can take
10-20 minutes. Give up waiting after about 45 minutes: the job keeps running and you can poll the
same id later. When it succeeds, download `data[0].url` straight away.

## Errors

At submit (HTTP status of the POST):

| Status | Meaning | What to do |
|---|---|---|
| 400 | A parameter or limit was violated, or a reference file was refused (`message` says which); `code` = `model_coming_soon` / `model_disabled` for a closed model or tier | Fix the request; pick another model or tier |
| 401 / 403 | Missing or invalid key, or the key is IP-restricted | Check `NEZHAGATE_API_KEY` |
| 402 | Not enough balance | Top up at <https://nezhagate.com/billing> |
| 429 | Rate limited | Wait and retry once |
| 503 | A reference file could not be stored on NezhaGate's side (temporary, not charged) | Retry once after a pause |
| other 5xx | Gateway trouble | Retry once after a pause |

Failed job (`status=failed`, look at `error.code`):

| `error.code` | Meaning | Resubmit? |
|---|---|---|
| `content_policy` | The content was refused by review | No - change prompt or references |
| `render_timeout`, `upstream_unstable`, `wait_timeout` | The render did not finish (not caused by the input) | Yes, as is |
| `invalid_material` | A reference or the prompt could not be used (unsupported or broken file, overlong prompt, a restricted real-person likeness) | Fix the material first |
| anything else | Read `error.message` | Report it to the user |

Never loop on failures: resubmit at most once, and only when the table says so.

## Helper script

`scripts/seedance.py` (Python 3, standard library only, works on Windows, macOS, Linux):

```bash
python scripts/seedance.py --model seedance-2.5 --prompt "A paper boat sails down a rainy street, low angle, soft focus" \
  --duration 6 --ratio 16:9 --out ./boat.mp4
python scripts/seedance.py --model seedance-2.5 --image ./hero.png --image ./street.jpg --video ./move.mp4 \
  --prompt "The man from @Image1 walks through @Image2 copying the moves of @Video1" --duration 10 --out ./walk.mp4
python scripts/seedance.py --dry-run ...        # print the request (base64 shortened) and a cost estimate, no network
python scripts/seedance.py --job img_3f9a...    # resume waiting for an existing job
python scripts/seedance.py --balance            # print the balance
```

Exit codes: 0 ok, 2 bad arguments, 3 auth, 4 balance, 5 request rejected, 6 rate limited,
7 job failed, 8 still running at timeout (re-run with `--job`), 9 network or server error,
10 download failed.

## Prompt tips

- Describe one shot: subject, action, camera move, lens and light, mood, sound.
- With references, say what each one is for: "the woman from @Image1, the street from @Image2,
  the camera move of @Video1, the music of @Audio1". Without tokens the model decides by itself.
- Photoreal AI-generated faces usually pass review; photos of real people may be refused
  (`invalid_material` or `content_policy`).
