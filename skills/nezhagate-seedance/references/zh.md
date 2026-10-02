# 在 NezhaGate 上用 Seedance 生成视频

NezhaGate 通过一个 OpenAI 风格的异步接口提供字节跳动的 Seedance 视频模型。本文覆盖：选模型、
传本地参考素材、提交任务、等待出片、下载 mp4、处理失败。

English: [../SKILL.md](../SKILL.md)

## 重要规则

1. **从环境变量 `NEZHAGATE_API_KEY` 读取密钥。** 不要把它贴进对话、代码、日志或提交记录。
   每个请求都带 `Authorization: Bearer $NEZHAGATE_API_KEY`。创建密钥：<https://nezhagate.com/keys>。
2. **视频是异步任务。** `POST /v1/videos/generations` 返回 HTTP **202** 和任务 id，
   之后轮询 `GET /v1/videos/jobs/{id}`，直到 `status` 为 `succeeded` 或 `failed`。不要在 POST 上干等。
3. **模型 id 和参数上限不要凭记忆写。** 目录会变。本次会话里第一次用某个模型前，先查
   `GET /v1/models`（带密钥）和该模型的公开文档 `https://nezhagate.com/en/docs/<model>/md`。下表只是快照。
4. **图片都是参考图，不是首帧。** NezhaGate 上的 Seedance 全系没有首帧/尾帧控制：图片决定人物、物体、
   场景和风格。在提示词里用 `@Image1`、`@Image2`……点名，视频和音频同理用 `@Video1`、`@Audio1`。
5. **参数越界会直接返回 HTTP 400 和可读的原因，绝不悄悄降级。** 看清原因、改好再提交，不要原样重试。
6. **失败的任务全额退款。** `content_policy`（内容审核未通过）对这份内容是终局：改提示词或素材，
   不要原样重交。
7. **出片后立刻下载。** 成片链接保留 60 天；NezhaGate 代为托管的参考素材保留 7 天。

## 模型（2026-10-02 快照，以模型页为准）

| 模型 | 时长 | 分辨率 | 参考素材 图 / 视频 / 音频 | 提示词上限 | 价格 |
|---|---|---|---|---|---|
| `seedance-2.5` | 4–30 秒任意整数（默认 4） | 480P、720P（默认）、1080P（有时会暂停，此时接口返回 `model_coming_soon`，请改用 720P） | 30 / 10 / 10 | 11000 字符 | 480P、720P 每秒 $0.158；1080P 每秒 $0.33 |
| `seedance-2.0` | 5–15 秒（默认 5） | 480P、720P（默认）；1080P 已预告、尚未开放 | 9 / 3 / 3 | 5000 字节（UTF-8） | 480P 每秒 $0.12；720P 每秒 $0.15 |
| `seedance-2.0-fast` | 5–15 秒（默认 5） | 720P | 9 / 3 / 3 | 5000 字节（UTF-8） | 每秒 $0.075 |
| `seedance-2.5-30s` | 固定 30 秒 | 720P | 9 / 0 / 0 | 5000 字节（UTF-8） | 每条 $1.50 |

四个模型通用：画幅 `size` 为 16:9（默认）、9:16、1:1、4:3、3:4（没有 21:9）。`audio`（布尔值，
默认 `true`）控制是否生成音轨；`seedance-2.5-30s` 固定带原生音轨，不接受 `audio` 字段。
按字节计的上限里，一个汉字算 3 字节。参考视频每段最长 30 秒，合计在 `seedance-2.5` 上不超过 30 秒、
在 2.0 系列上不超过 15 秒。实时价格：<https://nezhagate.com/en/pricing>。

怎么选：

- 画质最好、片长最长、要 1080P、参考素材多 → `seedance-2.5`
- 最便宜的草稿和测试 → `seedance-2.0-fast`
- 一条 30 秒长镜头、按条定价 → `seedance-2.5-30s`

## 先查余额

```bash
curl -s https://nezhagate.com/v1/dashboard/billing/credit_grants \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY"
# -> {"total_available": 12.34, "credits": 2468, ...}   （单位美元；200 积分 = $1）
```

提交前先估价：按秒计费的模型是「单价 × 时长」（`seedance-2.5` 720P 10 秒 = $1.58）；
`seedance-2.5-30s` 每条 $1.50。提交时冻结这笔钱，余额不足会返回 HTTP 402。

## 提交

`POST https://nezhagate.com/v1/videos/generations`

| 字段 | 类型 | 说明 |
|---|---|---|
| `model` | string | 必填，上表中的模型 id。 |
| `prompt` | string | 必填。写清镜头、主体、动作、运镜、光线、声音；用 `@Image1` / `@Video1` / `@Audio1` 点名参考素材。 |
| `duration` | integer | 秒数，在模型范围内。别名 `seconds`。 |
| `resolution` | string | `480P` / `720P` / `1080P`（以模型支持为准）。 |
| `size` | string | 画幅比例。别名 `aspect_ratio`。 |
| `audio` | boolean | 是否生成音轨（`seedance-2.5-30s` 不接受）。 |
| `image` | string | 一张参考图。 |
| `images` | array | 多张参考图，依次对应 `@Image1`、`@Image2`……别名 `reference_images`。 |
| `video_references` | array | 参考视频（动作、运镜、舞蹈），可与参考图同时传。 |
| `audio_reference` | string 或 array | 参考音频，必须同时带至少一张参考图或一段参考视频。别名 `audio_references`（二选一，不要都传）。 |

