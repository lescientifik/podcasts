# Carnets de recherche

Mini-podcasts générés par IA qui synthétisent l'état de l'art sur des
sujets pointus en science, tech et méthodologie.

- **Site** : https://lescientifik.github.io/podcasts/
- **Flux RSS** : https://lescientifik.github.io/podcasts/feed.xml
  *(à coller dans AntennaPod / Pocket Casts / etc.)*

## Ajouter un épisode automatiquement

Le pipeline complet (recherche → script → TTS → cover → publication) est
orchestré par la skill Claude Code `podcast-generator` qui vit sous
`.claude/skills/podcast-generator/`. Depuis la racine de ce repo :

```
# Via Claude Code (skill auto-invoquée)
> fais un podcast sur la fission nucléaire

# La skill produit l'audio + cover dans .podcast/<slug>/, appelle
# scripts/add_episode.py pour mettre à jour feed.xml, puis
# scripts/publish.sh pour committer/pusher.
```

Pré-requis :

- `uv` (Python project manager, https://docs.astral.sh/uv/)
- `ffmpeg` + `ffprobe` (système)
- `OPENROUTER_API_KEY` dans `.claude/skills/podcast-generator/.env`
  (voir `.env.example`). Donne accès à Voxtral (TTS), OpenAI shimmer
  (TTS backup) et Gemini 3.1 Flash Image Preview (cover).

## Ajouter un épisode manuellement

Si tu as déjà un MP3 + une cover (1:1, ≥1400 px) ailleurs :

```
python3 scripts/add_episode.py \
  --mp3 /chemin/vers/podcast.mp3 \
  --cover /chemin/vers/cover.jpg \
  --title "Titre lisible de l'épisode" \
  --description "Une à trois phrases qui résument." \
  --notes /chemin/vers/research.md         # optionnel — notes sourcées
  --transcript /chemin/vers/script.md      # optionnel — transcript TTS

# puis
bash scripts/publish.sh "ep00X" "Titre lisible de l'épisode"
```

`add_episode.py` :

- détermine le prochain numéro libre (`ep001`, `ep002`, …) en scannant
  `episodes/` ;
- copie MP3, cover et notes dans `episodes/epNNN.{mp3,jpg|png|webp,md}` ;
- calcule durée + taille via `ffprobe` ;
- insère un nouvel `<item>` dans `feed.xml`, trie par `pubDate` desc ;
- imprime `epNNN` sur stdout (utile pour scripter).

Dépendances : Python stdlib + `ffprobe` (aucune lib externe).

## Structure du repo

```
.
├── index.html        # liste des épisodes + player + recherche + dark mode
├── style.css         # mobile-first, mode sombre, sobre
├── app.js            # fetch feed.xml, render, localStorage (position/vitesse/écouté)
├── feed.xml          # flux RSS 2.0 + namespace itunes (généré, ne pas éditer à la main)
├── cover.jpg         # cover globale du podcast (channel-level)
├── episodes/
│   ├── ep001.mp3            # audio
│   ├── ep001.jpg            # cover de l'épisode (1:1)
│   ├── ep001.md             # notes de recherche sourcées (research.md original)
│   └── ep001.transcript.md  # transcript TTS (script lu par la voix dans le MP3)
├── scripts/
│   ├── add_episode.py  # met à jour feed.xml + copie assets
│   └── publish.sh      # git add/commit/push
├── .claude/
│   ├── agents/         # research-writer, podcast-formatter, image-prompt-writer
│   └── skills/podcast-generator/
│       ├── SKILL.md    # orchestrateur du pipeline complet
│       ├── scripts/    # tts.py, generate_cover.py
│       ├── assets/     # cover fallback carrée
│       ├── pyproject.toml + uv.lock
│       └── .env        # *gitignoré* — contient OPENROUTER_API_KEY
└── .podcast/           # *gitignoré* — cache d'intermédiaires par épisode
```

## Ce qui se passe côté apps de podcast

Le flux RSS respecte la spec **iTunes Podcast RSS 2.0** (namespace
`itunes:*`), lue par AntennaPod, Pocket Casts, Apple Podcasts, Spotify,
etc. Pour s'y abonner :

1. Copier l'URL : `https://lescientifik.github.io/podcasts/feed.xml`
2. AntennaPod → menu → "Ajouter un podcast" → "Ajouter par URL" → coller.
3. Le téléchargement, la position de lecture et les notifications de
   nouvel épisode sont gérés par l'app — pas besoin du site web.

## Ce qui se passe côté navigateur

Le site web (`index.html` + `app.js`) est un complément du flux : il
permet d'écouter sans installer d'app. Il fait du `fetch('feed.xml')`,
parse le XML côté client et persiste en `localStorage` :

- `pos:epNNN` — position de lecture (reprise auto au prochain play)
- `speed:epNNN` — vitesse choisie (1× / 1.25× / 1.5× / 2×)
- `listened:epNNN` — flag "écouté" (mis à `1` à la fin de l'audio)

Aucun build, aucun framework, aucune dépendance JS.
