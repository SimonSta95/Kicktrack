from __future__ import annotations

import argparse
import os
import shutil
from pathlib import Path

SUPPORTED = {".png", ".webp", ".jpg", ".jpeg"}


def default_cache_dir() -> Path:
    if os.name == "nt":
        root = Path(os.getenv("APPDATA", Path.home()))
    else:
        root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return root / "KickTrack" / "player_portraits"


def main() -> int:
    parser = argparse.ArgumentParser(description="Copy the local KickTrack portrait cache into assets/portraits for a release build.")
    parser.add_argument("--source", type=Path, default=default_cache_dir(), help="Portrait cache directory")
    parser.add_argument("--target", type=Path, default=Path("assets") / "portraits", help="Bundled portrait target")
    parser.add_argument("--no-clean", action="store_true", help="Keep existing images in the target")
    args = parser.parse_args()

    source = args.source.expanduser().resolve()
    target = args.target.expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    if not args.no_clean:
        for item in target.iterdir():
            if item.is_file() and item.suffix.lower() in SUPPORTED:
                item.unlink()

    if not source.exists():
        print(f"Kein Portrait-Cache gefunden: {source}")
        print("Der Build kann trotzdem erstellt werden, enthält dann aber keine Spielerportraits.")
        return 0

    copied = 0
    skipped = 0
    for item in source.iterdir():
        if not item.is_file() or item.suffix.lower() not in SUPPORTED:
            skipped += 1
            continue
        shutil.copy2(item, target / item.name)
        copied += 1

    print(f"Portraits für Build vorbereitet: {copied} kopiert -> {target}")
    if skipped:
        print(f"Ignorierte Dateien: {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
