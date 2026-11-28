import pytest

from free_claude_code.application.orb.youtube import (
    YouTubeAudio,
    YouTubeError,
    plain_error,
    video_id,
)


def test_video_id_accepts_only_single_youtube_videos():
    assert video_id("https://www.youtube.com/watch?v=WftF2zJkvHY&t=30") == "WftF2zJkvHY"
    assert video_id("https://youtu.be/WftF2zJkvHY?si=x") == "WftF2zJkvHY"
    assert video_id("https://www.youtube.com/shorts/WftF2zJkvHY") == "WftF2zJkvHY"
    for bad in (
        "https://evil.example/watch?v=WftF2zJkvHY",
        "https://www.youtube.com/playlist?list=PL123",
        "file:///etc/passwd",
        "https://youtube.com.evil.example/watch?v=WftF2zJkvHY",
        "https://www.youtube.com/watch?v=short",
    ):
        with pytest.raises(YouTubeError):
            video_id(bad)


class FakeYdl:
    def __init__(self, options, root, fail=None):
        self.options, self.root, self.fail = options, root, fail

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def extract_info(self, url, download):
        if self.fail:
            raise RuntimeError(self.fail)
        assert url == "https://www.youtube.com/watch?v=WftF2zJkvHY" and download
        (self.root / "WftF2zJkvHY.m4a").write_bytes(b"audio")
        return {"title": "5 Years Later | Episode 1", "duration": 1234}


def test_download_once_then_reuse(tmp_path):
    made = []

    def factory(options):
        made.append(options)
        return FakeYdl(options, tmp_path)

    yt = YouTubeAudio(tmp_path, ydl_factory=factory)
    got = yt.download("https://youtu.be/WftF2zJkvHY")
    assert got["path"] == tmp_path / "WftF2zJkvHY.m4a" and got["title"].startswith(
        "5 Years"
    )
    assert made[0]["noplaylist"] is True and made[0]["postprocessors"] == []
    assert made[0]["format"].startswith("bestaudio[ext=m4a]")
    again = yt.download("https://www.youtube.com/watch?v=WftF2zJkvHY")
    assert again["bytes"] == 5 and len(made) == 1  # not downloaded twice


def test_download_errors_are_plain(tmp_path):
    yt = YouTubeAudio(
        tmp_path,
        ydl_factory=lambda o: FakeYdl(
            o, tmp_path, fail="ERROR: [youtube] x: Sign in to confirm you're not a bot"
        ),
    )
    with pytest.raises(YouTubeError, match=r"not a bot\. Open the video once"):
        yt.download("https://youtu.be/WftF2zJkvHY")
    assert "unavailable" in plain_error("ERROR: Video unavailable")
