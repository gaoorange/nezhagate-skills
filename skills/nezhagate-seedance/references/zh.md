# 在 NezhaGate 上用 Seedance 生成视频

NezhaGate 通过一个 OpenAI 风格的异步接口提供字节跳动的 Seedance 视频模型。本文是基础使用说明：
查型号、组请求、付钱前自检、提交、等待、下载、处理失败。

English: [../SKILL.md](../SKILL.md)

## 规则

1. **从环境变量 `NEZHAGATE_API_KEY` 读取密钥。** 不要把它贴进对话、代码、日志或提交记录。
   每个接口请求都带 `Authorization: Bearer $NEZHAGATE_API_KEY`。创建密钥：<https://nezhagate.com/keys>。
2. **用之前先查型号。** 型号、上限和价格会变，所以本文不列具体数字。
   `python scripts/seedance.py --models` 列出在售的 Seedance 型号和实时价格；
   `python scripts/seedance.py --doc <型号>` 打印该型号的参数和上限（内容同 `https://nezhagate.com/en/docs/<型号>/md`）。
   两个命令都不需要密钥。
3. **提交前先自检**（见下一节）。每次渲染都要花钱、要等几分钟；请求组错了（提示词只剩第一行、
   参考素材没带上）照样计费。
4. **视频是异步任务。** `POST /v1/videos/generations` 返回 HTTP **202** 和任务 id，之后轮询
   `GET /v1/videos/jobs/{id}`，直到 `status` 为 `succeeded` 或 `failed`。
5. **图片都是参考图，不是首帧。** NezhaGate 上的 Seedance 全系没有首帧 / 尾帧控制：图片决定人物、物体、
   场景和风格。按传入顺序在提示词里写 `@Image1`、`@Image2`……点名，视频和音频同理写 `@Video1`、`@Audio1`。
6. **每条成片都带声音，不能关闭。** 对白、音效和配乐由模型按提示词生成，所以不要传 `audio`：
   `false` 在 Seedance 2.5 / 2.0 / 2.0 Fast 上不起作用，在 2.0 Clip / 2.5 30s 上会被拒绝。
   提示词里的台词、旁白和歌词会被念出来或唱出来，声音和画面一起审核；用户不想要人声，就别在提示词里写这些。
7. **参数越界直接返回 HTTP 400 和可读的原因，绝不悄悄改动。** 不扣费。改好请求再提交，不要原样重发。
8. **失败的任务全额退款。** `content_policy`（内容审核未通过）对这份内容是终局：改提示词或素材，不要原样重交。
9. **出片后立刻下载。** 成片链接保留 60 天；NezhaGate 代为托管的参考素材保留 7 天。

## 付钱前先自检

1. 把提示词写进一个 UTF-8 文本文件，用 `--prompt-file` 传。长的或多行的提示词不要直接写在命令行里：
   PowerShell、cmd、bash 都可能在第一个换行处截断，或者弄坏引号。
2. 用户给的每个参考素材都用 `--image`、`--video`、`--audio` 带上（本地路径、链接、`data:` URI 都行；
   本地文件脚本会自动编码）。
3. 先加 `--dry-run` 跑一遍。它什么都不提交、不需要密钥，会打印一份检查结果：

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

4. 和用户的要求逐项对：提示词长度完整、最后一行确实是原文的最后一行；图片 / 视频 / 音频的数量和用户给的
   文件一致；每个 `@ImageN` / `@VideoN` / `@AudioN` 都有对应的文件。有不对的就改，改完再 `--dry-run`；
   都对上了，去掉 `--dry-run` 再跑同一条命令。

以下两种情况脚本会拒绝提交（退出码 2）：提示词点名了没带上的素材（写了 `@Image3`，却只带了两张图）；
整个提示词只有一行标题，比如 `## Scene 1` 或 `【生成目标】`（通常说明多行提示词只剩了第一行）。
确认就是要这样发，才加 `--force`。

如果不用脚本、自己写代码调接口，发送前也要照样检查你要发出的 JSON：提示词长度和最后一行，
以及 `images`、`video_references`、`audio_reference` 各有几项。

## 费用和余额

`--models` 和 `--dry-run` 都会显示价格：按秒计费的型号 = 单价 × 时长，按条计费的型号每条一个价。
提交时冻结这笔钱，渲染失败全额退回；余额不足时提交会返回 HTTP 402。

```bash
python scripts/seedance.py --balance
# 或者
curl -s https://nezhagate.com/v1/dashboard/billing/credit_grants -H "Authorization: Bearer $NEZHAGATE_API_KEY"
# -> {"total_available": 12.34, "credits": 2468, ...}   （单位美元；200 积分 = $1）
```

## 请求字段

`POST https://nezhagate.com/v1/videos/generations`。某个型号接受哪些字段、哪些取值，看它的文档（`--doc <型号>`）。

| 字段 | 类型 | 说明 |
|---|---|---|
| `model` | string | 必填，`--models` 里的型号 id。 |
| `prompt` | string | 必填。长度上限见型号文档：有的按字数算，有的按 UTF-8 字节算（一个汉字 3 字节）。 |
| `duration` | integer | 秒数。别名 `seconds`。 |
| `resolution` | string | `480P` / `720P` / `1080P`，以型号支持为准。 |
| `size` | string | 画幅比例，如 `16:9`、`9:16`。别名 `aspect_ratio`。 |
| `audio` | boolean | 不要传。Seedance 每条成片都带声音，不能关闭：`false` 在 2.5 / 2.0 / 2.0 Fast 上不起作用，在 2.0 Clip / 2.5 30s 上会被拒绝。 |
| `image` | string | 一张参考图。 |
| `images` | array | 多张参考图，依次对应 `@Image1`、`@Image2`……别名 `reference_images`。 |
| `video_references` | array | 参考视频（动作、运镜），只在支持的型号上。 |
| `audio_reference` | string 或 array | 参考音频，只在支持的型号上；必须同时带至少一张参考图或一段参考视频。别名 `audio_references`（二选一，不要都传）。 |

