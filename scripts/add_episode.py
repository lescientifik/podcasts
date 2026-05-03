#!/usr/bin/env python3
"""Ajoute un nouvel épisode au feed RSS et copie les assets dans episodes/.

Usage :
    python3 scripts/add_episode.py \\
        --mp3 PATH \\
        --cover PATH \\
        --title "Titre de l'épisode" \\
        --description "Description courte" \\
        [--notes PATH.md] \\
        [--date "RFC 822"]

Sortie : imprime "epNNN" sur la dernière ligne stdout (numéro assigné).
Le récap détaillé va sur stderr.

Dépendances : stdlib + ffprobe (subprocess).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

NS_ITUNES = "http://www.itunes.com/dtds/podcast-1.0.dtd"
NS_ATOM = "http://www.w3.org/2005/Atom"

ET.register_namespace("itunes", NS_ITUNES)
ET.register_namespace("atom", NS_ATOM)

REPO_ROOT = Path(__file__).resolve().parent.parent
EPISODES_DIR = REPO_ROOT / "episodes"
FEED_PATH = REPO_ROOT / "feed.xml"
SITE_BASE_URL = "https://lescientifik.github.io/podcasts"

EP_RE = re.compile(r"^ep(\d{3})(?:\.transcript)?\.(mp3|jpg|jpeg|png|webp|md)$")


def next_episode_number() -> int:
    """Scanne episodes/ et retourne le prochain numéro libre (1-indexé)."""
    if not EPISODES_DIR.exists():
        return 1
    used: set[int] = set()
    for p in EPISODES_DIR.iterdir():
        m = EP_RE.match(p.name)
        if m:
            used.add(int(m.group(1)))
    n = 1
    while n in used:
        n += 1
    return n


def ffprobe_duration_seconds(mp3: Path) -> float:
    """Retourne la durée du MP3 en secondes via ffprobe."""
    args = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(mp3),
    ]
    try:
        out = subprocess.check_output(args, text=True).strip()
    except FileNotFoundError as exc:
        raise RuntimeError("ffprobe introuvable. Installer ffmpeg.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ffprobe a échoué : {exc}") from exc
    return float(out)


def format_duration_hhmmss(seconds: float) -> str:
    """Formate des secondes en HH:MM:SS pour <itunes:duration>."""
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def parse_pub_date(arg: str | None) -> datetime:
    """Parse l'arg --date (RFC 822) ou retourne maintenant (UTC)."""
    if arg is None:
        return datetime.now(timezone.utc)
    try:
        return parsedate_to_datetime(arg)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"--date invalide (RFC 822 attendu) : {arg}") from exc


def copy_episode_assets(
    ep: int,
    mp3: Path,
    cover: Path,
    notes: Path | None,
    transcript: Path | None,
) -> tuple[str, str, str | None, str | None]:
    """Copie MP3, cover, notes, transcript vers episodes/ avec naming epNNN.*."""
    EPISODES_DIR.mkdir(parents=True, exist_ok=True)
    base = f"ep{ep:03d}"

    mp3_dst = EPISODES_DIR / f"{base}.mp3"
    shutil.copy(mp3, mp3_dst)

    cover_ext = cover.suffix.lower().lstrip(".")
    if cover_ext == "jpeg":
        cover_ext = "jpg"
    if cover_ext not in {"png", "jpg", "webp"}:
        raise SystemExit(f"Format de cover non supporté : .{cover_ext}")
    cover_dst = EPISODES_DIR / f"{base}.{cover_ext}"
    shutil.copy(cover, cover_dst)

    notes_dst_name: str | None = None
    if notes is not None:
        if not notes.exists():
            raise SystemExit(f"Notes introuvables : {notes}")
        notes_dst = EPISODES_DIR / f"{base}.md"
        shutil.copy(notes, notes_dst)
        notes_dst_name = notes_dst.name

    transcript_dst_name: str | None = None
    if transcript is not None:
        if not transcript.exists():
            raise SystemExit(f"Transcript introuvable : {transcript}")
        transcript_dst = EPISODES_DIR / f"{base}.transcript.md"
        shutil.copy(transcript, transcript_dst)
        transcript_dst_name = transcript_dst.name

    return mp3_dst.name, cover_dst.name, notes_dst_name, transcript_dst_name


def itunes(name: str) -> str:
    """Retourne le tag qualifié `{ns}name` pour le namespace iTunes."""
    return f"{{{NS_ITUNES}}}{name}"


