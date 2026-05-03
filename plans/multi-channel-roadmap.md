---
description: Roadmap pas-à-pas pour migrer le repo mono-chaîne vers une architecture multi-chaînes, avec validation à chaque phase.
---

# Roadmap multi-chaînes

> Voir [`multi-channel-architecture.md`](./multi-channel-architecture.md) pour le rationnel des décisions et le schéma cible. Ce fichier liste **dans quel ordre** procéder, avec un critère de validation à la fin de chaque phase.

Hypothèse de travail : on opère sur une branche `feat/multi-channel`, on merge dans `main` à la phase 8 uniquement.

## Phase 0 — Branche et plans

- [ ] `git switch -c feat/multi-channel`
- [x] `plans/multi-channel-architecture.md` (fait)
- [x] `plans/multi-channel-roadmap.md` (ce fichier)
- [ ] Décider si l'on s'autorise PyYAML comme dépendance Python (sinon : conversion `channels.yaml` → JSON pour parsing stdlib). **Recommandation** : ajouter `PyYAML` à `scripts/` (zéro impact sur le skill), c'est trivial.

**Validation** : branche dédiée propre, plans pushés, alignement user obtenu sur les choix d'architecture.

## Phase 1 — `channels.yaml` et templates

- [ ] Écrire `channels.yaml` à la racine avec **au minimum** la chaîne `carnets` (titre/description/cover recopiés depuis l'actuel `feed.xml`). Cf. [§4 du plan](./multi-channel-architecture.md#4-schéma-channelsyaml).
- [ ] Créer `scripts/templates/` :
  - `root.html` — landing avec `{{channels_cards}}` placeholder.
  - `channel.html` — équivalent fonctionnel de l'actuel `index.html`, avec `{{title}}`, `{{description}}`, `{{cover_path}}`, `{{channel_slug}}`, et `<meta name="channel" content="{{channel_slug}}">` injecté.
  - `feed_skeleton.xml` — squelette feed RSS avec channel-level metadata + zéro `<item>`.

**Validation** : `channels.yaml` parse avec `python3 -c "import yaml; yaml.safe_load(open('channels.yaml'))"`. Les templates contiennent des placeholders cohérents avec le code à venir.

## Phase 2 — `build_pages.py`

- [ ] Écrire `scripts/build_pages.py`.
  - Charge `channels.yaml`.
  - Pour chaque chaîne : crée `<channel>/` si absent, écrit `<channel>/feed.xml` depuis le squelette si absent (sans toucher si présent), régénère `<channel>/index.html` depuis `templates/channel.html`.
  - Régénère `index.html` racine depuis `templates/root.html`.
  - Mode `--dry-run` qui imprime `+ écrirait <path>` / `~ régénérerait <path>` sans rien écrire.
  - Mode normal : idempotent. Avertir si `channels.yaml` liste une chaîne dont le dossier existe mais que la cover référencée est manquante.
- [ ] Tester `python3 scripts/build_pages.py --dry-run` avant la phase 3.

**Validation** : sortie `--dry-run` cohérente, aucune écriture disque effectuée.

## Phase 3 — Migration de l'existant vers `carnets/`

⚠ Phase qui touche au feed publié. À faire avec un commit distinct des autres phases pour pouvoir revert si problème.

- [ ] `git mv feed.xml carnets/feed.xml`
- [ ] `git mv cover.jpg carnets/cover.jpg`
- [ ] `git mv episodes carnets/episodes`
- [ ] Mettre à jour les URLs absolues dans `carnets/feed.xml` :
  - `<atom:link href="…/feed.xml">` → `…/carnets/feed.xml`
  - `<link>…/</link>` du channel → `…/carnets/`
  - `<itunes:image href="…/cover.jpg">` → `…/carnets/cover.jpg`
  - Tous les `<enclosure url="…/episodes/epNNN.mp3">` → `…/carnets/episodes/epNNN.mp3`
  - Tous les `<itunes:image href="…/episodes/epNNN.png">` → `…/carnets/episodes/epNNN.png`
- [ ] `python3 scripts/build_pages.py` — génère `index.html` racine + `carnets/index.html`.
- [ ] Vérifier que `app.js` et `style.css` restent à la racine ; `<channel>/index.html` les charge en `../app.js` / `../style.css`.
- [ ] Test local :
  ```bash
  cd /home/thenry/experiments/podcasts
  python3 -m http.server 8000
  # ouvrir http://localhost:8000/                    → landing
  #        http://localhost:8000/carnets/             → liste épisodes
  #        http://localhost:8000/carnets/feed.xml     → feed valide
  ```
  Vérifier : MP3 jouables, lecture position sauvée, search OK, liens transcript/notes pointent vers `…/blob/main/carnets/episodes/…`.

**Validation** : navigation locale OK ; `python3 -c "import xml.etree.ElementTree as ET; ET.parse('carnets/feed.xml')"` passe sans erreur.

## Phase 4 — Refactor `add_episode.py`

- [ ] Ajouter `--channel <slug>` (obligatoire).
- [ ] Charger `channels.yaml`, valider que `<channel>` existe ; sinon échouer avec un message qui suggère `python3 scripts/build_pages.py` après ajout dans le YAML.
- [ ] Recalculer `EPISODES_DIR`, `FEED_PATH`, `SITE_BASE_URL` per-channel.
- [ ] Si `<channel>/feed.xml` est absent, déclencher `build_pages.py` (sous-process) avant d'insérer l'item.
- [ ] Garder le contrat de stdout : la dernière ligne reste `epNNN`. Le récap reste sur stderr. Le caller (skill) peut continuer à extraire l'ep number par `tail -n 1`.

**Validation** :
- Exécution sur un MP3 factice avec `--channel carnets` : nouveau `<item>` inséré, `epNNN` correctement incrémenté.
- Exécution avec `--channel inexistant` : échec propre, message clair, exit code non nul.

## Phase 5 — Refactor `publish.sh`

- [ ] Nouvelle signature : `publish.sh <channel> <ep> "<title>"`.
- [ ] Remplacer `git add .` par `git add channels.yaml index.html style.css app.js scripts/ <channel>/` — ciblé.
- [ ] Refuser (`exit 1`) si `<channel>/episodes/<ep>.mp3` n'existe pas ou si `channels.yaml` ne contient pas `<channel>`.
- [ ] Commit message : `"<channel>: nouvel épisode <ep>: <title>"`.
- [ ] Garder les apostrophes échappées dans `${1:?…}` (déjà fait dans le commit `77e073a`).

**Validation** : `bash scripts/publish.sh carnets ep999 "Test"` (sans MP3 correspondant) échoue proprement. Avec un faux MP3 placeholder, commit ciblé OK, aucun fichier hors `carnets/` ni hors scripts modifiés n'est inclus.

## Phase 6 — Refactor du skill `SKILL.md`

Cf. [§6.9 du plan](./multi-channel-architecture.md#69-skill-claudeskillspodcast-generatorskillmd) pour le détail.

- [ ] **Step 0a — Sélection de chaîne** (nouveau, avant la micro-recherche) :
  - Charger `channels.yaml` côté skill (via `Bash` → `python3 -c "import yaml..."`).
  - Si invocation a un arg `--channel`, le respecter (mais le contrat skill actuel ne prévoit qu'un `topic` ; on peut soit ajouter un 2ᵉ arg optionnel, soit toujours demander).
  - Sinon : `AskUserQuestion` "Dans quelle chaîne publier ?" avec options = chaînes existantes + "Créer une nouvelle chaîne".
  - Branche "Créer une nouvelle chaîne" : 4 sous-questions (slug, titre, description, catégorie iTunes), avec recommandation pour les choix de subagents (`research-writer` par défaut, `kids-story-writer` si applicable). Mettre à jour `channels.yaml` puis lancer `build_pages.py`.
- [ ] **Step 0b — Cadrage** (existant, inchangé sauf pour propager le slug en aval).
- [ ] **OUT_DIR** : devient `${REPO_ROOT}/.podcast/<channel_slug>/<topic_slug>` pour permettre le même topic sur 2 chaînes.
- [ ] **Step 1 / 2a / 2b** : remplacer les `subagent_type` hard-codés par les valeurs lues dans `channels.{slug}.pipeline.*.subagent`. Concaténer le `brief_extra` éventuel au brief existant. Pour `image_prompt`, injecter `style_hint` dans la prompt fournie au subagent.
- [ ] **Step 5a** : ajouter `--channel <slug>` à l'appel `add_episode.py`.
- [ ] **Step 5b** : changer l'appel en `bash "$REPO_ROOT/scripts/publish.sh" "<channel>" "<ep>" "<title>"`.
- [ ] **Step 6 — récap** : URLs deviennent `…/<channel>/#<ep>` et `…/<channel>/feed.xml`. Mentionner explicitement le slug dans le récap.
- [ ] **Pre-flight checks** : vérifier que `<channel>/feed.xml` existe (ou que la chaîne est listée dans `channels.yaml` et qu'on est en train de la scaffolder).

**Validation** : un nouvel épisode `carnets/ep003` se génère bout-en-bout depuis l'invocation skill, sans intervention manuelle, et atterrit dans `carnets/` (et nulle part ailleurs).

## Phase 7 — Subagent `kids-story-writer` (si on prévoit la chaîne stories)

À ne déclencher qu'au moment de créer la 1re chaîne `kids_stories`. Peut être différé, le skill doit échouer proprement avec un message clair si le subagent est demandé sans exister.

- [ ] Écrire `~/.claude/agents/kids-story-writer.md`. Contrat :
  - **Input** : un thème/topic + cadrage user (âge cible, durée, ton).
  - **Output** : un fichier `<OUT_DIR>/research.md` contenant :
    - Frontmatter YAML obligatoire (`description: <pitch en 1 phrase>`).
    - Une histoire originale structurée (ouverture / péripéties / climax / résolution).
    - Longueur ~3 000-5 000 mots (15-25 min de TTS).
    - Pas de sources externes, pas de section "pour aller plus loin".
  - **Style** : narration à voix posée, phrases courtes, vocabulaire simple, pas de violence ni de notion anxiogène.
  - Le formatter (`podcast-formatter`) en aval prend ce `research.md` et produit un script TTS-ready : pas besoin de l'adapter, juste lui passer un `brief_extra` (déjà prévu dans le YAML).
- [ ] (Optionnel V2) Écrire `kids-learning-writer.md` si `research-writer` + `brief_extra` ne donne pas un résultat satisfaisant pour la chaîne éducative.

**Validation** : générer un épisode test sur `kids_stories` avec un thème simple (ex: "le petit poisson curieux") et vérifier le pipeline complet : story → script TTS → MP3 → cover → feed.

## Phase 8 — Documentation et merge

- [ ] Mettre à jour `README.md` :
  - Décrire l'architecture multi-chaînes.
  - Procédure pour ajouter une chaîne : édit `channels.yaml` + `python3 scripts/build_pages.py`.
  - Lister les subagents requis et leur emplacement (`~/.claude/agents/`).
- [ ] `.gitignore` : confirmer que `.podcast/<channel>/<topic_slug>/` reste gitignoré (modifier la règle si elle est trop spécifique).
- [ ] Suite finale de validations :
  - `python3 -c "import xml.etree.ElementTree as ET; [ET.parse(f) for f in ['carnets/feed.xml']]"` → OK.
  - Test local complet : landing + chaque chaîne servies via `python3 -m http.server`.
- [ ] PR / merge `feat/multi-channel` → `main`.
- [ ] `git push`, attendre déploiement GH Pages (~1 min).
- [ ] Vérification post-déploiement :
  - `https://lescientifik.github.io/podcasts/` → landing accessible.
  - `https://lescientifik.github.io/podcasts/carnets/feed.xml` → feed valide.
  - `https://lescientifik.github.io/podcasts/carnets/episodes/ep002.mp3` → MP3 jouable.
- [ ] Mettre à jour l'URL d'abonnement RSS dans le lecteur (AntennaPod / Pocket Casts) : nouveau lien = `…/carnets/feed.xml`.

**Validation** : site en prod fonctionnel sur la nouvelle structure, anciens épisodes accessibles via leur nouvelle URL.

---

## Annexe — Tableau récapitulatif des artefacts produits/modifiés par phase

| Phase | Création | Modification | Suppression |
|-------|----------|--------------|-------------|
| 1 | `channels.yaml`, `scripts/templates/*` | — | — |
| 2 | `scripts/build_pages.py` | — | — |
| 3 | `carnets/index.html`, `index.html` (racine, écrasé) | `carnets/feed.xml` (déplacé + URLs réécrites) | — (les fichiers déplacés disparaissent de la racine via `git mv`) |
| 4 | — | `scripts/add_episode.py` | — |
| 5 | — | `scripts/publish.sh` | — |
| 6 | — | `.claude/skills/podcast-generator/SKILL.md` | — |
| 7 | `~/.claude/agents/kids-story-writer.md` (hors repo) | — | — |
| 8 | — | `README.md`, `.gitignore` | — |

## Annexe — Commandes de vérification utiles

```bash
# Valider les feeds
python3 -c "import xml.etree.ElementTree as ET; ET.parse('carnets/feed.xml')"

# Valider channels.yaml
python3 -c "import yaml; yaml.safe_load(open('channels.yaml'))"

# Servir localement
python3 -m http.server 8000

# Dry-run du générateur de pages
python3 scripts/build_pages.py --dry-run

# Lister les subagents disponibles
ls ~/.claude/agents/
```

## Annexe — Critère "go/no-go" pour merger

- [ ] Tests locaux phase 3 ✅
- [ ] Génération bout-en-bout phase 6 d'un nouvel épisode `carnets/ep003` ✅
- [ ] Si `kids_stories` créée : génération bout-en-bout phase 7 d'un épisode test ✅
- [ ] Aucun fichier parasite committé (vérifier `git diff --stat main..HEAD`) ✅
- [ ] Documentation `README.md` à jour ✅
