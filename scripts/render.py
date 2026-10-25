"""Offline HTML, SVG and PDF learning-map rendering. No remote assets or scripts."""
from __future__ import annotations

import base64
import hashlib
import html
import math
import textwrap
from pathlib import Path

from library import InputError, now, timestamp, video_url

COLORS = {"matched": ("#e5f3ed", "#226748"), "partial": ("#fff1dc", "#956018"),
          "unverified": ("#eeebf8", "#66518b"), "missing": ("#f8e8e6", "#9d4940")}
LABELS = {"matched": "Matched", "partial": "Partial match", "unverified": "Unverified", "missing": "No match found"}


def esc(value):
    return html.escape(str(value), quote=True)


def anchor(value):
    return "r" + hashlib.sha256(str(value).encode()).hexdigest()[:16]


def layout(requirements, edges):
    ids = [r["id"] for r in requirements]
    by_id = {r["id"]: r for r in requirements}
    remaining, placed, levels = set(ids), set(), []
    while remaining:
        level = [key for key in ids if key in remaining and all(e["from"] in placed for e in edges if e["to"] == key and e["from"] in by_id)]
        if not level:  # Cyclic conceptual links remain visible; layout does not assert a prerequisite order.
            level = [next(key for key in ids if key in remaining)]
        for start in range(0, len(level), 3):
            levels.append(level[start:start + 3])
        placed.update(level)
        remaining.difference_update(level)
    boxes = {}
    width, box_width, box_height = 960, 270, 100
    for row, level in enumerate(levels):
        gap = 32
        left = (width - len(level) * box_width - (len(level) - 1) * gap) / 2
        for col, key in enumerate(level):
            boxes[key] = (left + col * (box_width + gap), 30 + row * 190, box_width, box_height)
    routes = []
    for index, edge in enumerate(edges):
        if edge["from"] not in boxes or edge["to"] not in boxes:
            continue
        x, y, w, h = boxes[edge["from"]]
        tx, ty, tw, th = boxes[edge["to"]]
        sx, sy, ex, ey = x + w / 2, y + h, tx + tw / 2, ty
        if 0 < ey - sy < 191:
            middle = (sy + ey) / 2
            points = [(sx, sy), (sx, middle), (ex, middle), (ex, ey)]
            label = ((sx + ex) / 2, middle - 12)
        else:
            rail = 12 + index % 3 * 10
            points = [(sx, sy), (sx, sy + 20), (rail, sy + 20), (rail, ey - 25), (ex, ey - 25), (ex, ey)]
            label = ((rail + ex) / 2, ey - 32)
        routes.append((edge, points, label))
    return width, max(150, len(levels) * 190 - 30), boxes, routes


def wrapped(value, width=29, lines=3):
    result = textwrap.wrap(str(value), width=width, break_long_words=True) or [""]
    return result[:lines - 1] + [textwrap.shorten(" ".join(result[lines - 1:]), width=width, placeholder="...")] if len(result) > lines else result