def build_item(
    ep: int,
    title: str,
    description: str,
    pub_date: datetime,
    mp3_name: str,
    mp3_size: int,
    duration_str: str,
    cover_name: str,
) -> ET.Element:
    """Construit l'élément <item> RSS pour un épisode."""
    item = ET.Element("item")
    ET.SubElement(item, "title").text = title
    ET.SubElement(item, "description").text = description
    ET.SubElement(item, "pubDate").text = format_datetime(pub_date)
    ET.SubElement(item, "guid", attrib={"isPermaLink": "false"}).text = f"ep{ep:03d}"
    ET.SubElement(
        item, "enclosure",
        attrib={
            "url": f"{SITE_BASE_URL}/episodes/{mp3_name}",
            "type": "audio/mpeg",
            "length": str(mp3_size),
        },
    )
    ET.SubElement(item, itunes("duration")).text = duration_str
    ET.SubElement(
        item, itunes("image"),
        attrib={"href": f"{SITE_BASE_URL}/episodes/{cover_name}"},
    )
    ET.SubElement(item, itunes("explicit")).text = "false"
    return item


def _item_pub_dt(item: ET.Element) -> datetime:
    """Retourne la pubDate d'un item ; epoch 0 si absente/invalide (item poussé en fin)."""
    p = item.find("pubDate")
    text = p.text if p is not None else None
    if not text:
        return datetime.fromtimestamp(0, timezone.utc)
    try:
        return parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return datetime.fromtimestamp(0, timezone.utc)


def insert_and_sort_by_date_desc(channel: ET.Element, new_item: ET.Element) -> None:
    """Ajoute `new_item` au channel et trie tous les items par pubDate descendante."""
    channel.append(new_item)
    items = list(channel.findall("item"))
    for it in items:
        channel.remove(it)
    items.sort(key=_item_pub_dt, reverse=True)
    for it in items:
        channel.append(it)


def write_feed(tree: ET.ElementTree) -> None:
    """Réindente et écrit le feed avec déclaration XML."""
    ET.indent(tree, space="  ")
    tree.write(FEED_PATH, encoding="utf-8", xml_declaration=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mp3", type=Path, required=True)
    parser.add_argument("--cover", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", required=True)
    parser.add_argument(
        "--notes", type=Path, default=None,
        help="Fichier markdown (research.md) à copier sous epNNN.md",
    )
    parser.add_argument(
        "--transcript", type=Path, default=None,
        help="Script TTS (podcast-script.md) à copier sous epNNN.transcript.md",
    )
    parser.add_argument(
        "--date", default=None,
        help="Date RFC 822. Défaut : maintenant (UTC).",
    )
    args = parser.parse_args(argv)

    if not args.mp3.exists():
        raise SystemExit(f"MP3 introuvable : {args.mp3}")
    if not args.cover.exists():
        raise SystemExit(f"Cover introuvable : {args.cover}")
    if not FEED_PATH.exists():
        raise SystemExit(f"feed.xml introuvable : {FEED_PATH}")

    pub_date = parse_pub_date(args.date)
    duration_s = ffprobe_duration_seconds(args.mp3)
    duration_str = format_duration_hhmmss(duration_s)
    ep = next_episode_number()

    mp3_name, cover_name, notes_name, transcript_name = copy_episode_assets(
        ep, args.mp3, args.cover, args.notes, args.transcript,
    )
    mp3_size = (EPISODES_DIR / mp3_name).stat().st_size

    tree = ET.parse(FEED_PATH)
    channel = tree.getroot().find("channel")
    if channel is None:
        raise SystemExit("feed.xml : <channel> introuvable")
    item = build_item(
        ep, args.title, args.description, pub_date,
        mp3_name, mp3_size, duration_str, cover_name,
    )
    insert_and_sort_by_date_desc(channel, item)
    write_feed(tree)

    # Récap sur stderr — stdout est réservé au numéro pour parsing par le caller.
    extras = ""
    if notes_name:
        extras += f", {notes_name}"
    if transcript_name:
        extras += f", {transcript_name}"
    print(f"  + episode    : ep{ep:03d}", file=sys.stderr)
    print(f"  + title      : {args.title}", file=sys.stderr)
    print(f"  + duration   : {duration_str}", file=sys.stderr)
    print(f"  + size       : {mp3_size:,} bytes", file=sys.stderr)
    print(f"  + pub date   : {format_datetime(pub_date)}", file=sys.stderr)
    print(f"  + assets     : {mp3_name}, {cover_name}{extras}", file=sys.stderr)
    print(f"  + feed.xml   : updated", file=sys.stderr)
    print(file=sys.stderr)
    print(
        f'Prochaine étape : bash scripts/publish.sh "ep{ep:03d}" "{args.title}"',
        file=sys.stderr,
    )

    print(f"ep{ep:03d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
