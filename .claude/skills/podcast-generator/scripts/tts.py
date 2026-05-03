"""Synthèse TTS chunkée vers MP3 unique pour le pipeline podcast.

Lit un script markdown podcast-ready (produit par le sub-agent podcast-formatter),
le découpe en chunks de 300-400 mots à frontière de paragraphe, synthétise chaque
chunk via OpenRouter (Voxtral en primaire, OpenAI shimmer x1.25 en backup),
détecte la troncature par analyse RMS et retry × 3 par chunk avant abandon.
Concatène les chunks MP3 en sortie unique via ffmpeg sans réencodage.

Reprise auto : si un chunk MP3 existe déjà et passe la détection de troncature,
on le réutilise sans appel API.

Usage :
    uv run scripts/tts.py --input outputs/<slug>/podcast-script.md \\
                          --output outputs/<slug>/podcast.mp3 \\
                          [--voice voxtral_marie | openai_shimmer_125x]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from dotenv import load_dotenv
from openai import OpenAI

# Chunking — guide: cible 300-400 mots, max 450, paragraphe insécable.
TARGET_MAX_WORDS: int = 400
HARD_MAX_WORDS: int = 450

# Détection de troncature — réutilise les seuils de scripts/analyze_voice_test.py.
PCM_SAMPLE_RATE: int = 24_000
RMS_WINDOW_MS: int = 100
SILENCE_THRESHOLD_RATIO: float = 0.05
MIN_TRAILING_SILENCE_MS: int = 200
MAX_FINAL_AMPLITUDE_PCT: float = 5.0

MAX_RETRIES: int = 3

OPENAI_INSTRUCTIONS: str = (
    "Parle d'une voix posée et claire, style podcast informatif en français, "
    "rythme naturel et débit modéré."
)

HEADING_RE: re.Pattern[str] = re.compile(r"^#{1,6}\s")
FRONTMATTER_RE: re.Pattern[str] = re.compile(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", re.DOTALL)


@dataclass(frozen=True)
class VoiceProfile:
    """Profil voix : modèle, voix, format API, instructions et tempo final."""

    name: str
    model: str
    voice: str
    response_format: Literal["pcm", "mp3"]
    instructions: str | None = None
    tempo: float = 1.0


VOICE_PROFILES: dict[str, VoiceProfile] = {
    "voxtral_marie": VoiceProfile(
        name="voxtral_marie",
        model="mistralai/voxtral-mini-tts-2603",
        voice="fr_marie_neutral",
        response_format="mp3",
    ),
    "openai_shimmer_125x": VoiceProfile(
        name="openai_shimmer_125x",
        model="openai/gpt-4o-mini-tts-2025-12-15",
        voice="shimmer",
        response_format="pcm",
        instructions=OPENAI_INSTRUCTIONS,
        tempo=1.25,
    ),
}


@dataclass(frozen=True)
class Chunk:
    """Bloc de texte à synthétiser, indexé pour la persistance des artefacts."""

    index: int
    text: str
    word_count: int


class TtsTruncationError(RuntimeError):
    """Levée quand un chunk reste tronqué après MAX_RETRIES tentatives."""

    def __init__(self, chunk_index: int, voice: str) -> None:
        suggestion = (
            " Relancer avec --voice openai_shimmer_125x."
            if voice != "openai_shimmer_125x"
            else ""
        )
        super().__init__(
            f"Chunk {chunk_index} tronqué après {MAX_RETRIES} tentatives "
            f"en {voice}.{suggestion}"
        )
        self.chunk_index = chunk_index
        self.voice = voice


def _word_count(text: str) -> int:
    """Compte les mots en splitant sur les espaces (cf guide §3)."""
    return len(text.split())


def _strip_frontmatter(text: str) -> str:
    """Retire le bloc YAML frontmatter en tête (--- ... ---), s'il existe.

    Sans cela, le contenu YAML serait lu à voix haute par le TTS.
    """
    return FRONTMATTER_RE.sub("", text, count=1)


def _extract_paragraphs(text: str) -> list[str]:
    """Découpe sur \\n\\n, ignore les blocs vides et les lignes de titres résiduels."""
    text = _strip_frontmatter(text)
    paragraphs: list[str] = []
    for block in re.split(r"\n\s*\n", text.strip()):
        kept_lines = [
            line for line in block.splitlines() if not HEADING_RE.match(line.strip())
        ]
        joined = "\n".join(kept_lines).strip()
        if joined:
            paragraphs.append(joined)
    return paragraphs


def chunk_markdown(text: str) -> list[Chunk]:
    """Pack les paragraphes en chunks ≤ TARGET_MAX_WORDS, sans casser un paragraphe.

    Greedy : on accumule tant que l'ajout du prochain paragraphe ne dépasse pas la
    cible. Un paragraphe seul plus long que TARGET_MAX_WORDS part dans son propre
    chunk (pas de re-split en milieu de paragraphe : le podcast-formatter doit
    avoir produit des paragraphes ≤ 400 mots).
    """
    paragraphs = _extract_paragraphs(text)
    chunks_text: list[str] = []
    buffer: list[str] = []
    buffer_words = 0

    for paragraph in paragraphs:
        para_words = _word_count(paragraph)
        if buffer and buffer_words + para_words > TARGET_MAX_WORDS:
            chunks_text.append("\n\n".join(buffer))
            buffer, buffer_words = [], 0
        buffer.append(paragraph)
        buffer_words += para_words

    if buffer:
        chunks_text.append("\n\n".join(buffer))

    return [
        Chunk(index=i, text=t, word_count=_word_count(t))
        for i, t in enumerate(chunks_text)
    ]


def _write_wav(int16_bytes: bytes, path: Path) -> None:
    """Wrap des bytes int16 mono PCM_SAMPLE_RATE Hz en WAV."""
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(PCM_SAMPLE_RATE)
        wav.writeframes(int16_bytes)


def _run_ffmpeg(args: list[str]) -> None:
    """Exécute ffmpeg en silencieux ; remonte le stderr en cas d'échec."""
    try:
        subprocess.run(args, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.decode("utf-8", errors="replace") if exc.stderr else ""
        raise RuntimeError(f"ffmpeg a échoué : {stderr}") from exc


def _ffmpeg_wav_to_mp3(src_wav: Path, dst_mp3: Path, tempo: float) -> None:
    """Convertit un WAV en MP3 ; applique atempo si tempo != 1.0."""
    args = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src_wav)]
    if tempo != 1.0:
        args += ["-filter:a", f"atempo={tempo:g}"]
    args += ["-codec:a", "libmp3lame", "-b:a", "128k", str(dst_mp3)]
    _run_ffmpeg(args)