def svg_map(requirements, edges):
    width, height, boxes, routes = layout(requirements, edges)
    chunks = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Course concept relationships">',
              '<defs><marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z" fill="#8b8794"/></marker></defs>']
    for edge, points, label in routes:
        chunks.append(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" fill="none" stroke="#8b8794" stroke-width="2" marker-end="url(#arrow)"/>')
        lines = wrapped(edge["label"], 30, 2)
        lx, ly = label
        chunks.append(f'<rect x="{lx-112}" y="{ly-16}" width="224" height="{len(lines)*16+5}" rx="5" fill="#faf9f6"/>')
        for line_index, line in enumerate(lines):
            chunks.append(f'<text x="{lx}" y="{ly + line_index*16}" text-anchor="middle" font-family="Arial,sans-serif" font-size="13" fill="#66616d">{esc(line)}</text>')
    for req in requirements:
        x, y, w, h = boxes[req["id"]]
        bg, fg = COLORS[req["status"]]
        chunks.append(f'<a href="#{anchor(req["id"])}"><title>{esc(req["title"])}</title><rect x="{x}" y="{y}" width="{w}" height="{h}" rx="13" fill="{bg}" stroke="{fg}" stroke-opacity=".25"/>')
        for index, line in enumerate(wrapped(req["title"], 28, 3)):
            chunks.append(f'<text x="{x+16}" y="{y+25+index*18}" font-family="Arial,sans-serif" font-size="16" fill="#28242d">{esc(line)}</text>')
        chunks.append(f'<text x="{x+16}" y="{y+h-12}" font-family="Arial,sans-serif" font-size="12" fill="{fg}">{LABELS[req["status"]]}</text></a>')
    return "".join(chunks) + "</svg>"


def clip_label(clip, video):
    return f"{video.get('title', clip['video_id'])} | {timestamp(clip['start'])} - {timestamp(clip.get('end'))}"


def names_for(plan):
    return {r["id"]: r["title"] for r in plan["requirements"]}


def frames_for(clip, checked):
    observed = checked.get("frames", {}).get(clip["video_id"], {})
    return [observed[at] for at in clip.get("frames", []) if at in observed]


def frame_text(row):
    notation = "; ".join(row.get("notation", []))
    return f"On screen at {timestamp(row['at'])}: {row['seen']}" + (f" [{notation}]" if notation else "") + \
        ("" if row.get("legibility") == "clear" else f" ({row.get('legibility')} legibility)")


def frame_image(row):
    image = row.get("image")
    return Path(image) if image and Path(image).is_file() else None


def html_report(plan, checked, diagram):
    videos = checked["videos"]
    sources = {s["id"]: s for s in plan["sources"]}
    sample = bool(plan.get("sample"))
    badge = "SYNTHETIC EXAMPLE" if sample else "COURSE-ALIGNED LEARNING"
    warning = "".join(f'<li>{esc(w)}</li>' for w in checked["warnings"])
    if sample:
        warning = "<li>This demonstration uses fictional course requirements and authored sample captions.</li>" + warning
    count_cards = "".join(f'<div class="stat"><strong>{count}</strong><span>{LABELS[state]}</span></div>' for state, count in checked["statuses"].items())
    cards = []
    requirement_names = {item["id"]: item["title"] for item in plan["requirements"]}
    for req in plan["requirements"]:
        links = []
        for sid in req["source_ids"]:
            s = sources[sid]
            label = esc(s["title"] + " / " + s["locator"])
            links.append(f'<a href="{esc(s["url"])}" target="_blank" rel="noopener noreferrer">{label}</a>' if s.get("url") and not sample else label)
        clip_links = []
        for clip in req.get("clips", []):
            record = videos[clip["video_id"]]
            label = esc(clip_label(clip, record))
            seen = []
            for row in frames_for(clip, checked):
                image = frame_image(row)
                picture = ""
                if image:
                    kind = "jpeg" if image.suffix.lower() in (".jpg", ".jpeg") else "png"
                    picture = f'<img alt="{esc(frame_text(row))}" src="data:image/{kind};base64,{base64.b64encode(image.read_bytes()).decode()}">'
                seen.append(f'<figure class="frame">{picture}<figcaption><a href="{video_url(clip["video_id"], row["at"])}" target="_blank" rel="noopener noreferrer">{esc(frame_text(row))}</a></figcaption></figure>')
            body = f'<a href="{video_url(clip["video_id"], clip["start"])}" target="_blank" rel="noopener noreferrer">{label}</a>' if not sample else label
            clip_links.append(f'<li>{body}<small>{esc(record.get("channel", ""))}</small>{"".join(seen)}</li>')
        candidates = "".join(f'<li><a href="{esc(url)}" target="_blank" rel="noopener noreferrer">Unverified candidate</a></li>' for url in req.get("candidate_urls", []))
        gap = f'<div class="gap"><b>Still needed</b><p>{esc(req["gap"])}</p></div>' if req.get("gap") else ""
        practice = f'<div class="practice"><b>Try it</b><p>{esc(req["practice"])}</p></div>' if req.get("practice") else ""
        related = []
        for edge in plan.get("edges", []):
            if edge["from"] == req["id"]:
                related.append(f'<li>{esc(requirement_names[edge["to"]])} · {esc(edge["label"])}</li>')
            if edge["to"] == req["id"]:
                related.append(f'<li>From {esc(requirement_names[edge["from"]])} · {esc(edge["label"])}</li>')
        relation_box = f'<div class="sources"><b>Connections</b><ul>{"".join(related)}</ul></div>' if related else ""
        cards.append(f'<article class="card" data-status="{req["status"]}" id="{anchor(req["id"])}"><span class="badge {req["status"]}">{LABELS[req["status"]]}</span><h3>{esc(req["title"])}</h3><p class="objective">{esc(req["objective"])}</p><p>{esc(req["explanation"])}</p><div class="sources"><b>Course evidence · {esc(req["basis"])}</b><p>{"<br>".join(links)}</p></div><ul class="clips">{"".join(clip_links)}{candidates}</ul>{relation_box}{gap}{practice}</article>')
    summaries = []
    for item in plan.get("video_summaries", []):
        record = videos[item["video_id"]]
        reviewed = len(set(item["reviewed_segments"]))
        total = len(record["segments"])
        points = "".join(f'<li>{esc(p)}</li>' for p in item.get("key_points", []))
        summaries.append(f'<details class="summary" open><summary>{esc(record["title"])}</summary><small>{esc(record.get("channel", ""))} · {reviewed}/{total} caption segments marked reviewed · {esc(record["source"])}</small><p>{esc(item["summary"])}</p><ul>{points}</ul></details>')
    time_note = "At least " if checked["unknown_duration"] else "Estimated "
    course = plan["course"]
    return f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(plan['title'])} · Cubbie Watches</title>
