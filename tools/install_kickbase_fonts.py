from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FONT_DIR = PROJECT_ROOT / "assets" / "fonts"

VOLKSANS_NAMES = {
    "KB_volksans_Light.otf",
    "KB_volksans_Regular.otf",
    "KB_volksans_Normal.otf",
    "KB_volksans_SemiBold.otf",
    "KB_volksans_Bold.otf",
    "KB_volksans_Black.otf",
}

# The variable face cleanly exposes the common "KB Pitch" family to Qt and is
# sufficient for our headline use. Static Still/Run/Sprint are copied as well so
# they remain available for later design work.
PITCH_NAMES = {
    "KBPitchVF.ttf",
    "KBPitch-Still.otf",
    "KBPitch-Run.otf",
    "KBPitch-Sprint.otf",
}


def _extract_selected(zip_path: Path, names: set[str], target: Path) -> list[Path]:
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir() and Path(m.filename).name in names]
        found_names = {Path(m.filename).name for m in members}
        missing = names - found_names
        if missing:
            raise SystemExit(f"In {zip_path.name} fehlen erwartete Dateien: {', '.join(sorted(missing))}")

        # Archives can contain duplicate Pitch TTFs in Web/Desktop. One copy per
        # filename is enough.
        by_name = {}
        for member in members:
            name = Path(member.filename).name
            # Prefer Desktop paths when both exist.
            current = by_name.get(name)
            if current is None or ("Desktop" in member.filename and "Desktop" not in current.filename):
                by_name[name] = member

        for name, member in sorted(by_name.items()):
            dest = target / name
            with archive.open(member) as src, dest.open("wb") as out:
                shutil.copyfileobj(src, out)
            copied.append(dest)
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(description="Install locally obtained Kickbase CI fonts into KickTrack.")
    parser.add_argument("volksans_zip", type=Path, help="Path to KB_Volksans.zip")
    parser.add_argument("pitch_zip", type=Path, help="Path to KB_Pitch.zip")
    args = parser.parse_args()

    if not args.volksans_zip.is_file():
        raise SystemExit(f"Nicht gefunden: {args.volksans_zip}")
    if not args.pitch_zip.is_file():
        raise SystemExit(f"Nicht gefunden: {args.pitch_zip}")

    volks = _extract_selected(args.volksans_zip, VOLKSANS_NAMES, FONT_DIR / "KB_Volksans")
    pitch = _extract_selected(args.pitch_zip, PITCH_NAMES, FONT_DIR / "KB_Pitch")

    print(f"Installiert nach: {FONT_DIR}")
    for path in [*volks, *pitch]:
        print(" -", path.relative_to(PROJECT_ROOT))
    print("\nBeim nächsten App-Start zeigt das Terminal die tatsächlich aktiven Font-Familien an.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