def synthesize_chunk(
    client: OpenAI, chunk: Chunk, profile: VoiceProfile, out_path: Path
) -> None:
    """Synthétise un chunk en MP3 à `out_path` selon le profil voix.

    Voxtral : MP3 direct depuis l'API.
    OpenAI shimmer x1.25 : PCM int16 24 kHz → WAV → ffmpeg atempo=1.25 → MP3.
    """
    extra_body: dict[str, object] | None = (
        {"instructions": profile.instructions} if profile.instructions else None
    )
    response = client.audio.speech.create(
        model=profile.model,
        input=chunk.text,
        voice=profile.voice,
        response_format=profile.response_format,
        extra_body=extra_body,
    )
    raw = response.read()

    if profile.response_format == "mp3" and profile.tempo == 1.0:
        out_path.write_bytes(raw)
        return

    if profile.response_format == "pcm":
        wav_path = out_path.with_suffix(".wav")
        _write_wav(raw, wav_path)
        try:
            _ffmpeg_wav_to_mp3(wav_path, out_path, tempo=profile.tempo)
        finally:
            wav_path.unlink(missing_ok=True)
        return

    # MP3 + tempo (cas non utilisé aujourd'hui mais cohérent).
    raw_path = out_path.with_suffix(".raw.mp3")
    raw_path.write_bytes(raw)
    try:
        _ffmpeg_wav_to_mp3(raw_path, out_path, tempo=profile.tempo)
    finally:
        raw_path.unlink(missing_ok=True)


