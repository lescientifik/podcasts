---
description: Cible architecturale pour héberger plusieurs chaînes de podcast indépendantes dans le même repo GitHub Pages, avec subagents dédiés par chaîne.
---

# Architecture multi-chaînes — Design

> Voir aussi [`multi-channel-roadmap.md`](./multi-channel-roadmap.md) pour la séquence d'exécution.

## 1. Contexte et objectif

Le repo `lescientifik/podcasts` héberge aujourd'hui **une** chaîne RSS ("Carnets de recherche") déployée sur GitHub Pages, avec deux épisodes (`ep001`, `ep002`). On veut le faire évoluer pour héberger **N chaînes indépendantes**, chacune avec son propre `feed.xml`, ses propres épisodes, sa cover, sa catégorie iTunes — et surtout **sa propre pipeline de génération** côté skill (subagents et briefs adaptés à la nature du contenu).

Cas d'usage attendus (exemples du user, non gravés) :

- `carnets` — tech/recherche (existant, à migrer)
- `kids_educative` — vulgarisation pédagogique pour enfants
- `kids_stories` — histoires originales racontées pour enfants
- `medical_research` — veille de recherche médicale

Note : les noms exacts (`kids_*`, `medical_research`) ne sont que des illustrations. L'architecture doit accueillir N chaînes définies par config.

## 2. Décisions

| Décision | Choix | Raison |
|---|---|---|
| Métadonnées chaînes | `channels.yaml` centralisé à la racine | La landing page racine a besoin d'une vue globale ; ajouter une chaîne reste rare. L'argument "auto-suffisance" du distribué n'est marginal qu'à cette échelle (3-5 chaînes max prévisibles). |
| Layout disque | `<channel>/feed.xml` + `<channel>/episodes/` + `<channel>/index.html` + `<channel>/cover.{jpg,png}` | Chaque chaîne devient un site complet sous son propre préfixe d'URL. URL stable côté abonné. |
| Numérotation `epNNN` | Par chaîne, indépendante | `carnets/ep001` et `kids_stories/ep001` peuvent coexister. Sinon, on lierait deux chaînes au compteur global, ce qui n'a pas de sens. |
| Choix de chaîne dans le skill | `AskUserQuestion` à l'étape 0 (avec option "créer une nouvelle chaîne") | Confirmé par le user. Zéro friction usage normal, onboarding minimal au premier épisode d'une nouvelle chaîne. |
| Per-chaîne : voix TTS / durée / public | **Non** | Voxtral n'a qu'une voix ; durée et public restent des choix par épisode. Pas de défaut figé qui obligerait à se battre contre le skill. |
| Per-chaîne : subagents | **Oui — c'est le vrai levier** | Une histoire pour enfants n'a rien à voir avec un rapport de recherche. On veut pouvoir spécifier `pipeline.research.subagent: kids-story-writer` au lieu de `research-writer`. |
| Style d'image | `style_hint` injecté dans le brief de `image-prompt-writer` | Suffit pour différencier visuellement les chaînes sans dupliquer le subagent. |

## 3. Layout cible

```
podcasts/
├── channels.yaml                # registre central (source de vérité)
├── index.html                   # landing racine (cards des chaînes)
├── style.css                    # CSS partagé root + per-channel
├── app.js                       # JS partagé, lit slug courant via <meta>
├── README.md
├── plans/                       # ce dossier (ne sera pas servi)
├── scripts/
│   ├── add_episode.py           # accepte --channel <slug>
│   ├── build_pages.py           # NEW : génère index.html racine + <channel>/index.html + <channel>/feed.xml initial
│   ├── publish.sh               # accepte <channel> <ep> "<title>"
│   └── templates/               # NEW
│       ├── root.html            # template landing racine
│       ├── channel.html         # template page par chaîne
│       └── feed_skeleton.xml    # template feed.xml vide pour bootstrap
├── carnets/                     # chaîne migrée
│   ├── feed.xml
│   ├── cover.jpg                # ex-cover.jpg racine
│   ├── index.html               # généré
│   └── episodes/
│       ├── ep001.{mp3,jpg,md,transcript.md}
│       └── ep002.{mp3,png,md,transcript.md}
├── kids_stories/                # exemple, créé à la première utilisation
│   ├── feed.xml
│   ├── cover.png
│   ├── index.html
│   └── episodes/
└── medical_research/
    └── …
```

