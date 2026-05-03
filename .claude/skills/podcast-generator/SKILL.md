---
name: podcast-generator
description: Generate a complete French research podcast end-to-end (research → script → TTS audio → square cover image → publish to GitHub Pages + RSS feed) from a single topic. Use when the user asks to make, create, or generate a podcast about any topic.
when_to_use: "Example requests in French: 'fais un podcast sur la fission nucléaire', 'génère un podcast sur les biais cognitifs', 'crée un podcast sur X'. Or in English: 'make a podcast about Y'. Does NOT apply to just writing a research note or a script without audio/video output."
arguments: [topic]
disable-model-invocation: false
allowed-tools: Agent AskUserQuestion Bash Read Write Glob WebSearch
---

# Podcast Generator Orchestrator

Generate a full French research podcast end-to-end from a single topic.
Final deliverable: the URL of the new episode on the GitHub Pages site
plus the RSS feed URL.

## Input

**Topic**: $topic

## Layout & Path Conventions

This skill is fully self-contained: scripts, assets, and the Python
project (`pyproject.toml` + `uv.lock`) all live under
`${CLAUDE_SKILL_DIR}`. The user's current working directory is the root
of the **`podcasts` GitHub Pages repo** — that's where per-episode
intermediate artefacts go (under `.podcast/`, gitignored) and where the
final `episodes/` + `feed.xml` are committed.

Resolve these once at the start of the run and reuse:

- `SKILL_DIR=${CLAUDE_SKILL_DIR}` — bundled scripts, assets, pyproject.
- `REPO_ROOT="$PWD"` — must be the root of the `podcasts` GitHub Pages repo
  (i.e. contain `feed.xml`, `index.html`, `scripts/add_episode.py`).
  Stop with an explicit error if those files don't exist.
- `SLUG` — derived from `$topic` (see slug rules below).
- `OUT_DIR="$REPO_ROOT/.podcast/$SLUG"` — absolute path to per-episode
  intermediate artefacts. Gitignored. Re-runs reuse this.

### Slug rules

From `$topic`:
- lowercase
- strip accents (é→e, à→a, ç→c, …)
- replace any run of non-alphanumeric characters with a single `_`
- trim leading/trailing `_`

Example: `"La fission nucléaire"` → `la_fission_nucleaire`.

If unsure, ask the user to confirm the slug before proceeding.

### Bootstrap

The Python scripts call `load_dotenv()` without arguments, which only
finds `.env` in the current working directory — useless when the user
invokes the skill from anywhere. So the orchestrator must explicitly
export secrets from the bundled `${SKILL_DIR}/.env` into the shell once
at the start of the run, before any `uv run`:

```bash
mkdir -p "$OUT_DIR"
set -a
source "$SKILL_DIR/.env"
set +a
```

After this, `OPENROUTER_API_KEY` is in the env, and every subsequent
`uv run …` child process inherits it.

## Pipeline Overview

```
research-writer ──► research.md
                         │
            ┌────────────┴────────────┐
            ▼                         ▼
   podcast-formatter            image-prompt-writer
            │                         │
            ▼                         ▼
       tts.py                  generate_cover.py
            │                         │
            ▼                         ▼
       podcast.mp3                cover.{png,jpg}
            │                         │
            └─────────────┬───────────┘
                          ▼
                    add_episode.py
                  (copy to episodes/,
                   update feed.xml)
                          │
                          ▼
                     publish.sh
                  (git add/commit/push)
                          │
                          ▼
              https://lescientifik.github.io/
                podcasts/#ep###  ✓
```

## Resume Logic

Before every step, check if its output already exists. If yes, skip it.
The expected artefacts under `$OUT_DIR`:

```
$OUT_DIR/
├── research.md             # step 1
├── podcast-script.md       # step 2a
├── image-prompt.txt        # step 2b
├── podcast.mp3             # step 3
├── cover.{png,jpg,webp}    # step 4
└── ep_number.txt           # step 5 — episode number assigned, marker for "published"
```

## Step 0 — Clarification (alignement avec le user)

**Avant toute exécution** (avant même de calculer le slug ou de
préparer `$OUT_DIR`), poser quelques questions ciblées via
`AskUserQuestion` pour s'assurer que le podcast produit correspond à
ce que le user attend.

Skip cette étape **uniquement si** :
- `$OUT_DIR/research.md` existe déjà (reprise après échec partiel), OU
- le user a déjà précisé tous les points dans sa demande initiale
  (angle, durée, ton, public).

### Micro-recherche préalable

Avant de formuler les questions, faire **1 à 2 appels `WebSearch`**
ciblés sur `$topic`. Objectif : repérer en ~30 s les angles réels qui
existent autour du sujet. Ne pas lire en profondeur.

### Questions à poser

Regrouper les questions dans **un seul appel `AskUserQuestion`** (4
questions max). Couvrir au minimum :

1. **Angle / focus** — quelle facette du sujet privilégier ?
2. **Profondeur / durée cible** — court (~20 min), moyen (~40 min),
   long (~70 min).
3. **Niveau du public** — débutant, curieux informé, expert.
4. **Points à inclure ou éviter** (optionnel).

### Propagation des réponses

Les réponses **doivent** être incluses dans le brief de
`research-writer` (Step 1) ET de `podcast-formatter` (Step 2a).

## Step 1 — Research

Skip if `$OUT_DIR/research.md` already exists.

Delegate to the `research-writer` sub-agent with a brief that includes:
- the topic (`$topic`)
- the absolute output directory (`$OUT_DIR`)
- the explicit instruction to write to `<OUT_DIR>/research.md`
- le bloc "Cadrage user" issu de l'étape 0

