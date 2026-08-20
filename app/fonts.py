from __future__ import annotations

import hashlib
import os
import platform
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFontDatabase


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ASSET_FONT_DIR = PROJECT_ROOT / "assets" / "fonts"
FONT_PACKAGE_DIR = ASSET_FONT_DIR / "packages"
SUPPORTED_FONT_SUFFIXES = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}

# Official archive names. For private/local use you can keep the original ZIPs
# in assets/fonts/packages without installing anything into Windows.
PACKAGE_NAMES = ("KB_Volksans.zip", "KB_Pitch.zip")

BODY_FONT_CANDIDATES = (
    "KB volksans",
    "KB Volksans",
    "KB volksans Regular",
    "KB volksans Normal",
    "Source Sans 3",
    "Source Sans Pro",
    "Segoe UI",
    "Arial",
)

DISPLAY_FONT_CANDIDATES = (
    "KB Pitch",
    "KB Pitch Still",
    "KB Pitch Sprint",
    "KB Pitch Bold",
    "KB volksans",
    "KB Volksans",
    "Source Sans 3",
    "Source Sans Pro",
    "Segoe UI",
    "Arial",
)

# Only desktop faces that are useful to this application are extracted from the
# original packages. The archives themselves can stay in the private repo.
VOLKSANS_FILES = {
    "KB_volksans_Light.otf",
    "KB_volksans_Regular.otf",
    "KB_volksans_Normal.otf",
    "KB_volksans_SemiBold.otf",
    "KB_volksans_Bold.otf",
    "KB_volksans_Black.otf",
}
PITCH_FILES = {
    "KBPitchVF.ttf",
    "KBPitch-Still.otf",
    "KBPitch-Run.otf",
    "KBPitch-Sprint.otf",
}


@dataclass(frozen=True)
class FontLoadReport:
    loaded_files: tuple[str, ...]
    loaded_families: tuple[str, ...]
    failed_files: tuple[str, ...]
    package_files: tuple[str, ...]
    body_family: str
    display_family: str


def _normalise(value: str) -> str:
    return "".join(ch for ch in str(value).casefold() if ch.isalnum())


def _family_lookup() -> tuple[list[str], dict[str, str]]:
    families = list(QFontDatabase.families())
    exact = {_normalise(family): family for family in families}
    return families, exact


def _preferred(candidates: tuple[str, ...]) -> str:
    families, exact = _family_lookup()
    for candidate in candidates:
        matched = exact.get(_normalise(candidate))
        if matched:
            return matched
    for candidate in candidates:
        needle = _normalise(candidate)
        if not needle:
            continue
        for family in families:
            haystack = _normalise(family)
            if needle in haystack or haystack in needle:
                return family
    return "Sans Serif"


def body_font_family() -> str:
    return _preferred(BODY_FONT_CANDIDATES)


def display_font_family() -> str:
    return _preferred(DISPLAY_FONT_CANDIDATES)


def _runtime_font_dir() -> Path:
    """Writable cache for fonts extracted from bundled/private ZIP packages."""
    if platform.system() == "Windows":
        base = Path(os.getenv("LOCALAPPDATA") or os.getenv("APPDATA") or Path.home())
    else:
        base = Path(os.getenv("XDG_CACHE_HOME", Path.home() / ".cache"))
    path = base / "KickTrack" / "fonts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _package_candidates(name: str) -> list[Path]:
    """Places where a private repo may keep the original official font ZIPs."""
    return [
        FONT_PACKAGE_DIR / name,
        ASSET_FONT_DIR / name,
        PROJECT_ROOT / name,
    ]


def _find_package(name: str) -> Path | None:
    for candidate in _package_candidates(name):
        if candidate.is_file():
            return candidate
    return None


def _archive_fingerprint(path: Path) -> str:
    stat = path.stat()
    payload = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:16]


def _extract_selected(package: Path, wanted: set[str], target: Path) -> list[Path]:
    """Extract one copy of selected desktop faces from an official archive."""
    target.mkdir(parents=True, exist_ok=True)
    copied: list[Path] = []
    with zipfile.ZipFile(package) as archive:
        members = [
            member for member in archive.infolist()
            if not member.is_dir()
            and "__MACOSX" not in Path(member.filename).parts
            and Path(member.filename).name in wanted
        ]

        # Prefer Desktop/OTF or Desktop/VF when the archive contains duplicates.
        by_name: dict[str, zipfile.ZipInfo] = {}
        for member in members:
            name = Path(member.filename).name
            current = by_name.get(name)
            score = (
                3 if "/Desktop/" in f"/{member.filename}" else 0,
                2 if "/OTF/" in f"/{member.filename}" else 0,
                1 if "/VF/" in f"/{member.filename}" else 0,
            )
            current_score = (-1, -1, -1)
            if current is not None:
                current_score = (
                    3 if "/Desktop/" in f"/{current.filename}" else 0,
                    2 if "/OTF/" in f"/{current.filename}" else 0,
                    1 if "/VF/" in f"/{current.filename}" else 0,
                )
            if current is None or score > current_score:
                by_name[name] = member

        for name, member in sorted(by_name.items()):
            dest = target / name
            with archive.open(member) as source, dest.open("wb") as output:
                shutil.copyfileobj(source, output)
            copied.append(dest)
    return copied