Hors-arbre :

- `~/.claude/agents/` — où vivent les définitions de subagents (existants : `research-writer`, `podcast-formatter`, `image-prompt-writer` ; à créer : `kids-story-writer`, peut-être `kids-learning-writer`).

## 4. Schéma `channels.yaml`

```yaml
site:
  base_url: "https://lescientifik.github.io/podcasts"
  repo_url: "https://github.com/lescientifik/podcasts"

channels:
  carnets:
    title: "Carnets de recherche"
    description: "Mini-podcasts générés par IA qui synthétisent l'état de l'art sur des sujets pointus en science, tech et méthodologie."
    language: fr-FR
    author: lescientifik
    cover: cover.jpg                       # relatif à <channel>/
    itunes:
      category: "Technology"
      explicit: false
    pipeline:
      research:
        subagent: research-writer
        # brief_extra: "..."               # optionnel : prose injectée dans le brief
      formatter:
        subagent: podcast-formatter
      image_prompt:
        subagent: image-prompt-writer
        style_hint: "abstract editorial illustration, indigo / cyan / orange tones"

  kids_stories:
    title: "Histoires racontées"
    description: "Histoires originales lues à voix posée pour les enfants."
    language: fr-FR
    author: lescientifik
    cover: cover.png
    itunes:
      category: "Kids & Family"
      explicit: false
    pipeline:
      research:
        subagent: kids-story-writer        # NEW agent à écrire
      formatter:
        subagent: podcast-formatter
        brief_extra: "Phrases courtes, vocabulaire simple, rythme conté, pauses naturelles."
      image_prompt:
        subagent: image-prompt-writer
        style_hint: "warm watercolor children's book illustration, soft pastels"

  kids_educative:
    title: "À hauteur d'enfant"
    description: "Mini-leçons pour comprendre le monde, taillées pour les 6-10 ans."
    language: fr-FR
    author: lescientifik
    cover: cover.png
    itunes:
      category: "Kids & Family"
      explicit: false
    pipeline:
      research:
        subagent: research-writer          # ou kids-learning-writer si on l'écrit
        brief_extra: "Public 6-10 ans. Pas de jargon. Analogies concrètes. Une seule idée à la fois."
      formatter:
        subagent: podcast-formatter
        brief_extra: "Phrases courtes, paragraphes courts, ton chaleureux."
      image_prompt:
        subagent: image-prompt-writer
        style_hint: "playful flat illustration, bold primary colors, kid-friendly geometry"
```

**Champs minimum requis** par chaîne : `title`, `description`, `language`, `author`, `cover`, `itunes.category`, `pipeline.research.subagent`, `pipeline.formatter.subagent`, `pipeline.image_prompt.subagent`.

**Champs optionnels** : `itunes.explicit` (default `false`), `pipeline.*.brief_extra`, `pipeline.image_prompt.style_hint`.

## 5. Pipeline avec subagent par chaîne

Vue d'ensemble de qui fait quoi par type de chaîne :

| Étape | `carnets` / `medical_research` | `kids_educative` | `kids_stories` |
|-------|--------------------------------|------------------|----------------|
| 1 — Recherche / contenu | `research-writer` | `research-writer` + brief_extra adapté (ou `kids-learning-writer` si on le crée) | `kids-story-writer` (NEW) |
| 2a — Formatter | `podcast-formatter` | `podcast-formatter` + brief_extra | `podcast-formatter` + brief_extra |
| 2b — Image prompt | `image-prompt-writer` | idem + style_hint | idem + style_hint |
| 3 — TTS | `tts.py` (Voxtral) | identique | identique |
| 4 — Cover gen | `generate_cover.py` (Gemini) | identique | identique |
| 5 — Publication | `add_episode.py --channel <slug>` + `publish.sh <channel>` | identique | identique |

**Conséquence pratique** : seules les étapes 1 et 2 dépendent de la chaîne. Les étapes 3-4-5 sont channel-agnostic (sauf le routage de paths).

### Recommandation `kids-story-writer` vs brief alternatif

Pour `kids_stories`, le format est si éloigné d'un rapport de recherche (récit narratif vs synthèse + sources) qu'un subagent dédié est plus propre qu'un brief surchargé sur `research-writer`. À écrire dans `~/.claude/agents/kids-story-writer.md`.

