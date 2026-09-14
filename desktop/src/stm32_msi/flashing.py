"""Write firmware to the board and prove it came back up.

Programming and checking belong together. The programmer reports that bytes were written,
which is not the same as the board running them, so this reconnects over the CDC port
afterwards and asks the device what it is.

STM32CubeProgrammer does the writing. It is ST's tool and cannot be redistributed here, so
this locates an installed copy rather than carrying one. Without it there is nothing to
drive the ST-LINK on the board.
"""

import glob
import subprocess
import sys
import time
from pathlib import Path

from .instrument import MINIMUM_FIRMWARE, Instrument
from .transport import Transport

IMAGE_NAME = "firmware.elf"
# Where to send someone who does not have it. ST's tool, ST's download page.
PROGRAMMER_URL = "https://www.st.com/en/development-tools/stm32cubeprog.html"
SEARCH = (
    r"C:\Users\*\AppData\Local\stm32cube\bundles\programmer\*\bin\STM32_Programmer_CLI.exe",
    (
        r"C:\Program Files\STMicroelectronics\STM32Cube\STM32CubeProgrammer"
        r"\bin\STM32_Programmer_CLI.exe"
    ),
    r"C:\ST\STM32CubeIDE*\STM32CubeIDE\plugins\*\tools\bin\STM32_Programmer_CLI.exe",
    "/usr/local/STMicroelectronics/STM32Cube/STM32CubeProgrammer/bin/STM32_Programmer_CLI",
)


def find_programmer() -> str | None:
    """The newest STM32_Programmer_CLI in the usual places, or None."""
    for pattern in SEARCH:
        matches = sorted(glob.glob(pattern))
        if matches:
            return matches[-1]
    return None


def bundled_image() -> Path | None:
    """The image shipped beside the application, or built in this tree.

    A frozen build unpacks its data next to the interpreter it carries, which is where
    PyInstaller puts anything added with --add-data.
    """
    if getattr(sys, "frozen", False):
        candidate = Path(getattr(sys, "_MEIPASS", ".")) / IMAGE_NAME
        return candidate if candidate.exists() else None
    candidate = Path(__file__).resolve().parents[3] / "firmware" / "build" / "Release" / IMAGE_NAME
    return candidate if candidate.exists() else None


def write(programmer: str, image: Path) -> tuple[bool, str]:
    """Write and verify. The verification comes from -v, not from the exit code."""
    try:
        done = subprocess.run(
            [programmer, "-c", "port=SWD", "mode=UR", "-w", str(image), "-v", "-rst"],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"could not run the programmer: {exc}"
    output = done.stdout + done.stderr
    if done.returncode != 0:
        lines = [line for line in output.strip().splitlines() if line.strip()]
        return False, lines[-1] if lines else "the programmer failed"
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


def run(
    image: Path | None = None, port: str | None = None, programmer: str | None = None
) -> tuple[bool, str]:
    """Flash, then verify if a port was given. One call, because a write on its own is
    not evidence that the image runs."""
    image = image or bundled_image()
    if image is None:
        return False, "no firmware image was found to flash"
    if not Path(image).exists():
        return False, f"no image at {image}"
    programmer = programmer or find_programmer()
    if programmer is None:
        return False, (
            "STM32CubeProgrammer was not found. It is what drives the ST-LINK on the "
            f"board; install it from {PROGRAMMER_URL}"
        )
    written, detail = write(programmer, Path(image))
    if not written:
        return False, detail
    if not port:
        return True, "written and verified, but not confirmed to run without a port"
    return identify(port)
