#!/usr/bin/env python
# -*- coding: utf-8 -*-
r"""
TK混剪 · 共享盘自动收发站（单轮执行）
=====================================
扫描共享盘 1-需求表投放 文件夹中的需求表 xlsx，逐个全自动处理：
  抓素材 -> 生成混剪计划 -> ffmpeg 渲染 -> 成片与报告归档到 3-成片输出

文件夹约定（共享盘根目录下）：
  1-需求表投放\  把需求表 xlsx 放这里即视为下单
  2-处理中\     正在处理的表（脚本自动移入）
  3-成片输出\   成片：<任务名>\videos\<SPU>\*.mp4 + report.csv + 原需求表
  4-异常记录\   处理失败的表 + 错误日志

用法：
  python process_inbox.py                        # 处理一轮然后退出（用默认共享盘）
  python process_inbox.py --share "\\\\服务器\\共享盘\\TK视频快速剪辑"   # 指定共享盘
  python process_inbox.py --dry-run              # 只检查有没有待处理表，不做任何改动

素材全局缓存：本脚本同级目录下的 material\（同一视频 ID 在不同任务间不重复下载）
"""
import argparse
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime

SHARE_DEFAULT = r"\\192.168.1.219\品牌视觉部-新\07-AIGC视觉\AI创意视频\TK视频快速剪辑"

# 投放子文件夹 → 剪辑模式（放哪个夹子就按哪种模式剪，无需改 config.txt）
SUB_NORMAL = "同SPU混剪"
SUB_CROSS = "跨SPU混剪"

# 本技能目录（脚本、素材缓存、工作目录都在这里，换电脑无需改代码）
TOOL_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(TOOL_DIR, "run_all.py")

SHARE = SHARE_DEFAULT
D_INBOX = D_DOING = D_DONE = D_FAIL = ""


def set_share(share):
    """按共享盘根目录推导四个流程文件夹路径"""
    global SHARE, D_INBOX, D_DOING, D_DONE, D_FAIL
    SHARE = share.rstrip("\\/")
    D_INBOX = os.path.join(SHARE, "1-需求表投放")
    D_DOING = os.path.join(SHARE, "2-处理中")
    D_DONE = os.path.join(SHARE, "3-成片输出")
    D_FAIL = os.path.join(SHARE, "4-异常记录")


set_share(SHARE_DEFAULT)
MATERIAL = os.path.join(TOOL_DIR, "material")
WORK_ROOT = os.path.join(TOOL_DIR, "work")

# ---- 默认出片参数（要改默认就在这里改，或在共享盘放 config.txt 覆盖） ----
DEFAULTS = {
    "mode": "normal",   # normal=同SPU混剪, cross=跨SPU混剪
    "per_spu": 20,
    "duration": 15,
    "segments": "4-5",
    "resolution": "1080x1920",
}


def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def read_config():
    """共享盘根目录可选 config.txt：每行 key=value（per_spu/duration/segments/resolution）"""
    cfg = dict(DEFAULTS)
    p = os.path.join(SHARE, "config.txt")
    if os.path.exists(p):
        try:
            for line in open(p, encoding="utf-8"):
                line = line.strip()
                if "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip().lower().replace("-", "_")
                    if k in cfg:
                        if isinstance(cfg[k], str):
                            cfg[k] = v.strip()
                        else:
                            cfg[k] = type(cfg[k])(v.strip())
        except Exception as e:
            log(f"config.txt 读取失败（用默认值）：{e}")
    # mode 合法性兜底
    if cfg.get("mode") not in ("normal", "cross"):
        cfg["mode"] = "normal"
    return cfg


def list_inbox():
    """返回 [(xlsx路径, 模式)]；模式由所在子文件夹决定，根目录散落的表按 config 默认模式处理"""
    if not os.path.isdir(D_INBOX):
        os.makedirs(D_INBOX, exist_ok=True)
    items = []
    for sub, mode in ((SUB_NORMAL, "normal"), (SUB_CROSS, "cross")):
        d = os.path.join(D_INBOX, sub)
        os.makedirs(d, exist_ok=True)
        items += [
            (os.path.join(d, f), mode)
            for f in os.listdir(d)
            if f.lower().endswith(".xlsx") and not f.startswith("~$")
        ]
    # 根目录直接放的表（老习惯）→ 用 config.txt 的 mode（默认 normal）
    items += [
        (os.path.join(D_INBOX, f), None)
        for f in os.listdir(D_INBOX)
        if f.lower().endswith(".xlsx") and not f.startswith("~$")
    ]
    return sorted(items)


def safe_name(name):
    return re.sub(r'[\\/:*?"<>|]', "_", name).strip()


