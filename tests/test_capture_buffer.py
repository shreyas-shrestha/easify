from app.engine.buffer import CaptureBuffer


def test_capture_buffer_max() -> None:
    b = CaptureBuffer(max_chars=3)
    b.push("a")
    b.push("b")
    b.push("c")
    b.push("d")
    assert b.text() == "abc"