def _prepare_package_fonts() -> tuple[list[Path], list[str]]:
    """Extract repo-shipped font ZIPs into a user-writable runtime cache.

    Nothing is installed system-wide. If the two ZIPs are committed to a private
    repository under ``assets/fonts/packages/``, cloning the repo is enough.
    """
    extracted: list[Path] = []
    packages_used: list[str] = []
    runtime = _runtime_font_dir()

    specs = (
        ("KB_Volksans.zip", VOLKSANS_FILES, "KB_Volksans"),
        ("KB_Pitch.zip", PITCH_FILES, "KB_Pitch"),
    )
    for package_name, wanted, group in specs:
        package = _find_package(package_name)
        if package is None:
            continue
        packages_used.append(str(package))
        target = runtime / group / _archive_fingerprint(package)
        marker = target / ".ready"
        if not marker.exists():
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            target.mkdir(parents=True, exist_ok=True)
            _extract_selected(package, wanted, target)
            marker.write_text("ok", encoding="utf-8")
        extracted.extend(
            path for path in target.iterdir()
            if path.is_file() and path.suffix.lower() in SUPPORTED_FONT_SUFFIXES
        )
    return extracted, packages_used


def _font_paths() -> tuple[list[Path], list[str]]:
    """Return directly unpacked fonts plus fonts prepared from private ZIPs."""
    ASSET_FONT_DIR.mkdir(parents=True, exist_ok=True)
    FONT_PACKAGE_DIR.mkdir(parents=True, exist_ok=True)

    direct = [
        path for path in ASSET_FONT_DIR.rglob("*")
        if path.is_file()
        and path.suffix.lower() in SUPPORTED_FONT_SUFFIXES
        and "__MACOSX" not in path.parts
        and "packages" not in path.parts
    ]
    packaged, packages_used = _prepare_package_fonts()
    paths = [*direct, *packaged]
    suffix_rank = {".otf": 0, ".ttf": 1, ".ttc": 2, ".woff2": 3, ".woff": 4}
    unique: dict[str, Path] = {}
    for path in paths:
        try:
            key = f"{path.name.casefold()}:{path.stat().st_size}"
        except OSError:
            continue
        unique.setdefault(key, path)
    return sorted(unique.values(), key=lambda p: (suffix_rank.get(p.suffix.lower(), 99), p.name.casefold())), packages_used


def load_local_fonts() -> FontLoadReport:
    """Register application-local fonts; never installs them into Windows."""
    paths, packages_used = _font_paths()
    loaded_files: list[str] = []
    loaded_families: list[str] = []
    failed_files: list[str] = []

    for path in paths:
        display_name = path.name
        font_id = QFontDatabase.addApplicationFont(str(path))
        if font_id < 0:
            failed_files.append(display_name)
            continue
        loaded_files.append(display_name)
        for family in QFontDatabase.applicationFontFamilies(font_id):
            if family not in loaded_families:
                loaded_families.append(family)

    return FontLoadReport(
        loaded_files=tuple(loaded_files),
        loaded_families=tuple(loaded_families),
        failed_files=tuple(failed_files),
        package_files=tuple(packages_used),
        body_family=body_font_family(),
        display_family=display_font_family(),
    )


def print_font_report(report: FontLoadReport) -> None:
    print("[KickTrack] Font setup")
    print(f"[KickTrack] UI font      : {report.body_family}")
    print(f"[KickTrack] Headline font: {report.display_family}")
    if report.package_files:
        print(f"[KickTrack] Font packages: {', '.join(report.package_files)}")
    else:
        print(f"[KickTrack] Font packages: none (expected in {FONT_PACKAGE_DIR})")
    if report.loaded_files:
        print(f"[KickTrack] Loaded files : {', '.join(report.loaded_files)}")
    else:
        print("[KickTrack] Loaded files : none")
    if report.loaded_families:
        print(f"[KickTrack] Font families: {', '.join(report.loaded_families)}")
    if report.failed_files:
        print(f"[KickTrack] WARNING could not load: {', '.join(report.failed_files)}")