<style>
:root{{--ink:#28242d;--muted:#6d6874;--line:#e5e1e8;--purple:#6b4bba}}*{{box-sizing:border-box}}body{{margin:0;background:#faf9f6;color:var(--ink);font:16px/1.65 system-ui,-apple-system,sans-serif}}main{{max-width:1120px;margin:auto;padding:32px 32px 64px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line);padding-bottom:20px}}.brand{{font-weight:750;letter-spacing:-.5px}}.brand span{{color:var(--purple)}}button{{font:inherit;border:1px solid var(--line);border-radius:100px;background:white;padding:7px 16px;cursor:pointer}}button[aria-pressed=true]{{background:var(--ink);color:white}}.eyebrow{{font-size:11px;letter-spacing:2px;color:var(--purple);font-weight:750;margin-top:42px}}h1{{font-size:clamp(30px,5vw,52px);line-height:1.12;letter-spacing:-1.5px;margin:14px 0 18px;max-width:850px}}h2{{font-size:24px;letter-spacing:-.5px;margin:36px 0 10px}}h3{{font-size:22px;line-height:1.25;margin:15px 0}}.meta,small{{color:var(--muted)}}.stats{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}.stat{{background:white;border:1px solid var(--line);border-radius:14px;padding:18px}}.stat strong{{display:block;font-size:30px;line-height:1.2}}.stat span{{font-size:13px;color:var(--muted)}}.notice{{padding:16px 22px;background:#fff1dc;border-radius:12px;margin:20px 0}}.notice ul{{margin:0;padding-left:18px}}.map{{overflow:auto;border:1px solid var(--line);border-radius:18px;padding:12px}}.map svg{{width:100%;min-width:640px;display:block}}.filters{{display:flex;gap:8px;flex-wrap:wrap;margin:20px 0}}.grid{{display:grid;grid-template-columns:1fr 1fr;gap:18px}}.card{{background:white;border:1px solid var(--line);border-radius:16px;padding:25px;scroll-margin-top:24px}}.card[hidden]{{display:none}}.badge{{font-size:11px;letter-spacing:.4px;text-transform:uppercase;font-weight:750;padding:5px 9px;border-radius:6px}}.matched{{background:#e5f3ed;color:#226748}}.partial{{background:#fff1dc;color:#956018}}.unverified{{background:#eeebf8;color:#66518b}}.missing{{background:#f8e8e6;color:#9d4940}}.objective{{font-weight:650}}.sources{{border-top:1px solid var(--line);margin-top:20px;padding-top:16px;font-size:13px}}.sources b,.gap b,.practice b{{font-size:11px;letter-spacing:.7px;text-transform:uppercase}}a{{color:#6845b2;text-decoration-thickness:1px;text-underline-offset:3px;overflow-wrap:anywhere}}.clips{{padding-left:18px;font-size:14px}}.clips small{{display:block}}.frame{{margin:10px 0 4px;font-size:13px}}.frame img{{width:100%;max-width:420px;border-radius:8px;border:1px solid var(--line);display:block;margin-bottom:4px}}.gap,.practice{{padding:14px 16px;border-radius:10px;margin-top:16px;background:#f6f3fa}}.gap{{background:#fff5e6}}.gap p,.practice p{{margin:5px 0 0}}.summary{{background:white;border:1px solid var(--line);border-radius:12px;padding:20px 24px;margin:12px 0}}summary{{font-weight:700;cursor:pointer}}footer{{margin-top:40px;border-top:1px solid var(--line);padding-top:18px;font-size:12px;color:var(--muted)}}@media(max-width:700px){{main{{padding:20px 16px}}.grid{{grid-template-columns:1fr}}.stats{{gap:7px}}.stat{{padding:12px 8px}}.stat span{{font-size:11px}}.map{{padding:0}}}}@media print{{button,.filters{{display:none}}body{{background:white}}main{{max-width:none;padding:0}}.card,.summary{{break-inside:avoid}}.grid{{display:block}}.card{{margin:12px 0}}.map svg{{min-width:0}}}}
</style></head><body><main><header><div class="brand">cubbie <span>watches.</span></div><button onclick="window.print()">Print / Save PDF</button></header><div class="eyebrow">{badge}</div><h1>{esc(plan['title'])}</h1><p class="meta">{esc(course['name'])} · {esc(course['term'])} · {esc(plan['mode'].title())} mode</p><p>{time_note}{checked['known_minutes']:.1f} minutes: {checked['watch_minutes']:.1f} watching at {plan.get('playback_speed',1):g}x + {checked['practice_minutes']:g} practice. Coverage describes resources, not mastery.</p><div class="stats">{count_cards}</div>{f'<aside class="notice"><ul>{warning}</ul></aside>' if warning else ''}<h2>Your learning map</h2><p class="meta">Follow the labeled connections. Select a concept to see its explanation and sources.</p><section class="map">{diagram}</section><h2>What to learn and where to watch</h2><div class="filters" aria-label="Filter course requirements"><button data-filter="all" aria-pressed="true">All</button>{''.join(f'<button data-filter="{s}" aria-pressed="false">{LABELS[s]}</button>' for s in LABELS)}</div><section class="grid">{''.join(cards)}</section><h2>Video notes</h2>{''.join(summaries) or '<p>No video summaries supplied.</p>'}<footer>Generated {esc(now())}. Course evidence and captions determine the scope. Semantic matches are teaching judgments and should be checked against the cited sources.</footer></main><script>document.querySelectorAll('[data-filter]').forEach(b=>b.addEventListener('click',()=>{{document.querySelectorAll('[data-filter]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));document.querySelectorAll('.card').forEach(c=>c.hidden=b.dataset.filter!=='all'&&c.dataset.status!==b.dataset.filter)}}));document.querySelectorAll('.map a').forEach(a=>a.addEventListener('click',()=>{{document.querySelector('[data-filter="all"]').click()}}));</script></body></html>'''


def render_pdf(plan, checked, path, font_path=None):
    import reportlab
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak, KeepTogether, Flowable, Image
    font_dir = Path(reportlab.__file__).parent / "fonts"
    if font_path:
        pdfmetrics.registerFont(TTFont("CW", str(font_path)))
        bold_font = str(font_path)
    else:
        pdfmetrics.registerFont(TTFont("CW", str(font_dir / "Vera.ttf")))
        bold_font = str(font_dir / "VeraBd.ttf")
    pdfmetrics.registerFont(TTFont("CWB", bold_font))
    pdfmetrics.registerFontFamily("CW", normal="CW", bold="CWB", italic="CW", boldItalic="CWB")
    face = pdfmetrics.getFont("CW").face

    def all_strings(value):
        if isinstance(value, str):
            yield value
        elif isinstance(value, dict):
            for child in value.values():
                yield from all_strings(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                yield from all_strings(child)

    missing = sorted({char for value in all_strings([plan, checked.get("frames", {})]) for char in value if ord(char) > 127 and ord(char) not in face.charToGlyph})
    if missing:
        shown = " ".join(f"U+{ord(char):04X}" for char in missing[:8])
        raise InputError(f"Selected PDF font cannot display {shown}. Use --font with an installed Unicode TrueType font, or render the HTML through Cubbie's browser.")
    styles = {
        "body": ParagraphStyle("body", fontName="CW", fontSize=9.5, leading=14, textColor=colors.HexColor("#302b38"), spaceAfter=8),
        "small": ParagraphStyle("small", fontName="CW", fontSize=8, leading=11, textColor=colors.HexColor("#6d6874"), spaceAfter=7),
        "title": ParagraphStyle("title", fontName="CWB", fontSize=27, leading=32, textColor=colors.HexColor("#28242d"), spaceAfter=16),
        "h2": ParagraphStyle("h2", fontName="CWB", fontSize=17, leading=22, spaceBefore=16, spaceAfter=10),
        "h3": ParagraphStyle("h3", fontName="CWB", fontSize=12, leading=16, spaceBefore=12, spaceAfter=7),
    }

    def p(value, style="body"):
        # Never interpret source content as ReportLab markup.
        return Paragraph(esc(value).replace("\n", "<br/>"), styles[style])

    def link(label, url):
        return Paragraph(f'<a href="{esc(url)}" color="#6845b2">{esc(label)}</a>', styles["small"])

    class MapDrawing(Flowable):
        def __init__(self, requirements, edges):
            super().__init__()
            self.requirements = requirements
            self.layout = layout(requirements, edges)
            self.scale = min(499 / self.layout[0], 610 / self.layout[1])
            self.width, self.height = self.layout[0] * self.scale, self.layout[1] * self.scale

        def draw(self):
            c = self.canv
            width, height, boxes, routes = self.layout
            c.saveState()
            c.scale(self.scale, self.scale)
            for edge, points, label in routes:
                c.setStrokeColor(colors.HexColor("#8b8794"))
                c.setLineWidth(2)
                for (x, y), (tx, ty) in zip(points, points[1:]):
                    c.line(x, height-y, tx, height-ty)
                ex, ey = points[-1]
                c.setFillColor(colors.HexColor("#8b8794"))
                arrow = c.beginPath()
                arrow.moveTo(ex, height-ey)
                arrow.lineTo(ex-5, height-ey+9)
                arrow.lineTo(ex+5, height-ey+9)
                arrow.close()
                c.drawPath(arrow, fill=1, stroke=0)
                lx, ly = label
                lines = wrapped(edge["label"], 30, 2)
                c.setFillColor(colors.white)
                c.rect(lx-116, height-ly-len(lines)*16+10, 232, len(lines)*16+8, stroke=0, fill=1)
                c.setFillColor(colors.HexColor("#66616d"))
                c.setFont("CW", 13)
                for i, line in enumerate(lines):
                    c.drawCentredString(lx, height-ly-i*16, line)
            for req in self.requirements:
                x, y, w, h = boxes[req["id"]]
                bg, fg = COLORS[req["status"]]
                c.setFillColor(colors.HexColor(bg))
                c.setStrokeColor(colors.HexColor(fg))
                c.roundRect(x, height-y-h, w, h, 12, fill=1, stroke=0)
                c.setFillColor(colors.HexColor("#28242d"))
                c.setFont("CW", 16)
                for i, line in enumerate(wrapped(req["title"], 28, 3)):
                    c.drawString(x+16, height-y-25-i*18, line)
                c.setFillColor(colors.HexColor(fg))
                c.setFont("CW", 12)
                c.drawString(x+16, height-y-h+12, LABELS[req["status"]])
            c.restoreState()

    def footer(canvas, doc):
        canvas.setFont("CW", 8)
        canvas.setFillColor(colors.HexColor("#6d6874"))
        canvas.drawString(48, 28, "Cubbie Watches / course-aligned learning")
        canvas.drawRightString(A4[0]-48, 28, str(doc.page))

    story = [p("CUBBIE WATCHES" + (" / SYNTHETIC EXAMPLE" if plan.get("sample") else ""), "small"), p(plan["title"], "title"),
             p(plan["course"]["name"] + " | " + plan["course"]["term"] + " | " + plan["mode"].title() + " mode", "small")]
    if plan.get("sample"):
        story.append(p("Demonstration only: fictional course requirements and authored sample captions."))
    story.append(p(("At least " if checked["unknown_duration"] else "Estimated ") + f"{checked['known_minutes']:.1f} minutes: {checked['watch_minutes']:.1f} watching + {checked['practice_minutes']:g} practice. Playback: {plan.get('playback_speed',1):g}x."))
    story.append(p(" | ".join(f"{count} {LABELS[state].lower()}" for state, count in checked["statuses"].items())))
    story.append(p("Coverage describes resources, not student mastery.", "small"))
    for warning in checked["warnings"]:
        story.append(p("Note: " + warning, "small"))
    requirements = plan["requirements"]
    # Small maps remain legible; larger courses get multiple map panels and a full relationship index.
    for offset in range(0, len(requirements), 6):
        if offset:
            story.append(PageBreak())
        part = requirements[offset:offset+6]
        ids = {r["id"] for r in part}
        edges = [e for e in plan.get("edges", []) if e["from"] in ids and e["to"] in ids]
        story.append(p("Your learning map" + (f" / {offset//6+1}" if len(requirements)>6 else ""), "h2"))
        story.append(p("Labeled connections explain how concepts relate. Detailed sources and practice follow.", "small"))
        story.append(MapDrawing(part, edges))
    story.append(PageBreak())
    story.append(p("What to learn and where to watch", "h2"))
    sources = {s["id"]: s for s in plan["sources"]}
    names = names_for(plan)
    for req in requirements:
        section = [p(req["title"], "h3"), p(LABELS[req["status"]] + " | " + req["basis"] + " course objective", "small"), p(req["objective"]), p(req["explanation"])]
        for sid in req["source_ids"]:
            source = sources[sid]
            label = "Course: " + source["title"] + " / " + source["locator"]
            section.append(link(label, source["url"]) if source.get("url") and not plan.get("sample") else p(label, "small"))
        for clip in req.get("clips", []):
            video = checked["videos"][clip["video_id"]]
            label = "Watch: " + clip_label(clip, video)
            section.append(p(label, "small") if plan.get("sample") else link(label, video_url(clip["video_id"], clip["start"])))
            for row in frames_for(clip, checked):
                image = frame_image(row)
                if image:
                    picture = Image(str(image))
                    picture.drawHeight = 220 * picture.imageHeight / picture.imageWidth
                    picture.drawWidth = 220
                    picture.hAlign = "LEFT"
                    section.append(picture)
                section.append(link(frame_text(row), video_url(clip["video_id"], row["at"])))
        for url in req.get("candidate_urls", []):
            section.append(link("Unverified candidate: " + url, url))
        for edge in plan.get("edges", []):
            if edge["from"] == req["id"]:
                section.append(p("Connection: " + names[edge["from"]] + " -> " + names[edge["to"]] + ": " + edge["label"], "small"))
        if req.get("gap"):
            section.append(p("Still needed: " + req["gap"]))
        if req.get("practice"):
            section.append(p("Try it: " + req["practice"]))
        story.append(KeepTogether(section))
        story.append(Spacer(1, 5))
    if plan.get("video_summaries"):
        story.append(p("Video notes", "h2"))
        for summary in plan["video_summaries"]:
            video = checked["videos"][summary["video_id"]]
            story.append(KeepTogether([p(video["title"], "h3"), p(video.get("channel", "Unknown creator") + f" | {len(set(summary['reviewed_segments']))}/{len(video['segments'])} caption segments marked reviewed | " + video["source"], "small")]))
            story.append(p(summary["summary"]))
            for point in summary.get("key_points", []):
                story.append(p("- " + point))
    doc = SimpleDocTemplate(str(path), pagesize=A4, rightMargin=48, leftMargin=48, topMargin=42, bottomMargin=48,
                            title=plan["title"], author="Cubbie Watches")
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


def render_reports(plan, checked, output, font_path=None, html_only=False):
    output.mkdir(parents=True, exist_ok=True)
    diagram = svg_map(plan["requirements"], plan.get("edges", []))
    (output / "learning-map.svg").write_text(diagram, encoding="utf-8")
    (output / "learning-map.html").write_text(html_report(plan, checked, diagram), encoding="utf-8")
    files = {"html": str(output / "learning-map.html"), "svg": str(output / "learning-map.svg")}
    if not html_only:
        render_pdf(plan, checked, output / "learning-map.pdf", font_path)
        files["pdf"] = str(output / "learning-map.pdf")
    return files