Wait for completion, then verify the file exists and is non-empty.

## Step 2 — Formatting + Image Prompt (parallel)

Delegate **in a single message with two `Agent` tool calls** so they
run concurrently:

- `podcast-formatter` — brief: `OUT_DIR=<OUT_DIR>`. Reads
  `<OUT_DIR>/research.md`, writes `<OUT_DIR>/podcast-script.md`.
- `image-prompt-writer` — brief: `OUT_DIR=<OUT_DIR>`. Reads
  `<OUT_DIR>/research.md`, writes `<OUT_DIR>/image-prompt.txt`.

Skip whichever output already exists. Verify both files exist after.

## Step 3 — TTS

Skip if `$OUT_DIR/podcast.mp3` already exists.

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/tts.py" \
  --input "$OUT_DIR/podcast-script.md" \
  --output "$OUT_DIR/podcast.mp3"
```

If the run fails with a Voxtral-specific error (rate limit, server
error), retry once with the OpenAI backup voice:

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/tts.py" \
  --input "$OUT_DIR/podcast-script.md" \
  --output "$OUT_DIR/podcast.mp3" \
  --voice openai_shimmer_125x
```

## Step 4 — Cover Image (square 1:1)

Skip if `$OUT_DIR/cover.{png,jpg,webp}` already exists.

The script generates a 1:1 cover (compatible iTunes / AntennaPod /
Pocket Casts) via Gemini 3.1 Flash Image Preview. Falls back
automatically to `${SKILL_DIR}/assets/generic_podcast_cover_square.png`
on image-gen failure.

```bash
uv run --project "$SKILL_DIR" "$SKILL_DIR/scripts/generate_cover.py" \
  --image-prompt "$OUT_DIR/image-prompt.txt" \
  --output "$OUT_DIR/cover.png"
```

## Step 5 — Publish to GitHub Pages

Skip if `$OUT_DIR/ep_number.txt` exists (means the episode is already
registered in `feed.xml`).

### 5a — Add the episode to `feed.xml` and copy assets

`add_episode.py` lives at the repo root (`$REPO_ROOT/scripts/add_episode.py`),
uses Python stdlib + `ffprobe` only (no extra deps).

Locate the cover (the actual extension may differ from `.png`):

```bash
COVER=$(ls "$OUT_DIR"/cover.{png,jpg,webp} 2>/dev/null | head -1)
```

Title and description for the episode item:

- **Title** = `$topic` verbatim (the human-readable input).
- **Description** = the `description` field from `research.md`'s YAML
  frontmatter (first occurrence). Fallback: 1st non-empty paragraph of
  `research.md` truncated to ~280 chars.

```bash
python3 "$REPO_ROOT/scripts/add_episode.py" \
  --mp3 "$OUT_DIR/podcast.mp3" \
  --cover "$COVER" \
  --title "$topic" \
  --description "<extracted description>" \
  --notes "$OUT_DIR/research.md" \
  --transcript "$OUT_DIR/podcast-script.md" \
  | tee "$OUT_DIR/ep_number.txt"
```

(`--notes` = research.md sourced report, `--transcript` = TTS-ready
podcast-script.md — both committed in `episodes/` so users can read or
search them on GitHub.)

The script prints the assigned episode number on its last stdout line
(e.g. `ep002`). `tee` persists it for resume.

### 5b — Commit & push

```bash
bash "$REPO_ROOT/scripts/publish.sh" "$(cat "$OUT_DIR/ep_number.txt")" "$topic"
```

`publish.sh` does `git add . && git commit -m … && git push`. GitHub
Pages picks up the change automatically (~1 min). The new episode is
live at `https://lescientifik.github.io/podcasts/#<ep_number>` and the
RSS feed at `https://lescientifik.github.io/podcasts/feed.xml`.

### Pre-flight checks (first run of a session only)

Verify before the very first publish:

- `git remote get-url origin` returns a `lescientifik/podcasts`
  remote — stop otherwise.
- `git status` is reasonably clean (or warn the user if there are
  unrelated uncommitted changes that would get swept up by `git add .`).

## Step 6 — Return Result

Read the episode number from `$OUT_DIR/ep_number.txt`, then present:

- topic (= `$topic`)
- final word count of `podcast-script.md`
- final MP3 duration (`ffprobe -i "$OUT_DIR/podcast.mp3" -show_entries format=duration -v quiet -of csv="p=0"`)
- whether the cover was AI-generated or fell back to the generic asset
- the episode URL: `https://lescientifik.github.io/podcasts/#<ep_number>`
- the RSS feed URL: `https://lescientifik.github.io/podcasts/feed.xml`
  (rappeler au user qu'il peut le coller dans AntennaPod / Pocket Casts)

## Error Handling Summary

| Step | Failure mode | Action |
|------|-------------|--------|
| 1 (research) | Agent error / network | Report and stop. User reruns. |
| 2 (formatter) | Paragraph > 400 words detected later | Re-run formatter once. |
| 3 (TTS) | Voxtral rate limit / 5xx | Retry once with `--voice openai_shimmer_125x`. |
| 3 (TTS) | Truncation flagged on a chunk | The script auto-retries × 3 internally. |
| 4 (cover) | Moderation rejection | Script falls back to bundled square generic cover. No action. |
| 5a (add_episode) | `ffprobe` missing | Stop and tell user to install ffmpeg. |
| 5a (add_episode) | feed.xml malformed | Stop. The user must fix manually before retry. |
| 5b (publish) | git push rejected | Surface the git error. Likely auth or remote conflict. |

Never silently swallow an error: surface it to the user with the
failed command and the relevant `$OUT_DIR/` path so they can diagnose.
