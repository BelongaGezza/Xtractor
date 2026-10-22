from __future__ import annotations

import io

from xtractor.ui import Reporter, human_eta, human_size, render_progress
from xtractor.ytdlp import Progress


class TtyStream(io.StringIO):
    def isatty(self) -> bool:
        return True


def prog(done: int, total: int | None = 1000, status: str = "downloading") -> Progress:
    return Progress(done, total, 2048.0, 7, status)


def test_human_formatting() -> None:
    assert human_size(None) == "?"
    assert human_size(512) == "512 B"
    assert human_size(2048) == "2.0 KiB"
    assert human_size(5 * 1024**2) == "5.0 MiB"
    assert human_size(3 * 1024**4) == "3072.0 GiB"
    assert human_eta(None) == "?"
    assert human_eta(75) == "01:15"
    assert human_eta(3725) == "1:02:05"


def test_render_progress() -> None:
    assert render_progress(prog(500)) == " 50.0% of 1000 B at 2.0 KiB/s ETA 00:07"
    unknown = render_progress(Progress(2048, None, None, None, "downloading"))
    assert "?" in unknown and "2.0 KiB" in unknown and "?/s" in unknown


def test_messages_and_quiet() -> None:
    s = io.StringIO()
    r = Reporter(stream=s)
    r.info("i")
    r.notice("n")
    r.warn("w")
    r.error("e")
    r.debug("hidden")
    assert s.getvalue() == "i\nXtractor: note: n\nXtractor: warning: w\nXtractor: error: e\n"
    q = io.StringIO()
    rq = Reporter(quiet=True, stream=q)
    rq.info("i")
    rq.notice("n")
    rq.warn("w")
    rq.progress(prog(5))
    assert q.getvalue() == ""
    rq.error("e")
    assert q.getvalue() == "Xtractor: error: e\n"


def test_verbose_debug() -> None:
    s = io.StringIO()
    Reporter(verbose=True, stream=s).debug("detail")
    assert s.getvalue() == "detail\n"


def test_default_stream_is_stderr(capsys) -> None:  # type: ignore[no-untyped-def]
    Reporter().info("hello")
    cap = capsys.readouterr()
    assert cap.out == "" and cap.err == "hello\n"


def test_tty_progress_single_line_with_carriage_returns() -> None:
    s = TtyStream()
    r = Reporter(stream=s)
    r.progress(prog(100))
    r.progress(prog(500))
    assert "\n" not in s.getvalue()
    assert s.getvalue().count("\r") == 2
    r.progress(prog(1000, status="finished"))
    assert s.getvalue().endswith("\n")
    r.info("next")
    assert s.getvalue().endswith("next\n")


def test_tty_message_closes_open_progress_line() -> None:
    s = TtyStream()
    r = Reporter(stream=s)
    r.progress(prog(100))
    r.warn("w")
    assert "\nXtractor: warning: w\n" in s.getvalue()


def test_non_tty_throttles_by_percent_and_time() -> None:
    s = io.StringIO()
    now = [0.0]
    r = Reporter(stream=s, clock=lambda: now[0])
    r.progress(prog(0))  # first event always shown
    r.progress(prog(50))  # +5%: suppressed
    r.progress(prog(100))  # +10%: shown
    assert s.getvalue().count("\n") == 2
    now[0] = 6.0
    r.progress(prog(101))  # time elapsed: shown
    assert s.getvalue().count("\n") == 3
    r.progress(prog(1000, status="finished"))
    assert s.getvalue().count("\n") == 4
    r.progress(prog(1000, status="finished"))  # duplicate completion line suppressed
    assert s.getvalue().count("\n") == 4
    assert "\r" not in s.getvalue()


def test_non_tty_second_stream_restarts() -> None:
    s = io.StringIO()
    r = Reporter(stream=s, clock=lambda: 0.0)
    r.progress(prog(1000))
    r.progress(prog(1000, status="finished"))
    n = s.getvalue().count("\n")
    r.progress(prog(10))  # a new stream (smaller byte count) is shown
    assert s.getvalue().count("\n") == n + 1
    r.reset_progress()
    r.progress(prog(10))
    assert s.getvalue().count("\n") == n + 2


def test_unknown_total_non_tty() -> None:
    s = io.StringIO()
    r = Reporter(stream=s, clock=lambda: 0.0)
    r.progress(Progress(10, None, None, None, "downloading"))
    r.progress(Progress(20, None, None, None, "downloading"))
    assert s.getvalue().count("\n") == 1
