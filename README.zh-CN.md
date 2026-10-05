# NezhaGate Agent Skills

让 Claude Code、Codex、Cursor 等支持 skill 的 AI 编程助手直接调用 [NezhaGate](https://nezhagate.com) 接口：
用一句话说出你要什么，助手会自己选模型、上传素材、等任务完成、把成片存到你指定的位置。

[English](README.md)

[![用 nezhagate-seedance skill 一句话生成的 8 秒视频](assets/rooftop-demo.jpg)](assets/rooftop-demo.mp4)

*用这个 skill 一次请求生成：`seedance-2.5`、8 秒、720P、1 张参考图、自带配乐。[看视频](assets/rooftop-demo.mp4) · [分镜](assets/rooftop-frames.jpg)*

| Skill | 能做什么 |
|---|---|
| [`nezhagate-seedance`](skills/nezhagate-seedance/SKILL.md) | 用字节跳动 **Seedance 2.5 / 2.0** 做文生视频，或用参考图、参考视频、参考音频生成视频，包括按条计费的 Seedance 2.0 Clip 和 Seedance 2.5 30s，自带配乐。附带一个零依赖的 Python 脚本：列出在售型号和实时价格，付钱前先检查请求，再提交、等待和下载。 |

详细的中文用法见 [skills/nezhagate-seedance/references/zh.md](skills/nezhagate-seedance/references/zh.md)。

## 安装

一行命令，从我们网站安装：

```bash
npx skills add https://nezhagate.com
```

或者从本仓库安装：

```bash
npx skills add gaoorange/nezhagate-skills
```

也可以手动安装：把 `skills/nezhagate-seedance/` 复制到助手的 skills 目录，比如 Claude Code 是 `~/.claude/skills/nezhagate-seedance/`，Codex 是 `~/.codex/skills/nezhagate-seedance/`。

## 设置 key

在 <https://nezhagate.com/keys> 创建 key，然后设成环境变量：

```bash
export NEZHAGATE_API_KEY=你的key            # macOS / Linux
```

```powershell
$env:NEZHAGATE_API_KEY = "你的key"           # Windows PowerShell（当前窗口）
setx NEZHAGATE_API_KEY "你的key"             # Windows（之后新开的窗口）
```

在设置了这个变量的终端里启动助手即可，key 不需要写进项目文件。

## 试一下

```text
用 nezhagate-seedance skill：拿 ./hero.png 里的女生，用 seedance-2.5 做一段 8 秒 16:9 的视频，
黄昏时分她在屋顶上转身看向镜头，镜头缓慢推近，存到 ./out/rooftop.mp4。
```

也可以自己运行脚本：`--models` 查在售型号和价格，加 `--dry-run` 先检查请求（不提交、不花钱），
长的或多行的提示词写进 UTF-8 文件后用 `--prompt-file` 传。

## NezhaGate 怎么对待你的任务

- **失败不扣费**：提交时冻结费用，渲染失败全额退回。
- **内容只属于你**：提示词和生成结果绝不用于训练；调用的文字内容 30 天后删除，生成文件 60 天后删除（[隐私政策](https://nezhagate.com/privacy)）。
- **状态公开**：真实成功率公布在 <https://nezhagate.com/status>。

Seedance 有的型号按秒计费、有的按条计费，实时价格用 `--models` 查，或见 <https://nezhagate.com/pricing>。

## 许可

MIT