素材可以是公网 `https://` 链接，也可以内联：

- 图片：jpg / png / webp / gif，每张不超过 16 MB；可传链接、`data:image/...;base64,...` 或裸 base64。
- 视频：mp4 / mov，可传链接或 `data:video/mp4;base64,...`；每段不超过 50 MB，单次请求内联合计不超过 100 MB。
- 音频：mp3 / wav / m4a，可传链接或 `data:audio/mpeg;base64,...`。

本地文件就读出字节、编成 data URI 发送，NezhaGate 会托管后再交给模型。`scripts/seedance.py` 已经替你做好。

```bash
curl -s https://nezhagate.com/v1/videos/generations \
  -H "Authorization: Bearer $NEZHAGATE_API_KEY" -H 'Content-Type: application/json' \
  -d '{"model":"seedance-2.5","prompt":"黄昏的天台上，@Image1 里的女人转身望向镜头微笑；镜头缓慢推近，暖色轮廓光，远处城市的低鸣。","images":["https://example.com/woman.png"],"duration":8,"resolution":"720P","size":"16:9"}'
# -> 202 {"id":"img_3f9a...","object":"video.generation.job","status":"queued","created":1790000000,"model":"seedance-2.5"}
```

可以一次提交多个任务：每个账号同时渲染一批，其余在队列里排队。

## 轮询与下载

```bash
curl -s https://nezhagate.com/v1/videos/jobs/img_3f9a... -H "Authorization: Bearer $NEZHAGATE_API_KEY"
```

| `status` | 含义 | 附带字段 |
|---|---|---|
| `queued` | 排队中 | `queue_position`、`eta_seconds` |
| `processing` | 渲染中 | - |
| `succeeded` | 完成 | `data[0].url`（mp4）、`usage` |
| `failed` | 结束并已退款 | `error` = `{message, type, code, param}` |

每 5–10 秒轮询一次。一般几分钟出片；30 秒长片和 1080P 可能要 10–20 分钟。等到约 45 分钟还没好就先停：
任务仍在继续，之后用同一个 id 再查即可。成功后立刻下载 `data[0].url`。

## 错误处理

提交阶段（POST 的 HTTP 状态码）：

| 状态码 | 含义 | 怎么办 |
|---|---|---|
| 400 | 参数或上限不符，或参考素材被拒（`message` 会写明）；`code` 为 `model_coming_soon` / `model_disabled` 表示该模型或档位未开放 | 改请求；换模型或档位 |
| 401 / 403 | 没带密钥、密钥无效，或密钥限制了来源 IP | 检查 `NEZHAGATE_API_KEY` |
| 402 | 余额不足 | 到 <https://nezhagate.com/billing> 充值 |
| 429 | 限流 | 稍等后重试一次 |
| 503 | 参考素材暂存失败（我方临时问题，未计费） | 稍等后重试一次 |
| 其他 5xx | 网关故障 | 稍等后重试一次 |

任务失败（`status=failed`，看 `error.code`）：

| `error.code` | 含义 | 能否重交 |
|---|---|---|
| `content_policy` | 内容审核未通过 | 不能——改提示词或素材 |
| `render_timeout`、`upstream_unstable`、`wait_timeout` | 渲染没完成（与输入无关） | 可以原样重交 |
| `invalid_material` | 参考素材或提示词无法使用（格式不支持或文件损坏、提示词过长、受限的真人形象） | 先修素材 |
| 其他 | 看 `error.message` | 转告用户 |

不要在失败上打转：最多重交一次，而且只在上表允许时。

## 辅助脚本

`scripts/seedance.py`（Python 3，只用标准库，Windows / macOS / Linux 通用）：

```bash
python scripts/seedance.py --model seedance-2.5 --prompt "雨夜街道上一只纸船顺水漂流，低机位，柔焦" \
  --duration 6 --ratio 16:9 --out ./boat.mp4
python scripts/seedance.py --model seedance-2.5 --image ./hero.png --image ./street.jpg --video ./move.mp4 \
  --prompt "@Image1 里的男人走过 @Image2 的街道，动作模仿 @Video1" --duration 10 --out ./walk.mp4
python scripts/seedance.py --dry-run ...        # 打印请求（base64 截短）和估价，不联网
python scripts/seedance.py --job img_3f9a...    # 继续等一个已提交的任务
python scripts/seedance.py --balance            # 查余额
```

退出码：0 成功，2 参数错误，3 鉴权，4 余额，5 请求被拒，6 限流，7 任务失败，
8 超时仍在跑（用 `--job` 续等），9 网络或服务器错误，10 下载失败。

## 提示词建议

- 一次写一个镜头：主体、动作、运镜、镜头与光线、情绪、声音。
- 有参考素材时说清每个的用途：「@Image1 的女人、@Image2 的街道、@Video1 的运镜、@Audio1 的音乐」。
  不写点名，模型会自己决定怎么用。
- AI 生成的写实人脸一般能过审；真人照片可能被拒（`invalid_material` 或 `content_policy`）。