def is_truncated(audio_path: Path) -> bool:
    """Détecte une troncature par analyse RMS du dernier silence et de l'amplitude finale.

    Décode l'audio (MP3 ou WAV) en PCM int16 mono via ffmpeg. Tronqué = coupe
    brutale = les DEUX signaux présents :
    - silence final < MIN_TRAILING_SILENCE_MS (pas de respiration finale)
    - amplitude des 50 dernières ms ≥ MAX_FINAL_AMPLITUDE_PCT du max
      (signal coupé en plein volume).

    Un silence court seul (ex : Voxtral fr_marie qui clôt à ~187 ms) avec une
    amplitude finale quasi-nulle n'est pas une troncature.
    """
    pcm = subprocess.run(
        [
            "ffmpeg", "-loglevel", "error", "-i", str(audio_path),
            "-f", "s16le", "-ac", "1", "-ar", str(PCM_SAMPLE_RATE), "-",
        ],
        check=True,
        capture_output=True,
    ).stdout
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32)
    if samples.size < PCM_SAMPLE_RATE // 2:
        return True

    window_size = PCM_SAMPLE_RATE * RMS_WINDOW_MS // 1000
    n_full = (len(samples) // window_size) * window_size
    windows = samples[:n_full].reshape(-1, window_size)
    rms = np.sqrt(np.mean(windows**2, axis=1))
    rms_max = float(rms.max()) if rms.max() > 0 else 1.0
    threshold = rms_max * SILENCE_THRESHOLD_RATIO

    above = np.where(rms > threshold)[0]
    last_audible_window = int(above[-1]) if len(above) > 0 else 0
    speech_end_s = (last_audible_window + 1) * RMS_WINDOW_MS / 1000
    duration_s = len(samples) / PCM_SAMPLE_RATE
    trailing_silence_ms = (duration_s - speech_end_s) * 1000

    tail_n = PCM_SAMPLE_RATE * 50 // 1000
    tail_max = float(np.abs(samples[-tail_n:]).max())
    sample_max = float(np.abs(samples).max()) or 1.0
    final_amplitude_pct = 100.0 * tail_max / sample_max

    return (
        trailing_silence_ms < MIN_TRAILING_SILENCE_MS
        and final_amplitude_pct >= MAX_FINAL_AMPLITUDE_PCT
    )


def concat_mp3(chunk_paths: list[Path], out_path: Path) -> None:
    """Concatène les chunks MP3 via le concat demuxer ffmpeg (zéro réencodage)."""
    list_file = out_path.parent / ".concat.txt"
    list_file.write_text(
        "\n".join(f"file '{p.resolve().as_posix()}'" for p in chunk_paths) + "\n",
        encoding="utf-8",
    )
    try:
        _run_ffmpeg([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy", str(out_path),
        ])
    finally:
        list_file.unlink(missing_ok=True)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", required=True, type=Path,
        help="Markdown podcast-ready (produit par podcast-formatter).",
    )
    parser.add_argument(
        "--output", required=True, type=Path,
        help="Chemin du MP3 final.",
    )
    parser.add_argument(
        "--voice", choices=sorted(VOICE_PROFILES), default="voxtral_marie",
        help="Profil voix (défaut: voxtral_marie).",
    )
    parser.add_argument(
        "--chunks-dir", type=Path, default=None,
        help="Dossier des chunks (défaut: <output_parent>/chunks/).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Orchestre chunking, synthèse, retry et concat. Retourne un exit code."""
    args = _parse_args(argv)

    if not shutil.which("ffmpeg"):
        print("ERROR: ffmpeg introuvable dans le PATH.", file=sys.stderr)
        return 1

    load_dotenv()
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        print("ERROR: OPENROUTER_API_KEY manquante dans .env.", file=sys.stderr)
        return 1

    profile = VOICE_PROFILES[args.voice]
    text = args.input.read_text(encoding="utf-8")
    chunks = chunk_markdown(text)
    if not chunks:
        print("ERROR: aucun contenu à synthétiser.", file=sys.stderr)
        return 1

    chunks_dir: Path = args.chunks_dir or args.output.parent / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    total_words = sum(c.word_count for c in chunks)
    oversized = [c for c in chunks if c.word_count > HARD_MAX_WORDS]
    print(
        f"Voix    : {profile.name} ({profile.model} / {profile.voice})\n"
        f"Chunks  : {len(chunks)} (total {total_words} mots)\n"
        f"Sortie  : {args.output}\n"
    )
    if oversized:
        print(
            f"WARN: {len(oversized)} chunk(s) > {HARD_MAX_WORDS} mots "
            "(le podcast-formatter devrait limiter à 400 mots/paragraphe).",
            file=sys.stderr,
        )

    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=api_key)
    chunk_paths: list[Path] = []

    for chunk in chunks:
        chunk_path = chunks_dir / f"chunk_{chunk.index:03d}.mp3"
        if chunk_path.exists() and not is_truncated(chunk_path):
            print(
                f"[{chunk.index + 1}/{len(chunks)}] reuse {chunk_path.name} "
                f"({chunk.word_count} mots)"
            )
            chunk_paths.append(chunk_path)
            continue

        for attempt in range(1, MAX_RETRIES + 1):
            print(
                f"[{chunk.index + 1}/{len(chunks)}] synth {chunk.word_count} mots "
                f"({attempt}/{MAX_RETRIES})...",
                flush=True,
            )
            synthesize_chunk(client, chunk, profile, chunk_path)
            if not is_truncated(chunk_path):
                print(f"        OK -> {chunk_path.name}")
                break
            print("        WARN: troncature détectée, retry.")
        else:
            raise TtsTruncationError(chunk.index, profile.name)

        chunk_paths.append(chunk_path)

    print(f"\nConcaténation -> {args.output}")
    concat_mp3(chunk_paths, args.output)
    size_mb = args.output.stat().st_size / 1024 / 1024
    print(f"OK ({size_mb:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
