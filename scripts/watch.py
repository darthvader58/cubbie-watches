#!/usr/bin/env python3
"""YouTube catalog, resumable transcripts, source validation and report CLI."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from library import (InputError, now, number, parse_captions, playlist_url, read_json, record_path, string,
                     suggest_frames, timestamp, transcript_record, validate_plan, video_id, video_url, visual_path,
                     write_json)


def emit(data):
    print(json.dumps(data, ensure_ascii=False, allow_nan=False), flush=True)


def metadata(entry):
    vid = video_id(entry.get("id") or entry.get("url", ""))
    duration = entry.get("duration")
    if duration is not None:
        number(duration, "video duration", 0.001)
    return {"id": vid, "url": video_url(vid), "title": string(entry.get("title"), "video title"),
            "channel": entry.get("channel") or entry.get("uploader") or "Unknown creator",
            "duration": duration, "cataloged_at": now()}


class Log:
    def __init__(self):
        self.warnings = []

    def debug(self, message):
        pass

    def warning(self, message):
        self.warnings.append(str(message)[:700])

    def error(self, message):
        self.warning(message)


def extract_catalog(target, limit=None):
    from yt_dlp import YoutubeDL
    log = Log()
    options = {"extract_flat": True, "skip_download": True, "quiet": True, "no_warnings": True,
               "ignoreerrors": True, "socket_timeout": 15, "retries": 1, "extractor_retries": 1,
               "logger": log, "cachedir": False}
    if limit:
        options["playlistend"] = limit
    with YoutubeDL(options) as client:
        result = client.extract_info(target, download=False)
        if not result:
            raise InputError("YouTube listing unavailable. Use the browser catalog import fallback.")
        entries = list(result.get("entries", [result]))
        if not entries and log.warnings:
            raise InputError("YouTube returned no results; " + " | ".join(log.warnings[:2]))
        videos, unavailable = [], 0
        for entry in entries:
            if not entry:
                unavailable += 1
                continue
            try:
                videos.append(metadata(entry))
            except InputError:
                unavailable += 1
        reported = result.get("playlist_count")
        complete = limit is None and not log.warnings and unavailable == 0
        if isinstance(reported, int) and reported > len(entries):
            complete = False
        return videos, {"title": result.get("title", target), "entry_count": len(entries),
                        "reported_count": reported, "unavailable_entries": unavailable,
                        "enumeration_complete": complete, "warnings": log.warnings[:5]}


def catalog(args):
    path = Path(args.output).expanduser()
    result = read_json(path) if path.exists() else {"schema_version": 1, "videos": [], "sources": []}
    videos = {v["id"]: v for v in result["videos"]}
    targets = [(f"ytsearch{args.per_query}:{q}", "search", q) for q in args.query]
    targets += [(playlist_url(p), "playlist", playlist_url(p)) for p in args.playlist]
    targets += [(video_url(v), "video", video_url(v)) for v in args.video]
    if not targets:
        raise InputError("Supply --query, --playlist or --video")
    failures = 0
    for target, kind, label in targets:
        record = {"kind": kind, "input": label, "checked_at": now()}
        try:
            entries, info = extract_catalog(target, args.limit if kind == "playlist" else None)
            for item in entries:
                old = videos.get(item["id"], {})
                videos[item["id"]] = {**old, **{k: v for k, v in item.items() if v is not None}}
            record.update(info)
            record["video_ids"] = [v["id"] for v in entries]
            record["status"] = "ok" if entries else "empty"
            if kind == "search":
                record["enumeration_complete"] = False
                record["scope"] = f"Up to {args.per_query} ranked results; not exhaustive YouTube coverage"
        except Exception as exc:
            if isinstance(exc, (ImportError, ModuleNotFoundError)):
                raise
            failures += 1
            record.update(status="failed", enumeration_complete=False, error=str(exc)[:700], video_ids=[])
        result["sources"] = [s for s in result["sources"] if (s["kind"], s["input"]) != (kind, label)] + [record]
        result["videos"] = list(videos.values())
        result["updated_at"] = now()
        write_json(path, result)
        emit({"source": label, "status": record["status"], "videos": len(record["video_ids"]),
              "enumeration_complete": record["enumeration_complete"]})
    emit({"catalog": str(path), "unique_videos": len(videos), "failed_sources": failures})
    return 4 if failures else 0


def catalog_import(args):
    incoming = read_json(args.input)
    if not isinstance(incoming, dict) or not isinstance(incoming.get("videos"), list):
        raise InputError("Catalog import needs a videos array")
    items = [metadata(v) for v in incoming["videos"]]
    path = Path(args.output).expanduser()
    data = read_json(path) if path.exists() else {"schema_version": 1, "videos": [], "sources": []}
    by_id = {v["id"]: v for v in data["videos"]}
    for item in items:
        by_id[item["id"]] = {**by_id.get(item["id"], {}), **{k: v for k, v in item.items() if v is not None}}
    data["videos"] = list(by_id.values())
    data["sources"].append({"kind": "browser", "input": args.source, "checked_at": now(),
                            "enumeration_complete": False, "scope": "Browser-imported observed results",
                            "status": "ok", "video_ids": [v["id"] for v in items]})
    write_json(path, data)
    emit({"catalog": str(path), "imported": len(items), "unique_videos": len(by_id)})
    return 0


def request_transcript(vid, languages):
    from requests import Session
    from youtube_transcript_api import YouTubeTranscriptApi

    class TimedSession(Session):
        def request(self, *args, **kwargs):
            kwargs.setdefault("timeout", (10, 25))
            return super().request(*args, **kwargs)

    with TimedSession() as session:
        fetched = YouTubeTranscriptApi(http_client=session).fetch(vid, languages=languages)
        return fetched.to_raw_data(), fetched.language_code, fetched.is_generated


def failure_status(exc):
    name = type(exc).__name__
    if name in ("RequestBlocked", "IpBlocked", "YouTubeRequestFailed", "PoTokenRequired"):
        return "needs_browser"
    if name in ("TranscriptsDisabled", "NoTranscriptFound"):
        return "captions_unavailable"
    if name in ("VideoUnavailable", "VideoUnplayable", "AgeRestricted"):
        return "video_unavailable"
    return "retryable_error"


def fetch(args):
    data = read_json(args.catalog)
    if not isinstance(data.get("videos"), list):
        raise InputError("Catalog needs a videos array")
    requested = {video_id(v) for v in args.video}
    available = {v["id"] for v in data["videos"]}
    if requested - available:
        raise InputError("Requested video is not in catalog")
    processed = ready = failed = skipped = 0
    for meta in data["videos"]:
        if requested and meta["id"] not in requested:
            continue
        path = record_path(args.workspace, meta["id"])
        if path.exists():
            old = read_json(path)
            if old.get("status") == "ready" and not args.refresh or old.get("status") != "ready" and not args.retry_failed and not args.refresh:
                skipped += 1
                continue
        if args.limit and processed >= args.limit:
            break
        processed += 1
        try:
            raw, language, generated = request_transcript(meta["id"], args.language or ["en"])
            item = transcript_record(meta, raw, "youtube_captions", language, generated)
            ready += 1
        except Exception as exc:
            if isinstance(exc, (ImportError, ModuleNotFoundError)):
                raise
            failed += 1
            item = {**meta, "status": failure_status(exc), "error_type": type(exc).__name__, "attempted_at": now(),
                    "next_action": "Open the watch page in Cubbie's browser, choose Show transcript, save the panel text and run import --source browser_captions."}
            # A failed refresh must not destroy a previously usable transcript.
            if path.exists() and read_json(path).get("status") == "ready":
                old = read_json(path)
                old["last_refresh_failure"] = {k: item[k] for k in ("status", "error_type", "attempted_at")}
                write_json(path, old)
                emit({"video_id": meta["id"], "status": "cached_after_refresh_failure", "error_type": item["error_type"]})
                continue
        write_json(path, item)
        emit({"video_id": meta["id"], "status": item["status"]})
    emit({"processed": processed, "ready": ready, "failed": failed, "skipped_existing": skipped,
          "next": "Run status to see remaining videos. Re-run fetch to resume, or import browser captions for failures."})
    return 4 if failed else 0


def import_captions(args):
    vid = video_id(args.video)
    path = record_path(args.workspace, vid)
    meta = {"id": vid, "url": video_url(vid), "title": args.title or vid, "channel": args.channel or "Unknown creator", "duration": args.duration}
    if path.exists():
        old = read_json(path)
        meta = {k: old.get(k) for k in ("id", "url", "title", "channel", "duration")}
        meta.update({k: v for k, v in {"title": args.title, "channel": args.channel, "duration": args.duration}.items() if v is not None})
    record = transcript_record(meta, parse_captions(args.input), args.source, args.language)
    write_json(path, record)
    emit({"video_id": vid, "segments": len(record["segments"]), "warnings": record["warnings"], "path": str(path)})
    return 0


def inspect(args):
    record = read_json(record_path(args.workspace, args.video))
    if record.get("status") != "ready":
        emit(record)
        return 4
    segments = record["segments"]
    rows, used, next_offset = [], 0, None
    for segment in segments:
        if segment["id"] < args.offset:
            continue
        if args.term and args.term.casefold() not in segment["text"].casefold():
            continue
        size = len(json.dumps(segment, ensure_ascii=False))
        if rows and (len(rows) >= args.limit or used + size > 6000):
            next_offset = segment["id"]
            break
        rows.append(segment)
        used += size
    emit({"video_id": record["id"], "title": record["title"], "source": record["source"],
          "language": record.get("language"), "auto_generated": record.get("auto_generated"),
          "transcript_hash": record.get("transcript_hash"), "total_segments": len(segments),
          "segments": rows, "next_offset": next_offset})
    return 0


def note(args):
    path = record_path(args.workspace, args.video)
    transcript = read_json(path)
    if transcript.get("status") != "ready":
        raise InputError("No ready transcript; import or fetch captions first")
    ids = sorted(set(args.reviewed_segment))
    if not ids or any(i < 0 or i >= len(transcript["segments"]) for i in ids):
        raise InputError("Supply valid --reviewed-segment IDs from read; these mark only segments you actually inspected")
    notes_path = Path(args.workspace).expanduser() / "notes.json"
    notes = read_json(notes_path) if notes_path.exists() else {"schema_version": 1, "videos": {}}
    old = notes["videos"].get(transcript["id"], {})
    if old and old.get("transcript_hash") != transcript.get("transcript_hash") and not args.replace:
        raise InputError("Transcript changed since its notes were made; use --replace after reviewing the new caption text")
    if args.replace:
        old = {}
    summary = string(args.summary, "summary")
    point_text = [string(p, "key point") for p in args.key_point]
    row = {"summary": (old.get("summary", "") + " " + summary).strip(),
           "key_points": list(dict.fromkeys(old.get("key_points", []) + point_text)),
           "limitations": list(dict.fromkeys(old.get("limitations", []) + [string(x, "limitation") for x in args.limitation])),
           "reviewed_segments": sorted(set(old.get("reviewed_segments", []) + ids)),
           "transcript_hash": transcript["transcript_hash"], "source": transcript.get("source"),
           "language": transcript.get("language"), "updated_at": now()}
    notes["videos"][transcript["id"]] = row
    write_json(notes_path, notes)
    emit({"video_id": transcript["id"], "reviewed_segment_count": len(row["reviewed_segments"]),
          "segment_count": len(transcript["segments"]), "transcript_hash": row["transcript_hash"], "path": str(notes_path)})
    return 0


def frames(args):
    vid = video_id(args.video)
    path = record_path(args.workspace, vid)
    record = read_json(path) if path.exists() else {"id": vid}
    if record.get("status") != "ready" and args.end is None and record.get("duration") is None:
        raise InputError("Without a transcript, give --end so moments can be spaced through the clip")
    picks = suggest_frames(record, args.start, args.end, args.max)
    for pick in picks:
        pick["time"] = timestamp(pick["at"])
        pick["url"] = video_url(vid, pick["at"])
        # Some agent browsers reject addresses containing "?" or "#"; this one has neither, so seek in the player.
        pick["browser_url"] = f"https://youtu.be/{vid}"
    emit({"video_id": vid, "frames": picks,
          "next": "Open browser_url in Cubbie's browser, seek the player to each time, pause, look at the frame, then record it with the frame command."})
    return 0


def frame(args):
    vid = video_id(args.video)
    at = number(args.at, "frame time")
    path = record_path(args.workspace, vid)
    duration = args.duration or (read_json(path).get("duration") if path.exists() else None)
    if duration is not None and at >= duration:
        raise InputError("Frame time is beyond the video duration")
    row = {"at": at, "seen": string(args.seen, "what is on screen"), "legibility": args.legibility,
           "notation": [string(n, "notation") for n in args.notation], "observed_at": now()}
    if args.image:
        source = Path(args.image).expanduser()
        if not source.is_file():
            raise InputError("Frame image not found")
        target = Path(args.workspace).expanduser() / "frames" / f"{vid}-{int(at)}.jpg"
        target.parent.mkdir(parents=True, exist_ok=True)
        # A study map needs a readable picture, not the full screenshot; keep the PDF small enough to text.
        from PIL import Image
        with Image.open(source) as picture:
            picture = picture.convert("RGB")
            picture.thumbnail((960, 960))
            picture.save(target, "JPEG", quality=80, optimize=True)
        row["image"] = str(target)
    store = read_json(visual_path(args.workspace)) if visual_path(args.workspace).exists() else {"schema_version": 1, "videos": {}}
    rows = [r for r in store["videos"].get(vid, []) if r["at"] != at] + [row]
    store["videos"][vid] = sorted(rows, key=lambda r: r["at"])
    write_json(visual_path(args.workspace), store)
    emit({"video_id": vid, "at": at, "time": timestamp(at), "frames_recorded": len(rows), "image": row.get("image")})
    return 0


def status(args):
    catalog_data = read_json(args.catalog)
    counts, rows = {}, []
    source_rows = []
    notes_file = Path(args.workspace).expanduser() / "notes.json"
    notes = read_json(notes_file).get("videos", {}) if notes_file.exists() else {}
    for meta in catalog_data["videos"]:
        path = record_path(args.workspace, meta["id"])
        state = read_json(path).get("status", "invalid") if path.exists() else "pending"
        counts[state] = counts.get(state, 0) + 1
        note_row = notes.get(meta["id"])
        if note_row:
            stale = not path.exists() or note_row.get("transcript_hash") != read_json(path).get("transcript_hash")
            if stale:
                counts["stale_notes"] = counts.get("stale_notes", 0) + 1
            else:
                reviewed = len(set(note_row.get("reviewed_segments", [])))
                total_segments = len(read_json(path).get("segments", []))
                key = "fully_reviewed_transcripts" if reviewed == total_segments else "partly_reviewed_transcripts"
                counts[key] = counts.get(key, 0) + 1
        if args.details and len(rows) < 50:
            rows.append({"id": meta["id"], "title": meta["title"][:120], "status": state})
    for source in catalog_data.get("sources", []):
        source_rows.append({k: source[k] for k in ("kind", "input", "status", "scope", "enumeration_complete", "entry_count", "reported_count", "unavailable_entries", "error") if k in source})
    emit({"videos": len(catalog_data["videos"]), "counts": counts, "source_count": len(catalog_data.get("sources", [])),
          "sources": source_rows[:20], "sources_truncated": len(source_rows) > 20,
          "details": rows, "details_truncated": args.details and len(catalog_data["videos"]) > 50,
          "note": "Transcript availability is separate from content reviewed and course coverage."})
    return 0


def build(args):
    plan = read_json(args.plan)
    checked = validate_plan(plan, args.workspace)
    report = {k: v for k, v in checked.items() if k not in ("videos", "frames")}
    report["validated_at"] = now()
    report["validation_scope"] = "Structure, references, stored caption evidence and timing; semantic relevance still requires source review."
    if args.command == "validate":
        emit(report)
        return 0
    from render import render_reports
    paths = render_reports(plan, checked, Path(args.output).expanduser(), getattr(args, "font", None), getattr(args, "html_only", False))
    write_json(Path(args.output).expanduser() / "validation.json", report)
    emit({"files": paths, **report})
    return 0


def sample(args):
    data = read_json(Path(__file__).resolve().parent.parent / "assets" / "sample.json")
    output = Path(args.output).expanduser().resolve()
    workspace = output / "sample-workspace"
    for video in data["videos"]:
        record = transcript_record(video, video["segments"], "synthetic_sample", "en", False)
        record["sample"] = True
        write_json(record_path(workspace, video["id"]), record)
        for summary in data["plan"].get("video_summaries", []):
            if summary["video_id"] == video["id"]:
                summary["transcript_hash"] = record["transcript_hash"]
    write_json(workspace / "plan.json", data["plan"])
    args.plan, args.workspace, args.command = workspace / "plan.json", workspace, "build"
    return build(args)


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Expected a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Expected a positive integer")
    return parsed


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("catalog", help="Search videos or enumerate a whole accessible playlist; saves after each source")
    p.add_argument("--query", action="append", default=[])
    p.add_argument("--playlist", action="append", default=[])
    p.add_argument("--video", action="append", default=[])
    p.add_argument("--per-query", type=positive_int, default=8)
    p.add_argument("--limit", type=positive_int, help="Explicit playlist entry limit; makes listing incomplete")
    p.add_argument("--output", required=True)
    p.set_defaults(func=catalog)
    p = sub.add_parser("catalog-import", help="Import observed browser search results when direct search fails")
    p.add_argument("--input", required=True)
    p.add_argument("--source", required=True, help="Actual search query or source page")
    p.add_argument("--output", required=True)
    p.set_defaults(func=catalog_import)
    p = sub.add_parser("fetch", help="Fetch and checkpoint captions, skipping existing records")
    p.add_argument("--catalog", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--video", action="append", default=[])
    p.add_argument("--language", action="append")
    p.add_argument("--limit", type=positive_int)
    p.add_argument("--retry-failed", action="store_true")
    p.add_argument("--refresh", action="store_true")
    p.set_defaults(func=fetch)
    p = sub.add_parser("import", help="Import timed browser or instructor captions")
    p.add_argument("--video", required=True)
    p.add_argument("--input", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--title")
    p.add_argument("--channel")
    p.add_argument("--duration", type=float)
    p.add_argument("--language", default="unknown")
    p.add_argument("--source", choices=("browser_captions", "instructor_transcript", "student_transcript"), required=True)
    p.set_defaults(func=import_captions)
    p = sub.add_parser("read", help="Read bounded transcript pages with evidence IDs")
    p.add_argument("--video", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--offset", type=int, default=0)
    p.add_argument("--limit", type=positive_int, default=40)
    p.add_argument("--term", help="Optional literal text filter")
    p.set_defaults(func=inspect)
    p = sub.add_parser("note", help="Checkpoint Cubbie's inspected transcript evidence by segment ID")
    p.add_argument("--video", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--reviewed-segment", type=int, action="append", default=[])
    p.add_argument("--key-point", action="append", default=[])
    p.add_argument("--limitation", action="append", default=[])
    p.add_argument("--replace", action="store_true")
    p.set_defaults(func=note)
    p = sub.add_parser("frames", help="Suggest moments to look at in a clip, from spoken visual cues and even spacing")
    p.add_argument("--video", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--start", type=float, default=0.0)
    p.add_argument("--end", type=float)
    p.add_argument("--max", type=positive_int, default=6)
    p.set_defaults(func=frames)

    p = sub.add_parser("frame", help="Record what is visibly on screen at one moment of a video")
    p.add_argument("--video", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--at", type=float, required=True, help="Seconds into the video where the frame was observed")
    p.add_argument("--seen", required=True, help="What is on screen: slide or board text, diagrams, axes, worked steps")
    p.add_argument("--notation", action="append", default=[], help="An equation or symbol exactly as written on screen")
    p.add_argument("--legibility", choices=("clear", "partial", "unreadable"), required=True)
    p.add_argument("--image", help="Private screenshot of the frame, kept in the workspace")
    p.add_argument("--duration", type=float)
    p.set_defaults(func=frame)

    p = sub.add_parser("status")
    p.add_argument("--catalog", required=True)
    p.add_argument("--workspace", required=True)
    p.add_argument("--details", action="store_true")
    p.set_defaults(func=status)
    for command in ("validate", "build"):
        p = sub.add_parser(command)
        p.add_argument("--plan", required=True)
        p.add_argument("--workspace", required=True)
        if command == "build":
            p.add_argument("--output", required=True)
            p.add_argument("--font", help="Path to a Unicode TrueType font for mathematical notation or another script")
            p.add_argument("--html-only", action="store_true", help="Build the standalone HTML and SVG without PDF")
        p.set_defaults(func=build)
    p = sub.add_parser("sample", help="Offline synthetic sample; writes only below the explicit output folder")
    p.add_argument("--output", required=True)
    p.set_defaults(func=sample)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (ImportError, ModuleNotFoundError) as exc:
        emit({"error": "dependency_missing", "detail": str(exc), "next": "Run the pinned Setup commands in SKILL.md."})
        return 3
    except (InputError, OSError, KeyError, TypeError, ValueError) as exc:
        emit({"error": "invalid_input", "detail": str(exc)[:900]})
        return 2


if __name__ == "__main__":
    sys.exit(main())
