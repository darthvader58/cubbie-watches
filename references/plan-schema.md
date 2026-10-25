# Course to video learning-map format

Cubbie first reads Canvas and the video evidence, then writes a private JSON plan for `watch.py validate` and `watch.py build`. Store the plan with the student's private course workspace, not in this Skill or public repository. The scripts never read Canvas or make semantic teaching decisions.

## Required structure

```json
{
  "schema_version": 1,
  "title": "How the course ideas connect",
  "mode": "exam",
  "course": {"id": "canvas course ID", "name": "Course name", "term": "Course term"},
  "exam_scope_confirmed": true,
  "budget_minutes": 45,
  "playback_speed": 1,
  "practice_minutes": 10,
  "sources": [
    {"id": "exam-review", "kind": "canvas", "title": "Midterm review guide", "url": "actual Canvas HTTPS URL", "locator": "Topics section", "checked_at": "ISO-8601 timestamp"}
  ],
  "requirements": [
    {
      "id": "equilibria",
      "title": "Equilibria and stability",
      "objective": "Classify a one-dimensional equilibrium from its local flow.",
      "explanation": "Explain how the professor's material connects to this lesson.",
      "basis": "explicit",
      "source_ids": ["exam-review"],
      "status": "matched",
      "clips": [{"video_id": "11-character-ID", "start": 91, "end": 178, "evidence_segments": [14, 15]}],
      "practice": "Classify a fresh ungraded example."
    }
  ],
  "edges": [],
  "video_summaries": []
}
```

Use `mode`: `exam`, `lecture` or `skill`. Source `kind` is `canvas` or `provided`; a Canvas source requires its actual HTTPS URL. Use `basis`: `explicit`, `inferred` or `student`. Every requirement's `source_ids` must point to real sources.

| Status | Clips | Additional evidence |
| --- | --- | --- |
| `matched` | One or more transcript-backed segments | Supports the objective at the requested depth |
| `partial` | One or more transcript-backed segments | Required `gap` names what remains uncovered |
| `unverified` | No verified clips | Required `gap`; `candidate_urls` remain unverified |
| `missing` | No clips | Required `gap`; no suitable inspected segment was found |

A clip may add `"frames": [193, 241]`: seconds of frames recorded with `watch.py frame`. Each must lie inside the clip. The map shows each frame's picture and on-screen description beside the clip link.

Segment IDs in `evidence_segments` come from `watch.py read`. The validator checks that each evidence segment starts inside its clip, clip times fit the known video duration and Canvas references exist. This does not prove semantic relevance; Cubbie must read and assess the evidence.

An edge is `{ "from": "requirement-id", "to": "requirement-id", "label": "why they connect" }`. Prefer labels such as “needed before,” “explains why,” “use when” and “contrasts with.”

Set `exam_scope_confirmed` only after reading instructor-published exam scope or a review guide. A syllabus alone is not exam scope. The validator warns when exam objectives are inferred or scope is unconfirmed.

`video_summaries` may be omitted if the workspace has checkpointed `notes.json`. For plan-provided summaries, include:

```json
{"video_id":"11-character-ID","summary":"Source-grounded notes","key_points":["Key idea"],"reviewed_segments":[14,15],"transcript_hash":"hash returned by watch.py read"}
```

List only the caption segments Cubbie actually reviewed. Transcript hashes detect stale summaries after caption changes. Never claim a whole video or playlist was reviewed from a title, description or transcript download alone.

## Commands

Examples use `<course-dir>` as a private course-and-term folder under the student's persistent home drive:

```bash
# Search finite ranked results and list every accessible item in a supplied playlist.
~/.local/share/venvs/cubbie-watches/bin/python scripts/watch.py catalog --query "objective and method" --playlist "<YouTube playlist URL>" --output "<course-dir>/catalog.json"

# Retrieve captions; saved videos are skipped when resuming.
~/.local/share/venvs/cubbie-watches/bin/python scripts/watch.py fetch --catalog "<course-dir>/catalog.json" --workspace "<course-dir>/workspace"

# Read the next bounded caption page. Continue with its next_offset until null.
~/.local/share/venvs/cubbie-watches/bin/python scripts/watch.py read --video "<ID>" --workspace "<course-dir>/workspace" --offset 0 --limit 40

# Inspect counts without printing captions again.
~/.local/share/venvs/cubbie-watches/bin/python scripts/watch.py status --catalog "<course-dir>/catalog.json" --workspace "<course-dir>/workspace"
```
