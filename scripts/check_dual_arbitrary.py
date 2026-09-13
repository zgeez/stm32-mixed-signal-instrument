"""Board regression: dual arbitrary playback through repeated starts and USB load."""

import argparse
import time

from stm32_msi.instrument import Instrument
from stm32_msi.transport import Transport


def check(instrument, baseline):
    for channel in range(2):
        status = instrument.channel_status(channel)
        counters = (status.underruns, status.dma_errors, status.refill_misses)
        if status.state != 2 or counters != baseline[channel]:
            raise RuntimeError(f"Playback failed: {status}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("port")
    args = parser.parse_args()
    with Transport(args.port) as transport:
        instrument = Instrument(transport)
        instrument.stop()
        baseline = []
        for channel in range(2):
            status = instrument.channel_status(channel)
            baseline.append((status.underruns, status.dma_errors, status.refill_misses))
        try:
            for length in (2, 17, 256):
                for channel in range(2):
                    table = [
                        (index * 997 + channel * 521) % 4096 for index in range(length)
                    ]
                    instrument.upload_arbitrary(channel, table)
                for frequency in (1, 1000, 20000):
                    for channel in range(2):
                        instrument.configure_channel(
                            channel, "arbitrary", frequency, 75, 50, 0
                        )
                    for _ in range(10):
                        instrument.start()
                        time.sleep(0.1)
                        check(instrument, baseline)
                        instrument.stop()
                    print(
                        f"Passed: {length} entries, {frequency} Hz, 10 starts",
                        flush=True,
                    )
            instrument.start()
            time.sleep(3)
            check(instrument, baseline)
            deadline = time.monotonic() + 10
            polls = 0
            while time.monotonic() < deadline:
                check(instrument, baseline)
                polls += 1
            print(f"Passed: 3 s silent, 10 s USB load ({polls} paired status polls)")
        finally:
            instrument.stop()


if __name__ == "__main__":
    main()