Pour `kids_educative`, un brief dédié sur `research-writer` peut suffire (le format reste explicatif). On peut créer `kids-learning-writer` plus tard si on rencontre des frottements.

## 6. Modifications de code, par fichier

### 6.1 `scripts/add_episode.py`

- **Nouveau flag** `--channel <slug>` (obligatoire).
- Charge `channels.yaml` (PyYAML — à ajouter aux deps si pas déjà présent ; sinon parser stdlib JSON via conversion). Vérifie que le slug existe.
- `EPISODES_DIR = REPO_ROOT / channel / "episodes"` ; `FEED_PATH = REPO_ROOT / channel / "feed.xml"`.
- `SITE_BASE_URL` per-chaîne : `f"{site.base_url}/{channel}"`.
- Si `<channel>/feed.xml` manquant : déléguer à `build_pages.py` pour scaffold (voir 6.3) plutôt que dupliquer la logique.
- La numérotation `epNNN` reste **par chaîne** (chaque chaîne a sa propre séquence).

### 6.2 `scripts/publish.sh`

- Signature : `publish.sh <channel> <ep> "<title>"`.
- Remplacer `git add .` par `git add channels.yaml index.html <channel>/ scripts/` — ciblé, pour éviter la régression "fichier parasite à la racine" qu'on a déjà rencontrée sur `ep002`.
- Refuser si `<channel>` n'existe pas dans `channels.yaml` ou si `<channel>/episodes/<ep>.mp3` est absent.
- Commit message : `"<channel>: nouvel épisode <ep>: <title>"`.
- Au passage, conserver le fix d'apostrophe (`d episode`) dans le message d'erreur du `${1:?}`.

### 6.3 `scripts/build_pages.py` (nouveau)

But : générateur statique idempotent à exécuter (a) lors de la migration initiale, (b) chaque fois qu'une chaîne est ajoutée ou que ses métadonnées changent dans `channels.yaml`.

Responsabilités :

1. Lire `channels.yaml`.
2. Pour chaque chaîne :
   - Si `<channel>/` n'existe pas, le créer.
   - Si `<channel>/feed.xml` n'existe pas, l'écrire à partir de `templates/feed_skeleton.xml` (channel-level metadata uniquement, zéro item).
   - Régénérer `<channel>/index.html` à partir de `templates/channel.html`, paramétré par les métadonnées.
3. Régénérer `index.html` racine à partir de `templates/root.html` avec une card par chaîne.
4. Mode `--dry-run` qui imprime le diff prévu sans écrire.

Implémentation : `string.Template` ou simples `str.replace()` ; pas besoin de Jinja2.

### 6.4 `index.html` racine (généré)

Petite landing avec une card par chaîne :

- Titre, description, cover thumbnail, lien `<channel>/`, lien direct `<channel>/feed.xml`.
- Réutilise `style.css` partagé.

### 6.5 `<channel>/index.html` (généré)

Quasi identique à l'actuel `index.html`, paramétré sur title/description/cover.

Adaptation requise dans `app.js` : le slug de chaîne doit être lisible côté JS (pour construire les URLs GitHub vers notes/transcript). On l'injecte via `<meta name="channel" content="<slug>">` dans la page générée. Le JS lit cette meta et construit `${REPO_URL}/blob/main/${slug}/episodes/${guid}.md`.

### 6.6 `app.js`

Diff minimal :

- Lire le slug : `const CHANNEL = document.querySelector('meta[name="channel"]')?.content || '';`
- Construction des URLs notes/transcript : `${REPO_URL}/blob/main/${CHANNEL}/episodes/${ep.guid}.md`.
- `FEED_URL = 'feed.xml'` reste relatif → marche dans `<channel>/`.

### 6.7 `style.css`

Ajouter quelques règles pour la grille de cards de la landing racine (`.channels-grid`, `.channel-card`). Reste inchangé.

### 6.8 `feed.xml` (par chaîne)

L'URL absolue dans `<atom:link>`, `<link>`, `<enclosure>` et `<itunes:image>` doit incorporer le slug : `${base_url}/${channel}/...`. Géré côté `add_episode.py`.

### 6.9 Skill `.claude/skills/podcast-generator/SKILL.md`

