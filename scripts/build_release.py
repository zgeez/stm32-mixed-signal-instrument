"""Build what a user actually downloads.

The headline artifact is one Windows executable that carries its own interpreter and the
firmware image, so a student on a lab machine downloads a single file, runs it, and can
flash the board from inside it. A wheel and an sdist are built too, for anyone who would
rather install it as a Python package, and the firmware image is staged on its own for
anyone flashing from the command line.

    python -m pip install ./desktop[release]
    python scripts/build_release.py
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parent.parent
DESKTOP = REPO / "desktop"
DIST = REPO / "dist"
FIRMWARE = REPO / "firmware" / "build" / "Release" / "firmware.elf"
RESOURCES = DESKTOP / "src" / "stm32_msi" / "resources"


def version() -> str:
    with (DESKTOP / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def run(command: list[str], cwd: Path) -> bool:
    print(f"  $ {' '.join(command[:3])} ...")
    done = subprocess.run(command, cwd=cwd, check=False)
    return done.returncode == 0


def build_wheel() -> bool:
    return run([sys.executable, "-m", "build", "--outdir", str(DIST)], DESKTOP)


def build_application(name: str) -> bool:
    """Freeze the GUI into one executable that carries its own interpreter and firmware.

    One file rather than one folder: a single download that runs is worth more to someone
    on a lab machine than a faster start. The bundle does unpack itself to a temporary
    directory on every launch, but that measured 1.7 s to a visible window, which is a
    price worth paying for not having to explain a folder.

    The firmware image goes inside it, so the application can flash the board without the
    user having to find a matching .elf.
    """
    work = DIST / "pyinstaller"
    work.mkdir(parents=True, exist_ok=True)
    # Freeze a launcher rather than gui.py itself. Pointing PyInstaller at the module runs
    # it as __main__ with no package, and its relative imports fail on the first launch.
    launcher = work / "stm32_msi_launcher.py"
    launcher.write_text(
        '"""Entry point for the frozen application."""\n\n'
        "from stm32_msi.gui import main\n\n"
        "raise SystemExit(main())\n",
        encoding="utf-8",
    )
    built = run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--windowed",
            "--onefile",
            "--name",
            name,
            "--distpath",
            str(DIST),
            "--workpath",
            str(work),
            "--specpath",
            str(work),
            # pyqtgraph reaches for its optional backends at import time; excluding the
            # ones that are not installed keeps the bundle from carrying half of Qt twice.
            "--exclude-module",
            "PyQt5",
            "--exclude-module",
            "PyQt6",
            "--exclude-module",
            "PySide2",
            "--exclude-module",
            "matplotlib",
            "--exclude-module",
            "tkinter",
            "--paths",
            str(DESKTOP / "src"),
            "--icon",
            str(RESOURCES / "icon.ico"),
            # The window and taskbar icon, kept at the same relative path the package uses
            # so one lookup works from source and from a frozen build alike.
            "--add-data",
            f"{RESOURCES}{os.pathsep}resources",
            # Carried inside the executable and unpacked beside the interpreter at run
            # time, which is where flashing.bundled_image() looks for it.
            "--add-data",
            f"{FIRMWARE}{os.pathsep}.",
            str(launcher),
        ],
        REPO,
    )
    # The work and spec directories are scaffolding. Leaving them in dist/ makes it
    # unclear which folders are the release.
    shutil.rmtree(work, ignore_errors=True)
    return built


def stage_firmware(release: str) -> bool:
    if not FIRMWARE.exists():
        print(f"  no firmware at {FIRMWARE}; build it first")
        return False
    target = DIST / "firmware"
    target.mkdir(parents=True, exist_ok=True)
    shutil.copy2(FIRMWARE, target / f"stm32-msi-{release}.elf")
    (target / "README.txt").write_text(
        "Flash this image with STM32CubeProgrammer connected over ST-LINK:\n\n"
        "    python scripts/flash.py --port COM4 --image firmware/"
        f"stm32-msi-{release}.elf\n\n"
        "The script verifies the write and then reconnects over the USB CDC port to\n"
        "confirm the board answers and reports a matching version. Without --port it\n"
        "writes the image but cannot tell you whether it runs.\n",
        encoding="utf-8",
    )
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Each step can be skipped because a release is assembled on more than one machine:
    # the frozen application only builds on Windows, the rest is happiest on Linux.
    parser.add_argument("--skip-wheel", action="store_true", help="no wheel or sdist")
    parser.add_argument(
        "--skip-application", action="store_true", help="no frozen application"
    )
    parser.add_argument(
        "--skip-firmware", action="store_true", help="do not stage the image"
    )
    parser.add_argument("--clean", action="store_true", help="empty dist first")
    args = parser.parse_args()

    release = version()
    if args.clean and DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True, exist_ok=True)
    print(f"  version {release}")

    steps = []
    if not args.skip_wheel:
        steps.append(("wheel and sdist", build_wheel))
    if not args.skip_application:
        steps.append(
            ("windows application", lambda: build_application(f"stm32-msi-{release}"))
        )
    if not args.skip_firmware:
        steps.append(("firmware image", lambda: stage_firmware(release)))

    failed = []
    for name, step in steps:
        print(f"\n{name}")
        if not step():
            failed.append(name)
            print(f"  {name}: FAILED")

    print("\ncontents of dist/")
    for item in sorted(DIST.iterdir()):
        kind = "dir " if item.is_dir() else f"{item.stat().st_size // 1024:>6} KiB"
        print(f"  {kind}  {item.name}")
    if failed:
        print("\nfailed: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
