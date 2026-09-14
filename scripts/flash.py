"""Flash the board and then prove it worked.

A thin front end for stm32_msi.flashing, which the desktop application also uses, so the
command line and the Flash button cannot drift apart.

    python scripts/flash.py --port COM4
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "desktop" / "src"))

from stm32_msi import flashing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="CDC port to verify on, for example COM4")
    parser.add_argument(
        "--image", type=Path, default=None, help="defaults to the built image"
    )
    parser.add_argument(
        "--programmer", default=None, help="path to STM32_Programmer_CLI"
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="write only; leaves you without evidence the image runs",
    )
    args = parser.parse_args()

    image = args.image or flashing.bundled_image()
    programmer = args.programmer or flashing.find_programmer()
    print(f"  image      {image}")
    print(f"  programmer {programmer}")

    ok, detail = flashing.run(
        image=image,
        port=None if args.no_verify else args.port,
        programmer=programmer,
    )
    print(f"  result     {'ok' if ok else 'FAILED'}: {detail}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
