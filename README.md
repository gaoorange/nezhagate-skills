# NezhaGate agent skills

Agent Skills that let coding agents (Claude Code, Codex, Cursor and other skill-aware agents) use the
[NezhaGate](https://nezhagate.com) API directly: ask in plain words, and the agent picks the model,
sends your files, waits for the job and saves the result.

[中文说明](README.zh-CN.md)

[![An 8-second clip made with the nezhagate-seedance skill](assets/rooftop-demo.jpg)](assets/rooftop-demo.mp4)

*Made with this skill in one request: `seedance-2.5`, 8 s, 720P, one reference image, generated soundtrack.
[Watch the clip](assets/rooftop-demo.mp4) · [storyboard](assets/rooftop-frames.jpg)*

| Skill | What it does |
|---|---|
| [`nezhagate-seedance`](skills/nezhagate-seedance/SKILL.md) | Text-to-video and video from reference images, videos and audio with ByteDance **Seedance 2.5 / 2.0**, including the per-clip Seedance 2.0 Clip and Seedance 2.5 30s, native soundtrack. Includes a zero-dependency Python helper that lists the models on sale with live prices, checks the request before you pay, then submits, waits and downloads. |

## Install

One line, from our site:

```bash
npx skills add https://nezhagate.com
```

or from this repository:

```bash
npx skills add gaoorange/nezhagate-skills
```

Manual install: copy `skills/nezhagate-seedance/` into your agent's skills folder, for example
`~/.claude/skills/nezhagate-seedance/` for Claude Code or `~/.codex/skills/nezhagate-seedance/` for Codex.

## Set your key

Create a key at <https://nezhagate.com/keys>, then make it available to the agent:

```bash
export NEZHAGATE_API_KEY=your_key            # macOS / Linux
```

```powershell
$env:NEZHAGATE_API_KEY = "your_key"           # Windows PowerShell (current window)
setx NEZHAGATE_API_KEY "your_key"             # Windows, for windows opened later
```

Start the agent from a shell where the variable is set. The skill never needs the key in your project files.

## Try it

```text
Use the nezhagate-seedance skill: make an 8-second 16:9 clip with seedance-2.5 of the woman in ./hero.png
turning to the camera on a rooftop at golden hour, slow dolly in, and save it to ./out/rooftop.mp4.
```

Or run the helper yourself:

```bash
python skills/nezhagate-seedance/scripts/seedance.py --models      # models on sale, live prices
python skills/nezhagate-seedance/scripts/seedance.py --model seedance-2.5 --image ./hero.png \
  --prompt "The woman from @Image1 turns to the camera on a rooftop at golden hour, slow dolly in" \
  --duration 8 --ratio 16:9 --dry-run                              # check the request, submit nothing
python skills/nezhagate-seedance/scripts/seedance.py --model seedance-2.5 --image ./hero.png \
  --prompt "The woman from @Image1 turns to the camera on a rooftop at golden hour, slow dolly in" \
  --duration 8 --ratio 16:9 --out ./out/rooftop.mp4                # submit, wait, download
```

For a long or multi-line prompt, put it in a UTF-8 file and pass `--prompt-file prompt.txt` instead of `--prompt`.

The prompt behind the demo clip:

> Golden-hour rooftop in an old Chinese city. The young woman from @Image1, in a cream trench coat, turns from the
> railing toward the camera; the wind lifts her hair, she hesitates, then breaks into a small relieved smile as distant
> temple bells ring. Slow dolly-in from medium shot to close-up, shallow depth of field, warm rim light, film grain,
> soft strings over the city hum.

## How NezhaGate runs your jobs

- **Failed renders cost nothing**: the amount is reserved at submit and refunded in full if a render fails.
- **Your content stays yours**: prompts and outputs are never used for training; the text of your calls is deleted
  after 30 days and generated files after 60 days ([privacy policy](https://nezhagate.com/privacy)).
- **Live status**: real success rates are published at <https://nezhagate.com/status>.

Some Seedance models bill per second and others per clip, in NezhaGate credits. Current prices: `--models` or
<https://nezhagate.com/en/pricing>.

## For maintainers

`well-known/agent-skills/` holds the [agentskills.io](https://agentskills.io) discovery index and the
archive it points to, served at `https://nezhagate.com/.well-known/agent-skills/`. Rebuild both after editing a skill:

```bash
python tools/build_archive.py
```

## License

MIT
