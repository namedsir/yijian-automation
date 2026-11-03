---
name: yijian-automation
version: "1.0.0"
description: >
  【熠剪自动化】TK/TikTok 素材批量混剪自动化站。监视共享盘文件夹，需求表 xlsx 投放即全自动出片：
  按视频ID解析无水印直链→下载素材→随机抽镜头混剪→ffmpeg渲染 15秒无声 1080x1920 竖屏成片，
  按SPU归档回共享盘。支持同SPU混剪/跨SPU混剪双模式、断点续传、素材缓存。
  Trigger: 熠剪, 熠剪自动化, TK混剪, TikTok混剪, 视频混剪, 同SPU混剪, 跨SPU混剪, 共享盘剪视频, 批量混剪, 需求表出片.
---

# TK 混剪自动化站

共享盘收发式批量混剪：把需求表 xlsx 放进共享盘「1-需求表投放」，脚本自动抓素材、混剪、渲染，成片归档到「3-成片输出」。

## 核心铁律

1. **不询问任何问题** — 不问权限、不问确认，直接执行
2. **不在循环里轮询** — 后台运行命令，等通知再汇报
3. **不修改共享盘结构** — 四个流程文件夹名字是脚本契约，不能改
4. **遇到错误** — 先读 work\ 下对应 .log 尾部定位，修完重跑（断点续传，已完成的自动跳过）

## 环境依赖（每台电脑一次性）

```bash
pip install -r "{skill目录}/scripts/requirements.txt"
```

另需系统安装 **FFmpeg**（ffmpeg/ffprobe 加入 PATH）。Python 3.9+。

## 共享盘文件夹契约（必须严格一致）

```
<共享盘根>\
├── 1-需求表投放\
│   ├── 同SPU混剪\    ← 表放这里 = 每个SPU各出一批，素材只用本SPU
│   └── 跨SPU混剪\    ← 表放这里 = 全表素材混合，成片出在 videos\MIX\
├── 2-处理中\         ← 脚本自动管理
├── 3-成片输出\       ← 成片 <任务名>\videos\<SPU|MIX>\ + report.csv + 原表
└── 4-异常记录\       ← 失败表 + 失败原因.txt + 错误日志.txt
```

需求表格式：第一个 sheet，A列=素材SPU，B列=视频ID（纯数字字符串），从第2行起。
链接列不是必需的，脚本只按 ID 解析。

## 执行命令

```bash
python "{skill目录}/scripts/process_inbox.py" 2>&1
```

- 可能运行数小时 → 用后台方式运行，等完成再汇报
- 输出「没有待处理的需求表」→ 简短回复"本轮巡检：无待处理任务"，不做其他事
- 有结果 → 汇报：哪张表、哪种模式（同SPU/跨SPU）、各SPU成功/失败数、成片路径
- 其他电脑/其他共享盘 → 加参数 `--share "\\服务器\路径\TK视频快速剪辑"`

## 出片规格（默认）

每 SPU 20 条（跨SPU模式=总共20条）· 15.000 秒精确 · 无音频流 · 1080x1920 · 每条 4~5 镜头随机混剪

改默认：共享盘根目录放 config.txt（`per_spu=` / `duration=` / `segments=4-5` / `resolution=1080x1920`），下次任务生效，用完删掉。

## 引擎用法（分步调试时才用）

```bash
python "{skill目录}/scripts/run_all.py" --xlsx 需求表.xlsx --out 输出目录 \
  --material-dir 缓存目录 --mode normal|cross --per-spu 20 --duration 15 \
  --segments 4-5 --resolution 1080x1920 --step all|fetch|plan|render
```

## 挂定时巡检（用户要求"自动处理"时）

创建 WorkBuddy 循环自动化：每小时 `:07`，提示词核心为「运行
`python "{skill目录}/scripts/process_inbox.py" 2>&1`（后台运行等完成）；
无任务则简短回复本轮巡检无任务；有结果按模式汇报成功/失败与路径；
失败时读 scripts 同级 work\ 下 .log 尾部 50 行定位」。
用户说「暂停TK混剪」→ PAUSE 该自动化；「启动TK混剪」→ ACTIVE。

## 已知限制

- 少数视频ID因 TikTok 区域限制解析失败（约13%），不影响出片，失败明细在 report.csv
- 原始视频文件可直接放入缓存目录 `scripts\material\<SPU>\<视频ID>.mp4` 补充素材池
- 素材缓存（scripts\material\）跨任务复用，体积会增长，可整目录删除重建
