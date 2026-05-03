"""Génère une cover carrée (1:1) pour un épisode de podcast via Gemini Image.

Lit un prompt visuel pré-rédigé (produit par le sub-agent `image-prompt-writer`),
appelle `google/gemini-3.1-flash-image-preview` sur OpenRouter en 1:1 (compatible
iTunes / AntennaPod / Pocket Casts), et sauve l'image au chemin demandé.

Reprise auto :
- Si `--cover` est fourni OU si une cover existe déjà au chemin cible (toute
  extension supportée png/jpg/webp), on skip l'appel d'image gen.

Fallback : en cas d'erreur OpenRouter (modération, panne), on copie l'asset
`assets/generic_podcast_cover_square.png` (committé une fois pour toutes).

Usage :
    uv run scripts/generate_cover.py --image-prompt outputs/<slug>/image-prompt.txt \\
                                     --output outputs/<slug>/cover.png
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

IMAGE_MODEL: str = "google/gemini-3.1-flash-image-preview"
IMAGE_ASPECT_RATIO: str = "1:1"

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
FALLBACK_DIR: Path = PROJECT_ROOT / "assets"
FALLBACK_STEM: str = "generic_podcast_cover_square"


def _find_fallback() -> Path | None:
    """Cherche le fallback bundle sous toute extension supportée (Gemini peut
    retourner png|jpg|webp ; on commit ce qu'on a sans imposer un format)."""
    for ext in ("png", "jpg", "webp"):
        candidate = FALLBACK_DIR / f"{FALLBACK_STEM}.{ext}"
        if candidate.exists():
            return candidate
    return None


GENERIC_FALLBACK: Path = _find_fallback() or (FALLBACK_DIR / f"{FALLBACK_STEM}.png")

DATA_URI_RE: re.Pattern[str] = re.compile(
    r"^data:image/(?P<ext>png|jpeg|jpg|webp);base64,(?P<b64>.+)$",
    re.DOTALL,
)


@dataclass(frozen=True)
class CoverResult:
    """Résultat de la génération de cover : chemin et provenance (gen vs fallback)."""

    path: Path
    used_fallback: bool


def _load_prompt(path: Path) -> str:
    """Lit le fichier prompt visuel et strip le whitespace."""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Prompt visuel vide : {path}")
    return text


def build_image_payload() -> dict[str, Any]:
    """Construit l'`extra_body` pour l'appel image gen via OpenRouter.

    `modalities` et `image_config` ne sont pas typés dans le SDK OpenAI ; ils
    transitent via `extra_body` qui les merge dans le body JSON brut.
    """
    return {
        "modalities": ["image", "text"],
        "image_config": {"aspect_ratio": IMAGE_ASPECT_RATIO},
    }


def extract_image_bytes(response_data: dict[str, Any]) -> tuple[bytes, str]:
    """Décode l'image base64 de la réponse OpenRouter et retourne (bytes, ext)."""
    try:
        message = response_data["choices"][0]["message"]
        images = message.get("images") or []
        if not images:
            raise ValueError("Réponse OpenRouter sans images (modération ?).")
        image_url = images[0]["image_url"]["url"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(f"Réponse OpenRouter au format inattendu : {exc}") from exc

    match = DATA_URI_RE.match(image_url)
    if not match:
        raise ValueError(f"data URI invalide : {image_url[:60]}...")

    ext = match.group("ext")
    if ext == "jpeg":
        ext = "jpg"
    return base64.b64decode(match.group("b64")), ext


def generate_cover_image(client: OpenAI, prompt: str, base_path: Path) -> Path:
    """Génère la cover via Gemini Image Preview et l'écrit à `base_path` (extension ajustée)."""
    response = client.chat.completions.create(
        model=IMAGE_MODEL,
        messages=[{"role": "user", "content": prompt}],
        extra_body=build_image_payload(),
    )
    image_bytes, ext = extract_image_bytes(response.model_dump())
    final_path = base_path.with_suffix(f".{ext}")
    final_path.parent.mkdir(parents=True, exist_ok=True)
    final_path.write_bytes(image_bytes)
    return final_path


def generate_cover_with_fallback(
    client: OpenAI,
    prompt: str,
    base_path: Path,
    fallback: Path,
) -> CoverResult:
    """Génère la cover ; en cas d'échec (modération, API), copie l'asset fallback."""
    try:
        path = generate_cover_image(client, prompt, base_path)
        return CoverResult(path=path, used_fallback=False)
    except (OpenAIError, ValueError) as exc:
        if not fallback.exists():
            raise RuntimeError(
                f"Génération d'image échouée ({exc}) ET fallback absent : {fallback}"
            ) from exc
        print(
            f"WARN: image gen échouée ({exc}), fallback -> {fallback.name}",
            file=sys.stderr,
        )
        dst = base_path.with_suffix(fallback.suffix)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(fallback, dst)
        return CoverResult(path=dst, used_fallback=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--image-prompt",
        type=Path,
        default=None,
        help="Fichier texte contenant le prompt visuel (produit par image-prompt-writer).",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Chemin cible de la cover (extension ajustée selon ce que l'API retourne).",
    )
    parser.add_argument(
        "--fallback",
        type=Path,
        default=GENERIC_FALLBACK,
        help=f"Image fallback en cas d'échec image gen (défaut: {GENERIC_FALLBACK}).",
    )
    return parser.parse_args(argv)


def _resolve_cover(args: argparse.Namespace, client_factory: Any) -> CoverResult:
    """Résout la cover : cover existante au chemin cible > génération API."""
    base_cover = args.output
    for ext in ("png", "jpg", "webp"):
        candidate = base_cover.with_suffix(f".{ext}")
        if candidate.exists():
            print(f"reuse cover existante : {candidate.name}")
            return CoverResult(path=candidate, used_fallback=False)

    if args.image_prompt is None:
        raise ValueError("--image-prompt requis quand aucune cover n'existe.")
    prompt = _load_prompt(args.image_prompt)
    print(f"image gen ({IMAGE_MODEL}, {IMAGE_ASPECT_RATIO})...")
    client = client_factory()
    return generate_cover_with_fallback(client, prompt, base_cover, args.fallback)


def _make_openai_client() -> OpenAI:
    """Charge la clé OpenRouter depuis .env et instancie le client."""
    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY manquante dans .env.")
    return OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)


def main(argv: list[str] | None = None) -> int:
    """Génère la cover. Retourne un exit code int."""
    args = _parse_args(argv)

    try:
        cover = _resolve_cover(args, _make_openai_client)
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(f"Cover   : {cover.path}" + (" (FALLBACK)" if cover.used_fallback else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
