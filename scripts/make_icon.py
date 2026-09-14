"""Draw the application icon.

A sine over a square wave: the two halves of a mixed-signal instrument, in the same yellow
and blue the analog traces use, so the icon and the plots agree.

Each size is drawn rather than scaled from one large render. A waveform scaled down to
16 pixels turns to mush, whereas redrawing lets the stroke stay a sensible fraction of the
icon at every size.

    python scripts/make_icon.py
"""

import math
import struct
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QPointF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPen

REPO = Path(__file__).resolve().parent.parent
RESOURCES = REPO / "desktop" / "src" / "stm32_msi" / "resources"
SIZES = (16, 24, 32, 48, 64, 128, 256)

BACKGROUND = QColor("#1b1e24")
ANALOG = QColor("#f5c542")
DIGITAL = QColor("#4aa8ff")


def draw(size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    panel = QPainterPath()
    panel.addRoundedRect(0, 0, size, size, size * 0.22, size * 0.22)
    painter.fillPath(panel, BACKGROUND)

    stroke = max(1.0, size * 0.062)
    pen = QPen(ANALOG, stroke)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)

    left, right = size * 0.16, size * 0.84
    span = right - left
    # One full period, centred in the upper half.
    sine = QPainterPath()
    steps = max(12, size // 2)
    for step in range(steps + 1):
        x = left + span * step / steps
        y = size * 0.34 - math.sin(2 * math.pi * step / steps) * size * 0.15
        point = QPointF(x, y)
        sine.moveTo(point) if step == 0 else sine.lineTo(point)
    painter.drawPath(sine)

    # Two periods below it, so the two halves read as different kinds of signal.
    painter.setPen(QPen(DIGITAL, stroke, c=Qt.PenCapStyle.SquareCap))
    high, low = size * 0.60, size * 0.80
    square = QPainterPath()
    square.moveTo(left, low)
    quarter = span / 4
    level = low
    square.lineTo(left, high)
    level = high
    for index in range(1, 5):
        x = left + quarter * index
        square.lineTo(x, level)
        level = low if level == high else high
        square.lineTo(x, level)
    painter.drawPath(square)

    painter.end()
    return image


def png_bytes(image: QImage) -> bytes:
    # The byte array has to outlive the buffer. Passing a temporary leaves Qt writing into
    # memory Python has already freed, which takes the interpreter down with no traceback.
    store = QByteArray()
    buffer = QBuffer(store)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(store)


def write_ico(images: list[QImage], path: Path) -> None:
    """Assemble a multi-size .ico holding PNG payloads.

    Qt cannot write .ico in every build, and the container is small enough to lay out by
    hand: a header, one directory entry per size, then the payloads. A side of 256 is
    recorded as 0, which is how the format says "256".
    """
    payloads = [png_bytes(image) for image in images]
    offset = 6 + 16 * len(payloads)
    header = struct.pack("<HHH", 0, 1, len(payloads))
    directory = b""
    for image, payload in zip(images, payloads, strict=True):
        side = 0 if image.width() >= 256 else image.width()
        directory += struct.pack(
            "<BBBBHHII", side, side, 0, 0, 1, 32, len(payload), offset
        )
        offset += len(payload)
    path.write_bytes(header + directory + b"".join(payloads))


def main() -> int:
    RESOURCES.mkdir(parents=True, exist_ok=True)
    images = [draw(size) for size in SIZES]
    write_ico(images, RESOURCES / "icon.ico")
    images[-1].save(str(RESOURCES / "icon.png"), "PNG")
    for name in ("icon.ico", "icon.png"):
        written = RESOURCES / name
        print(f"  {name:10} {written.stat().st_size:>7} bytes  {written}")
    return 0


if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication

    # QImage needs a QGuiApplication before it will paint text or load plugins.
    QApplication([])
    raise SystemExit(main())
