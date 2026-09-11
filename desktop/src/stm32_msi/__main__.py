"""Command-line device control."""

import argparse
import json
from dataclasses import asdict

from .instrument import WAVEFORMS, Instrument
from .transport import Transport


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="STM32 Mixed-Signal Instrument")
    parser.add_argument("--port", required=True, help="CDC serial port, e.g. COM5")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("hello", "capabilities", "status", "start", "stop"):
        sub.add_parser(name)
    config = sub.add_parser("configure")
    config.add_argument("waveform", choices=WAVEFORMS)
    config.add_argument("frequency", type=int)
    args = parser.parse_args(argv)
    try:
        with Transport(args.port) as transport:
            device = Instrument(transport)
            if args.command == "configure":
                device.configure(args.waveform, args.frequency)
            elif args.command == "status":
                print(json.dumps(asdict(device.status())))
            else:
                result = getattr(device, args.command)()
                if result is not None:
                    print(json.dumps(result))
    except (OSError, RuntimeError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
