"""The flashing path, without a board or a programmer attached."""

from pathlib import Path

from stm32_msi import flashing


def test_a_missing_programmer_says_what_to_install(tmp_path, monkeypatch):
    """The one thing that cannot be shipped is the one thing most likely to be absent."""
    image = tmp_path / "firmware.elf"
    image.write_bytes(b"not really an image")
    monkeypatch.setattr(flashing, "find_programmer", lambda: None)

    ok, detail = flashing.run(image=image, port="COM4")
    assert not ok
    assert "STM32CubeProgrammer" in detail and "st.com" in detail


def test_a_missing_image_is_reported_before_anything_is_run(tmp_path, monkeypatch):
    def refuse(*_args, **_kwargs):
        raise AssertionError("the programmer must not run without an image")

    monkeypatch.setattr(flashing, "find_programmer", lambda: "programmer.exe")
    monkeypatch.setattr(flashing, "write", refuse)

    ok, detail = flashing.run(image=tmp_path / "absent.elf", port="COM4")
    assert not ok
    assert "no image at" in detail


def test_without_a_port_the_result_is_honest_about_what_was_proven(tmp_path, monkeypatch):
    """A verified write is not evidence that the image runs, and should not claim to be."""
    image = tmp_path / "firmware.elf"
    image.write_bytes(b"image")
    monkeypatch.setattr(flashing, "find_programmer", lambda: "programmer.exe")
    monkeypatch.setattr(flashing, "write", lambda *_: (True, "written and verified"))
    monkeypatch.setattr(
        flashing, "identify", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no port"))
    )

    ok, detail = flashing.run(image=image, port=None)
    assert ok
    assert "not confirmed to run" in detail


def test_a_failed_write_never_reaches_the_verify_step(tmp_path, monkeypatch):
    image = tmp_path / "firmware.elf"
    image.write_bytes(b"image")
    monkeypatch.setattr(flashing, "find_programmer", lambda: "programmer.exe")
    monkeypatch.setattr(flashing, "write", lambda *_: (False, "the programmer failed"))
    monkeypatch.setattr(
        flashing,
        "identify",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("must not verify")),
    )

    ok, detail = flashing.run(image=image, port="COM4")
    assert not ok
    assert detail == "the programmer failed"


def test_the_bundled_image_is_found_in_this_tree():
    """Not frozen here, so it should resolve to the build output if one exists."""
    found = flashing.bundled_image()
    assert found is None or (isinstance(found, Path) and found.name == flashing.IMAGE_NAME)