def process_one(xlsx_path, cfg):
    """处理单张需求表，返回 (成功与否, 任务目录或错误信息)"""
    base = safe_name(os.path.splitext(os.path.basename(xlsx_path))[0])
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    task_name = f"{base}_{stamp}"
    doing_path = os.path.join(D_DOING, os.path.basename(xlsx_path))
    task_dir = os.path.join(D_DONE, task_name)
    work_dir = os.path.join(WORK_ROOT, task_name)
    err_log = os.path.join(WORK_ROOT, f"{task_name}.log")

    log(f"=== 开始任务：{task_name} ===")
    try:
        # 网络盘上移动文件偶发抖动，重试 3 次
        for i in range(3):
            try:
                shutil.move(xlsx_path, doing_path)
                break
            except Exception:
                if i == 2:
                    raise
                time.sleep(3)
        os.makedirs(work_dir, exist_ok=True)

        cmd = [sys.executable, ENGINE,
               "--xlsx", doing_path,
               "--out", work_dir,
               "--material-dir", MATERIAL,
               "--per-spu", str(cfg["per_spu"]),
               "--duration", str(cfg["duration"]),
               "--segments", str(cfg["segments"]),
               "--mode", str(cfg["mode"]),
               "--resolution", str(cfg["resolution"])]
        log("执行引擎：" + " ".join(cmd))
        t0 = time.time()
        with open(err_log, "w", encoding="utf-8") as ef:
            p = subprocess.run(cmd, stdout=ef, stderr=subprocess.STDOUT, timeout=6 * 3600)
        elapsed = time.time() - t0
        log(f"引擎退出码 {p.returncode}，耗时 {elapsed/60:.1f} 分钟")

        videos_src = os.path.join(work_dir, "videos")
        n_videos = 0
        if os.path.isdir(videos_src):
            for spu in os.listdir(videos_src):
                src_spu = os.path.join(videos_src, spu)
                if not os.path.isdir(src_spu):
                    continue
                dst_spu = os.path.join(task_dir, "videos", spu)
                os.makedirs(dst_spu, exist_ok=True)
                for f in os.listdir(src_spu):
                    if f.lower().endswith(".mp4"):
                        shutil.copy2(os.path.join(src_spu, f), os.path.join(dst_spu, f))
                        n_videos += 1
        if os.path.exists(os.path.join(work_dir, "report.csv")):
            shutil.copy2(os.path.join(work_dir, "report.csv"), os.path.join(task_dir, "report.csv"))

        if p.returncode != 0 or n_videos == 0:
            raise RuntimeError(f"引擎失败（exit={p.returncode}，成片 {n_videos} 个），详见 {err_log}")

        # 归档：原表 + 日志副本放进任务目录
        shutil.move(doing_path, os.path.join(task_dir, os.path.basename(xlsx_path)))
        shutil.copy2(err_log, os.path.join(task_dir, "处理日志.txt"))
        log(f"=== 任务完成：{task_name}，出片 {n_videos} 个 -> {task_dir} ===")
        return True, task_dir, n_videos
    except Exception as e:
        log(f"!!! 任务失败：{base} —— {e}")
        # 失败的表移到失败记录，附错误日志
        try:
            fail_dir = os.path.join(D_FAIL, task_name)
            os.makedirs(fail_dir, exist_ok=True)
            src = doing_path if os.path.exists(doing_path) else xlsx_path
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(fail_dir, os.path.basename(xlsx_path)))
                if os.path.exists(doing_path):
                    os.remove(doing_path)
            if os.path.exists(err_log):
                shutil.copy2(err_log, os.path.join(fail_dir, "错误日志.txt"))
            with open(os.path.join(fail_dir, "失败原因.txt"), "w", encoding="utf-8") as f:
                f.write(f"{datetime.now()}\n{e}\n")
        except Exception as e2:
            log(f"归档失败记录时出错：{e2}")
        return False, str(e), 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只检查，不处理")
    ap.add_argument("--share", default=SHARE_DEFAULT, help="共享盘根目录（含四个流程文件夹）")
    args = ap.parse_args()
    set_share(args.share)

    inbox = list_inbox()
    if not inbox:
        log("没有待处理的需求表")
        return
    log(f"发现 {len(inbox)} 张待处理需求表")
    if args.dry_run:
        for f, m in inbox:
            mode_txt = m if m else "config默认"
            log(f"  - [{mode_txt}] {f}")
        return

    ok_n, fail_n, total_v = 0, 0, 0
    for f, folder_mode in inbox:
        cfg = read_config()
        if folder_mode:  # 子文件夹优先于 config.txt
            cfg["mode"] = folder_mode
        log(f"任务模式：{cfg['mode']}（{'投放夹指定' if folder_mode else 'config默认'}）"
            f" | 每SPU/总数 {cfg['per_spu']} 条 / {cfg['duration']} 秒 / 镜头 {cfg['segments']} / {cfg['resolution']}")
        ok, info, n = process_one(f, cfg)
        if ok:
            ok_n += 1
            total_v += n
        else:
            fail_n += 1
    log(f"本轮结束：任务成功 {ok_n} / 失败 {fail_n}，共出片 {total_v} 个")


if __name__ == "__main__":
    main()
