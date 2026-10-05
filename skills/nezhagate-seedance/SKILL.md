---
name: nezhagate-seedance
description: Generate videos with ByteDance Seedance (Seedance 2.5, Seedance 2.0, 2.0 Fast, 2.0 Clip, 2.5 30s) through the NezhaGate API (https://nezhagate.com/v1) - text-to-video and video from reference images, reference videos and reference audio. Use when the user asks to make, render or script a Seedance video, mentions seedance / Seedance 2.5 / Seedance 2.0 / NezhaGate, or wants text-to-video, image-to-video or video generation from a coding agent. Covers the live model list and prices, local reference files, a check before paying, submit, polling, download and error handling.
---

# Seedance video on NezhaGate

NezhaGate serves ByteDance's Seedance video models behind one OpenAI-style async endpoint. This is the
basic usage guide: look the model up, build the request, check it before paying, submit, wait, download
and handle errors.

中文版：[references/zh.md](references/zh.md)

## Rules

1. **Read the key from `NEZHAGATE_API_KEY`.** Never paste it into chat, code, logs or commits. Every API
   request sends `Authorization: Bearer $NEZHAGATE_API_KEY`. Keys: <https://nezhagate.com/keys>.
2. **Look the model up before you use it.** Models, limits and prices change, so this guide does not list
   them. `python scripts/seedance.py --models` prints the Seedance models on sale with live prices, and
   `python scripts/seedance.py --doc <model>` prints one model's parameters and limits (the same text as
   `https://nezhagate.com/en/docs/<model>/md`). Neither needs a key.
3. **Check the request before you submit** (next section). A render costs money and takes minutes, and a
   request that was built wrong (a prompt cut to its first line, reference files left out) is billed like
   any other.
4. **Video is asynchronous.** `POST /v1/videos/generations` returns HTTP **202** with a job id. Poll
   `GET /v1/videos/jobs/{id}` until `status` is `succeeded` or `failed`.
5. **Images are references, never first frames.** No Seedance model on NezhaGate has first-frame or
   last-frame control: images set the characters, objects, scene and style. Name them in the prompt as
   `@Image1`, `@Image2`... in the order you send them, and likewise `@Video1`, `@Audio1`.
6. **Out-of-range values are refused with HTTP 400 and a readable message, never silently changed.**
   Nothing is charged. Fix the request; do not resend the same body.
7. **Failed jobs are refunded in full.** A `content_policy` failure is final for that content: change the
   prompt or references instead of resubmitting.
8. **Download the result right away.** Result links are kept for 60 days; reference files NezhaGate hosts
   for you are kept for 7 days.

## Check before you pay

1. Write the prompt to a UTF-8 text file and pass it with `--prompt-file`. Do not put a long or
   multi-line prompt on the command line: PowerShell, cmd and bash can cut it at the first line break or
   break the quoting.
2. Pass every reference file the user gave with `--image`, `--video` and `--audio` (local paths, URLs or
   `data:` URIs; local files are encoded for you).
3. Run the command with `--dry-run`. It submits nothing, needs no key, and prints a check:

   ```json
   "check": {
     "model": "seedance-2.5", "duration": 10, "resolution": "720P", "size": "16:9",
     "prompt_chars": 905, "prompt_utf8_bytes": 2573, "prompt_lines": 23,
     "prompt_first_line": "...", "prompt_last_line": "...",
     "images": 6, "videos": 0, "audio_files": 0,
     "mentions": ["@Image1", "@Image2", "@Image3"]
   },
   "problems": [],
   "estimated_cost_usd": 1.58
   ```

4. Compare it with what the user asked for: the prompt has its full length and its real last line, the
   counts match the files the user gave, and every `@ImageN` / `@VideoN` / `@AudioN` has a file. If
   anything is off, fix it and run `--dry-run` again. Then run the same command without `--dry-run`.

The script refuses to submit (exit code 2) when the prompt names a reference that is not attached
(`@Image3` with two images) or when the whole prompt is a single heading line such as `## Scene 1` or
`【生成目标】`, which usually means the rest of a multi-line prompt was lost. Add `--force` only if that
really is what you want to send.

If you call the API with your own code instead, check the exact JSON body before sending it in the same
way: the prompt's length and last line, and the number of items in `images`, `video_references` and
`audio_reference`.

## Cost and balance

`--models` and `--dry-run` show the price: per-second models cost rate x duration, per-clip models cost
one price per clip. The amount is reserved at submit and refunded in full if the render fails; with too
little balance the submit gets HTTP 402.

```bash
python scripts/seedance.py --balance
# or
curl -s https://nezhagate.com/v1/dashboard/billing/credit_grants -H "Authorization: Bearer $NEZHAGATE_API_KEY"
# -> {"total_available": 12.34, "credits": 2468, ...}   (USD; 200 credits = $1)
```

## Request fields

