"""Local records, caption normalization, and source checks for Cubbie Watches."""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse


class InputError(ValueError):
    pass


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InputError(f"Cannot read JSON from {path}: {exc}") from exc


def write_json(path, data):
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".cw-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def number(value, label, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < minimum:
        raise InputError(f"{label} must be a finite number >= {minimum}")
    return float(value)


def string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise InputError(f"{label} must be nonempty text")
    return value.strip()


def https_url(value):
    value = string(value, "source URL")
    try:
        url = urlparse(value)
        if url.scheme != "https" or not url.hostname or url.username or url.password or url.port not in (None, 443):
            raise ValueError()
    except ValueError as exc:
        raise InputError("Source links must be HTTPS URLs without credentials or custom ports") from exc
    return value


def video_id(value):
    value = str(value).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value
    url = urlparse(https_url(value))
    if url.hostname == "youtu.be":
        result = url.path.strip("/")
    elif url.hostname in ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"):
        parts = url.path.strip("/").split("/")
        result = parts[1] if len(parts) == 2 and parts[0] in ("shorts", "embed", "live") else parse_qs(url.query).get("v", [""])[0]
    else:
        result = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{11}", result):
        raise InputError("Expected a YouTube video URL or an 11-character video ID")
    return result


def video_url(vid, start=None):
    url = "https://www.youtube.com/watch?v=" + video_id(vid)
    return url + (f"&t={int(start)}s" if start is not None else "")


def playlist_url(value):
    url = urlparse(https_url(value))
    key = parse_qs(url.query).get("list", [""])[0]
    if url.hostname not in ("www.youtube.com", "youtube.com", "m.youtube.com", "music.youtube.com") or not re.fullmatch(r"[A-Za-z0-9_-]+", key):
        raise InputError("Expected a YouTube playlist URL with a list parameter")
    return "https://www.youtube.com/playlist?list=" + key