Voir [roadmap §5 Phase 5](./multi-channel-roadmap.md#phase-5--refactor-du-skill) pour la séquence. Changements logiques :

- **Step 0** : nouvelle sous-étape **0a — Sélection de chaîne** avant la micro-recherche. Lit `channels.yaml`, pose `AskUserQuestion` ("Dans quelle chaîne publier ?"), inclut une option "Créer une nouvelle chaîne". Si "nouvelle chaîne" → mini-onboarding (slug, titre, description, catégorie iTunes, choix subagents) → met à jour `channels.yaml` → lance `build_pages.py` → continue.
- **Step 0b** : micro-recherche + 4 questions de cadrage (inchangé), avec une option "ne pas demander la durée si la chaîne le suggère" → mais on a écarté ça, donc on garde 4 questions classiques.
- **Step 1, 2a, 2b** : le `subagent_type` n'est plus hard-codé `research-writer` / `podcast-formatter` / `image-prompt-writer` mais lu depuis `channels.{slug}.pipeline.*.subagent`. Le `brief_extra` éventuel est concaténé au brief existant.
- **Step 5a** : `add_episode.py --channel <slug>`.
- **Step 5b** : `publish.sh <channel> <ep> "<title>"`.
- **Step 6** : récap utilise les URLs per-channel (`/<channel>/#<ep>` et `/<channel>/feed.xml`).

`OUT_DIR` devient `${REPO_ROOT}/.podcast/<channel>/<topic_slug>` pour permettre le même topic_slug sur deux chaînes différentes.

## 7. Stratégie de migration de l'existant

`carnets` accueille les deux épisodes existants.

Étapes (détaillées dans le roadmap) :

1. `git mv feed.xml carnets/feed.xml`, `git mv cover.jpg carnets/cover.jpg`, `git mv episodes carnets/episodes`.
2. Mettre à jour les URLs absolues dans `carnets/feed.xml` (préfixe `/carnets`).
3. Générer `index.html` racine + `carnets/index.html` via `build_pages.py`.
4. Vérifier en local (`python3 -m http.server`) puis push.

**URLs cassées par la migration** :

- `…/podcasts/feed.xml` → 404 (devient `…/podcasts/carnets/feed.xml`).
- `…/podcasts/episodes/ep001.mp3` → 404 (devient `…/podcasts/carnets/episodes/ep001.mp3`).

Acceptable : aucun abonné externe à ce jour. Si on veut adoucir : `404.html` côté GH Pages avec redirection JS vers `carnets/`.

## 8. Tradeoffs explicites

- **Centralisé vs distribué pour `channels.yaml`** : argument "auto-suffisance" du distribué = supprimer un dossier suffit à supprimer la chaîne sans toucher au fichier central. À l'échelle 3-5 chaînes c'est marginal, et la perte d'une vue globale (utile pour la landing page) coûte plus.
- **Numérotation par chaîne** : `kids_stories/ep001` peut exister en parallèle de `carnets/ep001`. Plus naturel, sépare les compteurs.
- **`build_pages.py` vs `index.html` hand-written** : générer évite la dérive entre `channels.yaml` et le HTML, et simplifie l'ajout d'une chaîne (1 commande).
- **Format YAML vs JSON pour `channels.yaml`** : YAML supporte les commentaires et reste lisible avec des champs imbriqués. PyYAML est une dépendance modeste (~150 KB). Acceptable.

## 9. Hors-scope V1

- Recherche cross-chaînes côté front-end.
- Statistiques d'écoute / analytics.
- Validation de schéma via Pydantic (V2 si on se fâche avec un YAML invalide).
- Migration des anciennes URLs via `404.html` (V2 si quelqu'un s'en plaint).
- Génération automatique d'une cover de chaîne (channel-level cover) — pour l'instant on en commit une à la main.

## 10. Risques

- **Drift entre `channels.yaml` et l'arborescence disque** : si on supprime un dossier sans nettoyer le YAML, `build_pages.py` doit avertir. Inversement, si une chaîne est listée dans le YAML mais que son dossier n'existe pas, `build_pages.py` la scaffolde.
- **Subagents inexistants** : `kids-story-writer` doit être écrit avant qu'on lance le pipeline pour `kids_stories`. Le skill doit échouer proprement avec un message explicite si le subagent n'existe pas.
- **`git add .` aveugle** : on l'a déjà payé une fois (fichier parasite `eval_closed_loop_pydanticai/podcast-script.md` swept dans `ep002`). Le nouveau `publish.sh` ne fait plus `git add .` — `git add` ciblé seulement.
