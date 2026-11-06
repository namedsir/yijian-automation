#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
TK 视频混剪一键工具
====================
输入：混剪需求表（xlsx，含列：素材SPU / 素材（视频ID）/ 素材（视频链接）/ 期望生成的视频数量 / 需求）
输出：每个 SPU 若干条 15 秒、无声音、1080x1920 竖屏 mp4

一键运行：
    python run_all.py --xlsx "TK视频混剪需求-261102.xlsx"

分步运行：
    python run_all.py --xlsx 需求.xlsx --step fetch    # 只抓素材
    python run_all.py --xlsx 需求.xlsx --step plan     # 只生成计划
    python run_all.py --xlsx 需求.xlsx --step render   # 只渲染（需先 fetch+plan）

常用参数：
    --per-spu 20          每个 SPU 生成条数（默认 20）
    --duration 15         成片秒数（默认 15）
    --segments 4-5        每条镜头数范围（默认 4-5 随机）
    --out output          输出目录（默认 ./output）
    --workers 4           下载/渲染并发数
    --only-spu 2038,2141  只处理指定 SPU
    --resolution 1080x1920 输出分辨率（默认 1080x1920，其他如 720x1280）

依赖：Python 3.9+，pip install requests openpyxl，系统需安装 ffmpeg/ffprobe 并加入 PATH。
断点续传：已下载素材、已渲染成片自动跳过；失败项写入 report.csv，重跑只补失败。
"""
import argparse
import csv
import json
import os
import random
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
    from openpyxl import load_workbook
except ImportError:
    sys.exit("缺少依赖，请先执行: pip install requests openpyxl")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
TIKTOK_RESOLVER = "https://www.tikwm.com/api/"


def log(msg):
    print(msg, flush=True)


def run_ffmpeg(args):
    p = subprocess.run(args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError((p.stderr or "")[-400:])


# ---------------------------------------------------------------- 读取需求表

def read_rows(xlsx):
    wb = load_workbook(xlsx, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = []
    for r in ws.iter_rows(min_row=2, values_only=True):
        spu, vid = r[0], r[1]
        if vid is None:
            continue
        rows.append({"spu": str(spu).strip(), "id": str(vid).strip()})
    wb.close()
    return rows


# ---------------------------------------------------------------- step 1: 抓素材

def resolve_video(vid):
    """按视频 ID 解析 TikTok 直链（公开解析接口，失败重试 4 次）"""
    for attempt in range(4):
        try:
            resp = requests.get(
                TIKTOK_RESOLVER,
                params={"url": f"https://www.tiktok.com/@/video/{vid}"},
                headers={"User-Agent": UA}, timeout=30)
            j = resp.json()
            if j.get("code") == 0 and j["data"].get("play"):
                d = j["data"]
                return {"play": d["play"], "duration": d.get("duration")}
        except Exception:
            pass
        time.sleep(2 + attempt * 2)
    return None


def probe(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,duration", "-of", "json", path],
            capture_output=True, text=True, timeout=60).stdout
        s = json.loads(out)["streams"][0]
        return {"w": s.get("width"), "h": s.get("height"), "dur": float(s.get("duration") or 0)}
    except Exception:
        return {"w": None, "h": None, "dur": 0.0}


def fetch(rows, mat_dir, workers):
    os.makedirs(mat_dir, exist_ok=True)
    manifest_path = os.path.join(mat_dir, "manifest.json")
    results = []
    if os.path.exists(manifest_path):
        results = json.load(open(manifest_path, encoding="utf-8"))
    done = {r["id"]: r for r in results}

    def work(row):
        vid, spu = row["id"], row["spu"]
        if vid in done and done[vid].get("ok"):
            rec = dict(done[vid])
            f = rec.get("file")
            if f and os.path.exists(f) and os.path.getsize(f) > 50_000:
                return rec  # 缓存记录的文件仍在原位
            f2 = os.path.join(mat_dir, spu, f"{vid}.mp4")
            if os.path.exists(f2) and os.path.getsize(f2) > 50_000:
                # 缓存被迁移过：重指向新路径并重新探测时长
                info = probe(f2)
                rec["file"] = f2
                rec["w"], rec["h"], rec["dur"] = info["w"], info["h"], info["dur"] or rec.get("dur", 0)
                return rec
            # 文件丢了，走下面的重新下载流程
        d = os.path.join(mat_dir, spu)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, f"{vid}.mp4")
        if os.path.exists(path) and os.path.getsize(path) > 50_000:
            info = probe(path)
            rec = {**row, "file": path, "ok": True, **info}
        else:
            meta = resolve_video(vid)
            if not meta:
                return {**row, "ok": False, "err": "resolve_failed"}
            try:
                tmp = path + ".part"
                with requests.get(meta["play"], headers={"User-Agent": UA},
                                  timeout=120, stream=True) as resp:
                    resp.raise_for_status()
                    with open(tmp, "wb") as f:
                        for chunk in resp.iter_content(1 << 20):
                            f.write(chunk)
                os.replace(tmp, path)
                info = probe(path)
                rec = {**row, "file": path, "ok": True,
                       "dur": info["dur"] or float(meta.get("duration") or 0),
                       "w": info["w"], "h": info["h"]}
            except Exception as e:
                return {**row, "ok": False, "err": f"download_failed:{type(e).__name__}"}
        return rec

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, r) for r in rows]
        for i, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()  # as_completed 返回的是 Future，必须取结果
            results = [r for r in results if r["id"] != rec["id"]] + [rec]
            log(f"[fetch {i}/{len(rows)}] {rec['spu']} {rec['id']} "
                f"{'OK %.1fs' % rec.get('dur', 0) if rec.get('ok') else 'FAIL ' + str(rec.get('err'))}")
    json.dump(results, open(manifest_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    ok = [r for r in results if r.get("ok")]
    log(f"抓取完成：成功 {len(ok)} / {len(results)}")
    return results


# ---------------------------------------------------------------- step 2: 生成计划

def plan(results, args, seed=20261102):
    rng = random.Random(seed)
    fps = 30
    total_f = args.duration * fps
    lo_seg, hi_seg = (args.segments.split("-") + ["5"])[:2]
    lo_seg, hi_seg = int(lo_seg), int(hi_seg)
    pools = {}
    for r in results:
        if r.get("ok") and r.get("dur", 0) > 2.0:
            pools.setdefault(r["spu"], []).append(r)
    if args.only_spu:
        pools = {k: v for k, v in pools.items() if k in args.only_spu}
    if args.mode == "cross":
        # 跨SPU混剪：全表素材合并成一个大池，per_spu 代表总共出几条
        allclips = [c for clips in pools.values() for c in clips]
        pools = {"MIX": allclips} if allclips else {}
        log(f"[plan] 跨SPU模式：合并素材池 {len(allclips)} 条，出片 {args.per_spu} 条")
    plan_out = {}
    for spu, clips in sorted(pools.items()):
        variants = []
        for v in range(1, args.per_spu + 1):
            nseg = rng.randint(lo_seg, hi_seg)
            nseg = min(nseg, len(clips))
            segs_f = [total_f // nseg] * nseg
            for i in range(total_f - sum(segs_f)):
                segs_f[i] += 1
            chosen = rng.sample(clips, nseg)
            rng.shuffle(chosen)
            items, cursor, used = [], 0, set()
            for clip, df in zip(chosen, segs_f):
                seg_s = df / fps
                hi = max(0.8, clip["dur"] - seg_s - 0.4)
                start = round(rng.uniform(0.8, hi), 2)
                guard = 0
                while (clip["id"], round(start, 1)) in used and guard < 30:
                    start = round(rng.uniform(0.8, hi), 2)
                    guard += 1
                used.add((clip["id"], round(start, 1)))
                items.append({"videoId": clip["id"], "file": clip["file"],
                              "fromFrame": cursor, "durationInFrames": df,
                              "sourceStartFromInSeconds": start})
                cursor += df
            variants.append({"spu": spu, "variant": v, "items": items})
        plan_out[spu] = variants
        log(f"[plan] SPU {spu}: {len(variants)} 条, 素材池 {len(clips)}")
    plan_path = os.path.join(args.out, "plan.json")
    json.dump(plan_out, open(plan_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    log(f"计划完成：共 {sum(len(v) for v in plan_out.values())} 条 -> {plan_path}")
    return plan_out


# ---------------------------------------------------------------- step 3: 渲染

def render_one(variant, out_dir, resolution, crf=20, bgm=None, bgm_start=0.0,
               bgm_volume=0.0, fade=0.25, force=False):
    spu, v = variant["spu"], variant["variant"]
    w, h = resolution.split("x")
    total_f = sum(it["durationInFrames"] for it in variant["items"])
    total_s = total_f / 30.0
    out_path = os.path.join(out_dir, spu, f"{spu}_v{v:02d}.mp4")
    if not force and os.path.exists(out_path) and os.path.getsize(out_path) > 100_000:
        return out_path, "cached"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    filters = []
    for i, it in enumerate(variant["items"]):
        seg = it["durationInFrames"] / 30.0
        # 每段多给 0.05s 帧级补偿，避免秒->帧取整丢帧；最终用精确帧数截断
        cmd += ["-ss", str(it["sourceStartFromInSeconds"]), "-t", f"{seg + 0.05:.4f}", "-i", it["file"]]
        filters.append(
            f"[{i}:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},fps=30,setsar=1,format=yuv420p[s{i}]")
    filters.append("".join(f"[s{i}]" for i in range(len(variant["items"])))
                   + f"concat=n={len(variant['items'])}:v=1:a=0[v]")

    maps = ["-map", "[v]"]
    if bgm:
        ai = len(variant["items"])          # 背景音乐作为最后一个输入
        cmd += ["-stream_loop", "-1", "-i", bgm]
        af = (f"[{ai}:a]atrim=start={bgm_start:.3f}:duration={total_s:.3f},"
              f"asetpts=PTS-STARTPTS,volume={bgm_volume}dB")
        if fade > 0:
            af += (f",afade=t=in:st=0:d={fade},"
                   f"afade=t=out:st={total_s - fade:.3f}:d={fade}")
        filters.append(af + "[a]")
        maps += ["-map", "[a]", "-c:a", "aac", "-b:a", "192k", "-ar", "44100", "-ac", "2"]
    else:
        maps += ["-an"]

    cmd += ["-filter_complex", ";".join(filters)] + maps + [
        "-c:v", "libx264", "-preset", "medium", "-crf", str(crf),
        "-movflags", "+faststart", "-frames:v", str(total_f), "-t", f"{total_s:.3f}", out_path]
    run_ffmpeg(cmd)
    return out_path, "rendered"


def resolve_bgm(args):
    """解析背景音乐路径：--no-bgm 关闭；--bgm 指定；否则用脚本目录 assets/bgm.mp3。"""
    if getattr(args, "no_bgm", False):
        return None
    if args.bgm:
        p = args.bgm
        return p if os.path.exists(p) else None
    default = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "bgm.mp3")
    return default if os.path.exists(default) else None


def render(plan_out, args):
    out_dir = os.path.join(args.out, "videos")
    jobs = [v for spu in plan_out.values() for v in spu]
    bgm = resolve_bgm(args)
    if bgm:
        log(f"背景音乐：{bgm}（起始 {args.bgm_start}s，音量 {args.bgm_volume}dB）")
    else:
        log("背景音乐：无（成片静音）")
    done, failed = 0, []
    with ThreadPoolExecutor(max_workers=max(1, args.render_workers)) as ex:
        futs = {ex.submit(render_one, v, out_dir, args.resolution, 20, bgm,
                          args.bgm_start, args.bgm_volume, args.bgm_fade, args.force): v
                for v in jobs}
        for i, fut in enumerate(as_completed(futs), 1):
            v = futs[fut]
            try:
                path, status = fut.result()
                done += 1
                log(f"[render {i}/{len(jobs)}] {v['spu']}_v{v['variant']:02d} {status}")
            except Exception as e:
                failed.append({"spu": v["spu"], "variant": v["variant"], "err": str(e)[:200]})
                log(f"[render {i}/{len(jobs)}] {v['spu']}_v{v['variant']:02d} FAIL {e}")
    # report
    report = os.path.join(args.out, "report.csv")
    with open(report, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["SPU", "成片", "状态", "说明"])
        for spu, vs in plan_out.items():
            for v in vs:
                name = f"{spu}_v{v['variant']:02d}.mp4"
                st = "成功" if os.path.exists(os.path.join(out_dir, spu, name)) else "失败"
                wr.writerow([spu, name, st, ""])
        for x in failed:
            wr.writerow([x["spu"], f"{x['spu']}_v{x['variant']:02d}.mp4", "失败", x["err"]])
    log(f"渲染完成：成功 {done}/{len(jobs)}，失败 {len(failed)}；报告 -> {report}")
    return failed


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="TK 视频混剪一键工具")
    ap.add_argument("--xlsx", required=True, help="需求表 xlsx 路径")
    ap.add_argument("--out", default="output", help="输出目录")
    ap.add_argument("--material-dir", default="", help="素材缓存目录（跨任务复用，默认 out/material）")
    ap.add_argument("--per-spu", type=int, default=20, help="每 SPU 成片数量")
    ap.add_argument("--duration", type=int, default=15, help="成片秒数")
    ap.add_argument("--segments", default="4-5", help="每条镜头数范围，如 4-5")
    ap.add_argument("--mode", choices=["normal", "cross"], default="normal",
                    help="normal=同SPU混剪（默认），cross=跨SPU混剪（全表素材合并）")
    ap.add_argument("--resolution", default="1080x1920", help="输出分辨率")
    ap.add_argument("--workers", type=int, default=4, help="下载并发")
    ap.add_argument("--render-workers", type=int, default=2, help="渲染并发")
    ap.add_argument("--step", choices=["all", "fetch", "plan", "render"], default="all")
    ap.add_argument("--only-spu", default="", help="只处理这些 SPU，逗号分隔")
    ap.add_argument("--bgm", default="", help="背景音乐文件（默认 assets/bgm.mp3，存在即启用）")
    ap.add_argument("--no-bgm", action="store_true", help="不配背景音乐（成片静音）")
    ap.add_argument("--bgm-start", type=float, default=0.0, help="从音乐的第几秒开始取")
    ap.add_argument("--bgm-volume", type=float, default=0.0, help="音乐音量（dB，负数=更轻）")
    ap.add_argument("--bgm-fade", type=float, default=0.25, help="首尾淡入淡出秒数，0=不做")
    ap.add_argument("--force", action="store_true", help="忽略已有成片，强制重新渲染")
    args = ap.parse_args()
    args.only_spu = set(args.only_spu.split(",")) if args.only_spu else None

    for tool in ("ffmpeg", "ffprobe"):
        if not subprocess.run(["where" if os.name == "nt" else "which", tool],
                              capture_output=True).returncode == 0:
            sys.exit(f"找不到 {tool}，请安装 FFmpeg 并加入 PATH")

    os.makedirs(args.out, exist_ok=True)
    mat_dir = args.material_dir or os.path.join(args.out, "material")

    rows = read_rows(args.xlsx)
    log(f"需求表：{len(rows)} 行素材，{len({r['spu'] for r in rows})} 个 SPU")

    if args.step in ("all", "fetch"):
        results = fetch(rows, mat_dir, args.workers)
    else:
        results = json.load(open(os.path.join(mat_dir, "manifest.json"), encoding="utf-8"))

    # 只保留当前需求表内的素材，防止缓存里其他任务的素材混进计划
    row_ids = {r["id"] for r in rows}
    dropped = len(results) - sum(1 for r in results if r["id"] in row_ids)
    results = [r for r in results if r["id"] in row_ids]
    if dropped:
        log(f"按需求表过滤：剔除缓存中不属于本表的 {dropped} 条素材记录")

    if args.step in ("all", "plan"):
        plan_out = plan(results, args)
    else:
        plan_out = json.load(open(os.path.join(args.out, "plan.json"), encoding="utf-8"))

    if args.step in ("all", "render"):
        render(plan_out, args)

    log("全部完成。成片目录: " + os.path.join(args.out, "videos"))


if __name__ == "__main__":
    main()
