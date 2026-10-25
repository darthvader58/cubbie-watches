# Cubbie Watches

**Your Canvas course. The YouTube lessons that fit it. A map that shows how the ideas connect.**

Cubbie Watches helps students find useful YouTube explanations for the material their university course actually requires. It connects course sources to inspected video segments, summarizes the teaching, and turns the result into a visual learning map and a focused plan for what to watch and practice.

## What it helps with

Choose the study goal that fits the moment:

| Mode | Starting point | Result |
| --- | --- | --- |
| **Exam Rescue** | An instructor's exam scope or review guide in Canvas | A prioritized route through relevant clips, practice, and visible coverage gaps |
| **Lecture Clarity** | A confusing lecture, slide deck, or course page | A concise explanation map that connects the course's presentation to clearer video explanations |
| **Skill Builder** | A lab, project brief, rubric, or course outcome | A shortlist of useful courses or playlists with practical milestones tied to course criteria |

The student can switch goals while keeping the same course evidence and video research.

## How it works

1. **Read the course context.** Cubbie uses its connected Canvas account to find the relevant syllabus, lecture, exam guidance, assignment, rubric, or project instructions.
2. **Search for relevant videos.** It searches YouTube using the course concepts, expected depth, methods, notation, and software requirements.
3. **Inspect the content.** The skill retrieves or reads available captions, reviews the relevant segments, and records timestamped evidence. It can enumerate all accessible entries in a selected playlist.
4. **Map course requirements to videos.** Each requirement is marked as matched, partial, unverified, or not found, with uncovered material kept visible.
5. **Build a learning route.** Cubbie creates a source-linked map, a realistic viewing plan, and small practice prompts.
6. **Check understanding.** A short follow-up question helps identify whether the explanation worked or what needs another pass.

The generated map can be delivered as a PDF, with standalone HTML and SVG companions when available.

## Try it in Cubbie

This repository contains the skill at its root. In your Cubbie conversation, share this public repository link and follow Cubbie's prompt to install it:

<https://github.com/darthvader58/cubbie-watches>

After installation, try one of these prompts and name a course you can access:

**Exam Rescue**

> Check the posted scope for my next exam in Canvas. Find YouTube lessons for those topics and make me a 40-minute watch-and-practice plan. Show anything the videos do not cover.

**Lecture Clarity**

> I got lost in this week's lecture for [course]. Use the Canvas slides to find a clearer YouTube explanation and show how the ideas connect.

**Skill Builder**

> Read the project instructions for [course] in Canvas. Find a YouTube course or playlist that teaches the required skills, then give me a small first practice task.

### Connecting Canvas and YouTube (free, no keys)

- **Canvas:** the skill starts Cubbie's own Canvas connection when it is missing. If that can't finish (for example, it needs a browser extension you can't install), Cubbie opens your school's Canvas in its own browser. You sign in once yourself, including SSO and two-factor approval, and Cubbie then reads course pages read-only. The login is saved for next time. Typing out course material is only the last resort, and it's labeled as supplied.
- **YouTube:** playlists and search results are cataloged by script. YouTube often blocks caption downloads from cloud servers, so Cubbie opens each selected video in its browser, reads the "Show transcript" panel, and imports it. Each timestamp still comes from the real transcript.

No paid browser service, API key or MCP server is involved; everything runs on Cubbie's built-in abilities.

## Run the bundled tools locally

The Python tools handle YouTube cataloging, resumable caption records, evidence checks, and map rendering. They do not connect to Canvas or decide whether a video is semantically relevant; Cubbie performs those tasks using the course sources and inspected captions.

Create an isolated environment and install the pinned dependencies:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Render the offline example without using a real course or network data:

```bash
.venv/bin/python scripts/watch.py sample --output ./output/sample
```

The sample writes `learning-map.pdf`, `learning-map.html`, and `learning-map.svg` under `output/sample/`. Its fictional course and caption evidence are clearly marked synthetic and must not be used as a real course map.

For actual course work, keep Canvas-derived plans, catalogs, captions, checkpoints, and reports in a private course folder outside this repository. Replace `course-term` with a short local label for the course and term:

```bash
COURSE_DIR="$HOME/cubbie-watches/course-term"

.venv/bin/python scripts/watch.py catalog \
  --query "linear systems phase portraits" \
  --playlist "<YouTube playlist URL>" \
  --output "$COURSE_DIR/catalog.json"

.venv/bin/python scripts/watch.py fetch \
  --catalog "$COURSE_DIR/catalog.json" \
  --workspace "$COURSE_DIR/workspace"
```

Use `scripts/watch.py --help` for the full command list. Cataloging searches a finite set of results; it does not search all of YouTube. A selected playlist is enumerated in full by default, while unavailable entries and incomplete retrieval are reported. Caption access may be blocked in a cloud environment; the skill can fall back to Cubbie's browser or a transcript supplied by the student or instructor.

## Evidence and privacy

- Canvas remains the authority for course requirements. Explicit exam instructions take priority; a syllabus alone does not establish exam scope.
- A video is marked matched only after its content supports the requirement at the requested depth. Titles and popularity are not proof of relevance.
- Timestamps and summaries are linked to reviewed caption segments. The validator checks references and timing, but Cubbie must assess the meaning of the evidence.
- Missing, partial, and unverified coverage stays visible. A finite YouTube search cannot promise exhaustive coverage of the platform.
- The scripts do not need a Canvas API token and do not start a Canvas MCP server. Cubbie reads Canvas through its native connected account and supplies the relevant course records to the workflow.
- Keep course files, student information, plans, captions, and rendered reports private. Do not commit them to this public repository.
- The skill supports learning and practice; students should follow their instructor's rules and submit their own work.

## Repository layout

```text
SKILL.md                  Cubbie skill workflow and safety rules
requirements.txt          Pinned Python dependencies
scripts/
  watch.py                Catalog, caption, validate, and build commands
  library.py              Storage and evidence validation
  render.py               PDF, HTML, and SVG map renderer
references/
  plan-schema.md           Source-backed plan format
assets/
  sample.json              Fictional offline sample data
```

## Project status

The skill format and offline sample workflow have been validated locally. A real Cubbie installation with a connected Canvas course is still needed to verify the complete account-level workflow. Always review generated explanations and links against the original course and video sources.
