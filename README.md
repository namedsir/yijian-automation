# 熠剪自动化 (yijian-automation)

TikTok 素材批量混剪流水线：需求表 xlsx 投进共享盘文件夹 → 自动抓素材 → 自动混剪渲染 → 成片按 SPU 归档回共享盘。**全程无人值守。**

- 出片规格：15.000 秒精确 · 无音频流 · 1080×1920 竖屏 · 每条 4~5 镜头随机混剪
- 双模式：**同SPU混剪**（每个成片只用本 SPU 素材）/ **跨SPU混剪**（全表素材混合，出在 `MIX\`）
- 断点续传：中断后重跑同一条命令即可续，已完成的自动跳过
- 素材缓存：同一视频 ID 只下载一次，跨任务复用

---

## 一键安装（Windows）

**方式 A：双击 `install.bat`**（推荐），装完自动检查环境。

**方式 B：手动两条命令**

```bash
pip install -r scripts/requirements.txt
winget install Gyan.FFmpeg
```

环境要求：Python 3.9+、FFmpeg（ffmpeg/ffprobe 在 PATH 里）。

## 安装为 WorkBuddy Skill

把整个 `yijian-automation` 文件夹放到：

```
C:\Users\<你的用户名>\.workbuddy\skills\tk-mix-remix
```

重启 WorkBuddy 对话即生效。之后对 WorkBuddy 说「**TK混剪**」「**跑一下共享盘混剪**」就能触发。

## 共享盘文件夹契约（重要，名字不能改）

```
<共享盘根>\
├── 1-需求表投放\
│   ├── 同SPU混剪\    ← 表放这里 = 每个SPU各出一批（默认每SPU 20条）
│   └── 跨SPU混剪\    ← 表放这里 = 全表素材混合（默认总共 20条，成片在 videos\MIX\）
├── 2-处理中\         ← 系统自动管理，勿动
├── 3-成片输出\       ← 成片 <任务名>\videos\<SPU|MIX>\ + report.csv + 原表存档
└── 4-异常记录\       ← 失败表 + 失败原因.txt + 错误日志.txt
```

**需求表格式**：第一个 sheet，A列 = 素材SPU，B列 = 视频 ID（纯数字），从第 2 行起。

## 命令行直接用（不装 Skill 也行）

```bash
python scripts/process_inbox.py                        # 处理一轮（默认共享盘）
python scripts/process_inbox.py --share "\\服务器\路径\TK视频快速剪辑"   # 自定义共享盘
python scripts/process_inbox.py --dry-run              # 只看队列不处理
```

## 改出片参数

共享盘根目录放 `config.txt`（可选，下次任务生效，用完删掉）：

```
per_spu=20            同SPU模式=每个SPU几条；跨SPU模式=总共几条
duration=15
segments=4-5          镜头数范围，8-10 = 快切风
resolution=1080x1920
```

## 已知限制

- 少数视频 ID 因 TikTok 区域限制解析失败（约 13%），不影响出片数量，明细在 report.csv
- 新电脑素材缓存为空，首轮会重新下载；可从跑过的电脑拷贝 `scripts\material\` 省时间
- 需要 TikTok 素材的网络可达性；解析走公开接口，无需任何账号

## 从 WorkBuddy 技能市场安装

在 WorkBuddy 技能中心搜索「**熠剪**」或「**yijian-automation**」即可一键安装（ClawHub 市场同步）。

## License

MIT-0（MIT No Attribution）