`POST https://nezhagate.com/v1/videos/generations`. Which fields and values a model takes is in its doc
(`--doc <model>`).

| Field | Type | Notes |
|---|---|---|
| `model` | string | Required. A model id from `--models`. |
| `prompt` | string | Required. The model doc gives the length limit: some models count characters, others UTF-8 bytes (a Chinese character is 3 bytes). |
| `duration` | integer | Seconds. Alias `seconds`. |
| `resolution` | string | `480P` / `720P` / `1080P`, where the model offers it. |
| `size` | string | Aspect ratio such as `16:9` or `9:16`. Alias `aspect_ratio`. |
| `audio` | boolean | Generated soundtrack on or off, on models that offer the switch. |
| `image` | string | One reference image. |
| `images` | array | Several reference images, `@Image1`, `@Image2`... in this order. Alias `reference_images`. |
| `video_references` | array | Reference videos (motion, camera), on models that take them. |
| `audio_reference` | string or array | Reference audio, on models that take it; needs at least one image or video reference. Alias `audio_references` (send one of the two). |

Media can be a public `https://` URL or inline data:

- Images: jpg / png / webp / gif, up to 16 MB each; a URL, `data:image/...;base64,...` or bare base64.
- Videos: mp4 / mov, up to 50 MB each and 100 MB inline per request; a URL or `data:video/mp4;base64,...`.
- Audio: mp3 / wav / m4a; a URL or `data:audio/mpeg;base64,...`.

A local file has to be read and sent as a `data:` URI; NezhaGate hosts it and passes the link on. The
script does this for you.

```bash
curl -s https://nezhagate.com/v1/videos/generations \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"seedance-2.5","prompt":"Golden hour on a rooftop. The woman from @Image1 turns to the camera and smiles; slow dolly in.","images":["https://example.com/woman.png"],"duration":8,"resolution":"720P","size":"16:9"}'
# -> 202 {"id":"img_3f9a...","object":"video.generation.job","status":"queued","created":1790000000,"model":"seedance-2.5"}
```

You can submit several jobs at once; extra ones wait in the queue.

## Wait and download

```bash
curl -s https://nezhagate.com/v1/videos/jobs/img_3f9a... -H "Authorization: Bearer $NEZHAGATE_API_KEY"
```

| `status` | Meaning | Extra fields |
|---|---|---|
| `queued` | Waiting for a slot | `queue_position`, `eta_seconds` |
| `processing` | Rendering | - |
| `succeeded` | Done | `data[0].url` (mp4), `usage` |
| `failed` | Done, refunded | `error` = `{message, type, code, param}` |

Poll every 5-10 seconds. A render takes from a few minutes to more than half an hour; long clips take
longest, and the model page shows recent render times. If you stop waiting, the job keeps running: poll
the same id later. Download `data[0].url` as soon as it succeeds.

If your shell commands have a time limit, submit with `--no-wait` (it prints the job id and exits), then
run `--job <id> --timeout 300` again until the job is done.

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
| `content_policy` | The content was refused by review | No - change the prompt or references |
| `render_timeout`, `upstream_unstable`, `wait_timeout` | The render did not finish (not caused by the input) | Yes, as is |
| `result_fetch_failed` | The video was rendered but its file could not be retrieved (not caused by the input) | Yes, as is |
| `invalid_material` | A reference or the prompt could not be used (unsupported or broken file, overlong prompt, a restricted real-person likeness) | Fix the material first |
| anything else | Read `error.message` | Report it to the user |

Never loop on failures: resubmit at most once, and only when the table says so.

## Helper script

`scripts/seedance.py` (Python 3.8+, standard library only; Windows, macOS, Linux):

```bash
python scripts/seedance.py --models                       # models on sale, live prices
python scripts/seedance.py --doc seedance-2.0-clip        # one model's parameters and limits
python scripts/seedance.py --model seedance-2.5 --prompt-file prompt.txt \
  --image hero.png street.jpg --duration 10 --ratio 16:9 --dry-run     # check, submit nothing
python scripts/seedance.py --model seedance-2.5 --prompt-file prompt.txt \
  --image hero.png street.jpg --duration 10 --ratio 16:9 --out walk.mp4   # submit, wait, download
python scripts/seedance.py --job img_3f9a... --out walk.mp4  # keep waiting for a submitted job
python scripts/seedance.py --balance
```

Other options: `--prompt` (a short one-line prompt), `--video` / `--audio` (reference files),
`--resolution`, `--no-audio`, `--force`, `--no-wait`, `--timeout` (seconds to wait, default 3600),
`--poll`. `--image`, `--video` and `--audio` take several files at once or can be repeated; their order
is the `@Image1`, `@Image2`... order.

Exit codes: 0 ok, 2 bad arguments or the check found a problem, 3 auth, 4 balance, 5 request refused,
6 rate limited, 7 job failed, 8 still running at timeout (resume with `--job`), 9 network or server
error, 10 download failed.
