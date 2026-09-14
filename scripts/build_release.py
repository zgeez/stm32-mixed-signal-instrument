"""Build what a user actually downloads: a wheel, a Windows application, and the firmware.

Two ways in, because the audience has two situations. A machine with Python installed wants
the wheel. A lab machine where you cannot install Python wants an application that carries
its own interpreter, which is most of the size and the reason this is not just a wheel.

The firmware image is staged alongside rather than bundled in, so the same image can be
flashed with scripts/flash.py whichever way the application was installed.

    python -m pip install ./desktop[release]
    python scripts/build_release.py
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import tomllib

REPO = Path(__file__).resolve().parent.parent
DESKTOP = REPO / "desktop"
DIST = REPO / "dist"
FIRMWARE = REPO / "firmware" / "build" / "Release" / "firmware.elf"


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
    """Freeze the GUI entry point into a folder that carries its own interpreter.

    One folder rather than one file: a single exe unpacks itself on every launch, which is
    slow for a PySide6 application and confuses antivirus more often.
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
            str(launcher),
        ],
        REPO,
    )
    # The work and spec directories are scaffolding. Leaving them in dist/ makes it
    # unclear which folders are the release.
    shutil.rmtree(work, ignore_errors=True)
    if built:
        # A release asset is a file, so the folder has to become an archive before it can
        # be uploaded anywhere.
        shutil.make_archive(
            str(DIST / f"{name}-windows"), "zip", root_dir=DIST, base_dir=name
        )
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
