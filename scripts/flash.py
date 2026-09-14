"""Flash the board and then prove it worked.

Programming and checking are one step here on purpose. The programmer reports that bytes
were written, which is not the same as the board coming back up and answering: a verified
download still leaves you guessing whether the image runs. So this reconnects over the CDC
port afterwards and asks the device what it is.

Needs STM32CubeProgrammer. Pass --programmer if it is not in one of the usual places.
"""

import argparse
import glob
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop" / "src"))

from stm32_msi.instrument import MINIMUM_FIRMWARE, Instrument
from stm32_msi.transport import Transport

REPO = Path(__file__).resolve().parent.parent
DEFAULT_IMAGE = REPO / "firmware" / "build" / "Release" / "firmware.elf"
SEARCH = (
    r"C:\Users\*\AppData\Local\stm32cube\bundles\programmer\*\bin\STM32_Programmer_CLI.exe",
    (
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer"
        r"\bin\STM32_Programmer_CLI.exe"
    ),
    r"C:\ST\STM32CubeIDE*\STM32CubeIDE\plugins\*\tools\bin\STM32_Programmer_CLI.exe",
)


def find_programmer() -> str | None:
    for pattern in SEARCH:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return None


def flash(programmer: str, image: Path) -> tuple[bool, str]:
    """Write and verify the image. -v is what produces the verification, not the exit code."""
    done = subprocess.run(
        [programmer, "-c", "port=SWD", "mode=UR", "-w", str(image), "-v", "-rst"],
        capture_output=True,
        text=True,
        check=False,
    )
    output = done.stdout + done.stderr
    if done.returncode != 0:
        lines = output.strip().splitlines()
        return False, lines[-1] if lines else "programmer failed"
    if "Download verified successfully" not in output:
        return False, "the programmer did not report a verified download"
    return True, "written and verified"


def identify(port: str, attempts: int = 12) -> tuple[bool, str]:
    """Wait for the port to come back, then ask the board what it is."""
    last = "no reply"
    for _ in range(attempts):
        time.sleep(1.0)
        try:
            with Transport(port, 4.0) as transport:
                device = Instrument(transport)
                name = device.hello()
                if name != "STM32-MSI":
                    return False, f"a device answered, but called itself {name!r}"
                try:
                    version = device.firmware_version()
                except (OSError, RuntimeError, ValueError):
                    return False, "running, but too old to report a version"
                wanted = ".".join(str(part) for part in MINIMUM_FIRMWARE)
                if not version.supported:
                    return False, f"running {version}, older than the expected {wanted}"
                return True, f"running {version}"
        except (OSError, RuntimeError, ValueError) as exc:
            last = str(exc)
    return False, f"never answered after flashing: {last}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="CDC port to verify on, for example COM4")
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
    parser.add_argument(
        "--programmer", default=None, help="path to STM32_Programmer_CLI"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="write only; leaves you without evidence the image runs",
    )
    args = parser.parse_args()

    if not args.image.exists():
        print(f"No image at {args.image}. Build the firmware first.")
        return 2
    programmer = args.programmer or find_programmer()
    if programmer is None:
        print(
            "STM32_Programmer_CLI not found. Install STM32CubeProgrammer or pass --programmer."
        )
        return 2

    print(f"  image      {args.image}")
    print(f"  programmer {programmer}")
    written, detail = flash(programmer, args.image)
    print(f"  flash      {'ok' if written else 'FAILED'}: {detail}")
    if not written:
        return 1
    if args.no_verify:
        print("  verify     skipped")
        return 0
    if not args.port:
        print("  verify     skipped: pass --port to confirm the board answers")
        return 0
    ok, detail = identify(args.port)
    print(f"  verify     {'ok' if ok else 'FAILED'}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