def timestamp(seconds):
    if seconds is None:
        return "unknown"
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02}:{seconds % 60:02}" if seconds >= 3600 else f"{seconds // 60}:{seconds % 60:02}"


def parse_time(value):
    chunks = value.replace(",", ".").split(":")
    if len(chunks) not in (2, 3):
        raise InputError(f"Invalid caption timestamp: {value}")
    total = 0.0
    try:
        for item in chunks:
            total = total * 60 + float(item)
    except ValueError as exc:
        raise InputError(f"Invalid caption timestamp: {value}") from exc
    return number(total, "caption time")


def parse_captions(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        data = read_json(path)
        if isinstance(data, dict):
            data = data.get("segments", data.get("transcript"))
        if not isinstance(data, list):
            raise InputError("Caption JSON must be an array, or an object with a segments array")
        return data
    # SRT/VTT and browser-exported [start - end] lines. No timing is invented.
    text = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    timing = re.compile(r"^\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?)\s*-->\s*(\d{1,2}:\d{2}(?::\d{2})?(?:[.,]\d+)?).*$")
    aside = re.compile(r"^\[(\d{1,2}:\d{2}(?::\d{2})?)\s*-\s*(\d{1,2}:\d{2}(?::\d{2})?)\]\s*(.*)$")
    result, current = [], None
    for line in text.splitlines():
        match = timing.match(line)
        bracket = aside.match(line)
        if match or bracket:
            if current and current["text"].strip():
                result.append(current)
            found = match or bracket
            current = {"start": parse_time(found[1]), "end": parse_time(found[2]), "text": found[3] if bracket else ""}
        elif not line.strip():
            if current and current["text"].strip():
                result.append(current)
            current = None
        elif current is not None:
            current["text"] += " " + line.strip()
    if current and current["text"].strip():
        result.append(current)
    if not result:
        raise InputError("No timed captions found; use JSON, SRT, VTT or [start - end] lines")
    return result


def normalize_segments(raw, duration=None):
    if duration is not None:
        duration = number(duration, "video duration", minimum=0.001)
    if not isinstance(raw, list) or not raw:
        raise InputError("Transcript must contain caption segments")
    result, warnings, seen = [], [], set()
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            raise InputError(f"Caption {index} must be an object")
        start = number(row.get("start"), f"caption {index} start")
        content = html.unescape(re.sub(r"<[^>]+>", "", string(row.get("text"), f"caption {index} text"))).strip()
        if duration is not None and start >= duration:
            warnings.append(f"Caption {index}: start is outside video; excluded")
            continue
        end = row.get("end")
        if end is None and row.get("duration") is not None:
            end = start + number(row["duration"], f"caption {index} duration")
        if end is not None:
            end = number(end, f"caption {index} end")
            if end <= start or duration is not None and end > duration + 0.5:
                warnings.append(f"Caption {index}: invalid end retained as unknown")
                end = None
        key = (start, end, content)
        if key not in seen and content:
            result.append({"start": start, "end": end, "text": content})
            seen.add(key)
    result.sort(key=lambda s: s["start"])
    if not result:
        raise InputError("No usable captions remain after timing checks")
    for index, segment in enumerate(result):
        segment["id"] = index
    return result, warnings


def record_path(workspace, vid):
    return Path(workspace).expanduser() / "videos" / (video_id(vid) + ".json")


def transcript_record(metadata, raw, source, language="unknown", generated=None):
    segments, warnings = normalize_segments(raw, metadata.get("duration"))
    return {**metadata, "id": video_id(metadata["id"]), "status": "ready", "source": source,
            "language": language, "auto_generated": generated, "fetched_at": now(), "segments": segments,
            "warnings": warnings, "transcript_hash": hashlib.sha256(json.dumps(segments, sort_keys=True).encode()).hexdigest()}


def unique(rows, label):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise InputError(f"{label} must be an array of objects")
    found = {}
    for row in rows:
        key = string(row.get("id"), f"{label} id")
        if key in found:
            raise InputError(f"Duplicate {label} id: {key}")
        found[key] = row
    return found


def merged_duration(clips):
    intervals = {}
    unknown = False
    for clip in clips:
        if clip.get("end") is None:
            unknown = True
        else:
            intervals.setdefault(clip["video_id"], []).append((clip["start"], clip["end"]))
    seconds = 0
    for ranges in intervals.values():
        a, b = sorted(ranges)[0]
        for start, end in sorted(ranges)[1:]:
            if start <= b:
                b = max(end, b)
            else:
                seconds += b - a
                a, b = start, end
        seconds += b - a
    return seconds, unknown


def validate_plan(plan, workspace):
    if not isinstance(plan, dict) or plan.get("schema_version") != 1:
        raise InputError("Plan schema_version must be 1")
    string(plan.get("title"), "plan title")
    if plan.get("mode") not in ("exam", "lecture", "skill"):
        raise InputError("mode must be exam, lecture or skill")
    course = plan.get("course", {})
    for key in ("id", "name", "term"):
        string(course.get(key), "course " + key)
    sources = unique(plan.get("sources"), "source")
    requirements = unique(plan.get("requirements"), "requirement")
    if not sources or not requirements:
        raise InputError("At least one course source and requirement are required")
    for source in sources.values():
        for key in ("title", "locator", "checked_at"):
            string(source.get(key), "source " + key)
        if source.get("kind") not in ("canvas", "provided"):
            raise InputError("source kind must be canvas or provided")
        if source.get("url"):
            https_url(source["url"])
        elif source["kind"] == "canvas":
            raise InputError("Canvas sources require their actual HTTPS URL")
    videos, warnings, all_clips = {}, [], []

    def get_video(vid):
        vid = video_id(vid)
        if vid not in videos:
            item = read_json(record_path(workspace, vid))
            if item.get("id") != vid or item.get("status") != "ready":
                raise InputError(f"Video {vid} has no usable transcript")
            if item.get("sample") and not plan.get("sample"):
                raise InputError("Synthetic transcripts cannot support a real course map")
            if not item.get("segments"):
                raise InputError(f"Video {vid} has no caption segments")
            videos[vid] = item
        return videos[vid]

    for req in requirements.values():
        for key in ("title", "objective", "explanation"):
            string(req.get(key), "requirement " + key)
        if req.get("basis") not in ("explicit", "inferred", "student"):
            raise InputError("requirement basis must be explicit, inferred or student")
        ids = req.get("source_ids")
        if not isinstance(ids, list) or not ids or any(s not in sources for s in ids):
            raise InputError(f"Requirement {req['id']} needs valid course source_ids")
        state = req.get("status")
        if state not in ("matched", "partial", "unverified", "missing"):
            raise InputError("Invalid requirement status")
        clips = req.get("clips", [])
        if not isinstance(clips, list):
            raise InputError("clips must be an array")
        if state in ("matched", "partial") and not clips:
            raise InputError(f"{state} requirement {req['id']} needs verified clips")
        if state in ("missing", "unverified") and clips:
            raise InputError("Missing/unverified requirements cannot contain verified clips; use candidate_urls")
        if state != "matched":
            string(req.get("gap"), "coverage gap")
        for candidate in req.get("candidate_urls", []):
            https_url(candidate)
        for clip in clips:
            record = get_video(clip.get("video_id"))
            start = number(clip.get("start"), "clip start")
            end = clip.get("end")
            duration = record.get("duration")
            if end is not None:
                end = number(end, "clip end")
                if end <= start:
                    raise InputError("Clip end must be after start")
            if duration is not None and (start >= duration or end is not None and end > duration):
                raise InputError("Clip exceeds video duration")
            if duration is None:
                warnings.append(f"{record['id']}: video duration unknown; timing bounds not fully verified")
            evidence = clip.get("evidence_segments")
            if not isinstance(evidence, list) or not evidence:
                raise InputError("Each clip needs evidence_segments from the stored transcript")
            for sid in evidence:
                if type(sid) is not int or sid < 0 or sid >= len(record["segments"]):
                    raise InputError("Evidence segment ID does not exist")
                segment = record["segments"][sid]
                if segment["start"] < start or end is not None and segment["start"] >= end:
                    raise InputError("Evidence segment starts outside its clip")
            all_clips.append(clip)
        if plan["mode"] == "exam" and req["basis"] != "explicit":
            warnings.append(f"{req['id']}: exam objective is {req['basis']}, not confirmed instructor scope")
    edges = plan.get("edges", [])
    if not isinstance(edges, list):
        raise InputError("edges must be an array")
    for edge in edges:
        if edge.get("from") not in requirements or edge.get("to") not in requirements or edge["from"] == edge["to"]:
            raise InputError("Edges must connect two different requirement IDs")
        string(edge.get("label"), "connection label")
    summaries = plan.get("video_summaries")
    if summaries is None:
        notes_file = Path(workspace).expanduser() / "notes.json"
        if notes_file.exists():
            notes = read_json(notes_file)
            summaries = [{**row, "video_id": vid} for vid, row in notes.get("videos", {}).items()]
        else:
            summaries = []
    if not isinstance(summaries, list):
        raise InputError("video_summaries must be an array")
    summary_ids = set()
    for summary in summaries:
        vid = summary.get("video_id")
        if vid in summary_ids:
            raise InputError("Duplicate video summary")
        summary_ids.add(vid)
        record = get_video(vid)
        if summary.get("transcript_hash") != record.get("transcript_hash"):
            raise InputError(f"Summary for {vid} is stale or has no matching transcript hash; review the new transcript")
        string(summary.get("summary"), "video summary")
        reviewed = summary.get("reviewed_segments")
        if not isinstance(reviewed, list) or not reviewed or any(type(i) is not int or i < 0 or i >= len(record["segments"]) for i in reviewed):
            raise InputError("Video summaries require valid reviewed_segments")
        for point in summary.get("key_points", []):
            string(point, "summary key point")
    for vid in videos:
        if vid not in summary_ids:
            warnings.append(f"{vid}: no video summary supplied")
    plan["video_summaries"] = summaries
    speed = number(plan.get("playback_speed", 1), "playback speed", 0.25)
    if speed > 4:
        raise InputError("Playback speed must be at most 4")
    practice = number(plan.get("practice_minutes", 0), "practice minutes")
    seconds, unknown = merged_duration(all_clips)
    total = seconds / speed / 60 + practice
    budget = plan.get("budget_minutes")
    if budget is not None:
        number(budget, "time budget", 0.01)
        if total > budget:
            warnings.append(f"Route exceeds {budget:g} minute budget; known total is {total:.1f} minutes")
    if unknown:
        warnings.append("Some clip end times are unknown; total time is a lower bound")
    if not plan.get("exam_scope_confirmed") and plan["mode"] == "exam":
        warnings.append("Exam scope is not confirmed; this is a provisional course study map")
    return {"videos": videos, "warnings": list(dict.fromkeys(warnings)), "known_minutes": total,
            "unknown_duration": unknown, "watch_minutes": seconds / speed / 60, "practice_minutes": practice,
            "statuses": {s: sum(r["status"] == s for r in requirements.values()) for s in ("matched", "partial", "unverified", "missing")}}