素材可以是公网 `https://` 链接，也可以内联：

- 图片：jpg / png / webp / gif，每张不超过 16 MB；可传链接、`data:image/...;base64,...` 或裸 base64。
- 视频：mp4 / mov，每段不超过 50 MB，单次请求内联合计不超过 100 MB；可传链接或 `data:video/mp4;base64,...`。
- 音频：mp3 / wav / m4a；可传链接或 `data:audio/mpeg;base64,...`。

本地文件要读出字节、编成 `data:` URI 发送，NezhaGate 托管后再交给模型。脚本已经替你做好。

```bash
curl -s https://nezhagate.com/v1/videos/generations \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"seedance-2.5","prompt":"黄昏的天台上，@Image1 里的女人转身望向镜头微笑；镜头缓慢推近。","images":["https://example.com/woman.png"],"duration":8,"resolution":"720P","size":"16:9"}'
# -> 202 {"id":"img_3f9a...","object":"video.generation.job","status":"queued","created":1790000000,"model":"seedance-2.5"}
```

可以一次提交多个任务，多出来的在队列里排队。

## 等待与下载

```bash
curl -s https://nezhagate.com/v1/videos/jobs/img_3f9a... -H "Authorization: Bearer $NEZHAGATE_API_KEY"
```

| `status` | 含义 | 附带字段 |
|---|---|---|
| `queued` | 排队中 | `queue_position`、`eta_seconds` |
| `processing` | 渲染中 | - |
| `succeeded` | 完成 | `data[0].url`（mp4）、`usage` |
| `failed` | 结束并已退款 | `error` = `{message, type, code, param}` |

每 5–10 秒轮询一次。一条视频要几分钟到半小时以上，片子越长越慢，型号页上有最近的出片时间。
不等了任务也会继续跑，之后用同一个 id 再查即可。成功后立刻下载 `data[0].url`。

如果你的命令有运行时长限制：提交时加 `--no-wait`（打印任务 id 后立即退出），之后反复运行
`--job <id> --timeout 300`，直到任务结束。

## 错误处理

提交阶段（POST 的 HTTP 状态码）：

| 状态码 | 含义 | 怎么办 |
|---|---|---|
| 400 | 参数或上限不符，或参考素材被拒（`message` 会写明）；`code` 为 `model_coming_soon` / `model_disabled` 表示该型号或档位未开放 | 改请求；换型号或档位 |
| 401 / 403 | 没带密钥、密钥无效，或密钥限制了来源 IP | 检查 `NEZHAGATE_API_KEY` |
| 402 | 余额不足 | 到 <https://nezhagate.com/billing> 充值 |
| 429 | 限流 | 稍等后重试一次 |
| 503 | 参考素材暂存失败（我方临时问题，未计费） | 稍等后重试一次 |
| 其他 5xx | 网关故障 | 稍等后重试一次 |

任务失败（`status=failed`，看 `error.code`）：

| `error.code` | 含义 | 能否重交 |
|---|---|---|
| `content_policy` | 内容审核未通过；`error.param` 为 `audio` 表示是声音没通过（按提示词生成的声音，或你上传的参考音频） | 不能——改提示词或素材 |
| `render_timeout`、`upstream_unstable`、`wait_timeout` | 渲染没完成（与输入无关） | 可以原样重交 |
| `result_fetch_failed` | 视频已生成，但成片文件多次取回失败（与输入无关） | 可以原样重交 |
| `invalid_material` | 参考素材或提示词无法使用（格式不支持或文件损坏、提示词过长、受限的真人形象） | 先修素材 |
| 其他 | 看 `error.message` | 转告用户 |

不要在失败上打转：最多重交一次，而且只在上表允许时。

## 辅助脚本

`scripts/seedance.py`（Python 3.8+，只用标准库，Windows / macOS / Linux 通用）：

```bash
python scripts/seedance.py --models                       # 在售型号和实时价格
python scripts/seedance.py --doc seedance-2.0-clip        # 某个型号的参数和上限
python scripts/seedance.py --model seedance-2.5 --prompt-file prompt.txt \
  --image hero.png street.jpg --duration 10 --ratio 16:9 --dry-run     # 自检，不提交
python scripts/seedance.py --model seedance-2.5 --prompt-file prompt.txt \
  --image hero.png street.jpg --duration 10 --ratio 16:9 --out walk.mp4   # 提交、等待、下载
python scripts/seedance.py --job img_3f9a... --out walk.mp4  # 继续等一个已提交的任务
python scripts/seedance.py --balance
```

其他选项：`--prompt`（一行的短提示词）、`--video` / `--audio`（参考素材）、`--resolution`、
`--force`、`--no-wait`、`--timeout`（最多等多少秒，默认 3600）、`--poll`。
`--image`、`--video`、`--audio` 可以一次跟多个文件，也可以重复写；顺序就是 `@Image1`、`@Image2`……的顺序。

退出码：0 成功，2 参数错误或自检发现问题，3 鉴权，4 余额，5 请求被拒，6 限流，7 任务失败，
8 超时仍在跑（用 `--job` 续等），9 网络或服务器错误，10 下载失败。
