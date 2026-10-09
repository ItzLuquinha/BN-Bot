from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from app.services import social_video
from app.services.social_video import (
    InvalidSocialVideoURL,
    SocialVideoRateLimited,
    SocialVideoExtractorError,
    SocialVideoNetworkError,
    download_social_video,
    validate_social_video_url,
)


def test_instagram_public_reel_url_is_accepted() -> None:
    value = "https://www.instagram.com/reel/ABC123/?igsh=example#section"
    assert validate_social_video_url(value, "instagram") == "https://www.instagram.com/reel/ABC123/?igsh=example"


def test_instagram_wrong_path_is_rejected() -> None:
    with pytest.raises(InvalidSocialVideoURL):
        validate_social_video_url("https://www.instagram.com/accounts/login/", "instagram")


def test_tiktok_public_video_url_is_accepted() -> None:
    value = "https://www.tiktok.com/@user/video/123456789"
    assert validate_social_video_url(value, "tiktok") == value


def test_short_tiktok_link_is_accepted() -> None:
    value = "https://vm.tiktok.com/ZM-example/"
    assert validate_social_video_url(value, "tiktok") == value


@pytest.mark.parametrize(
    "url,platform",
    [
        ("http://www.instagram.com/reel/abc/", "instagram"),
        ("https://instagram.com.evil.example/reel/abc/", "instagram"),
        ("https://www.tiktok.com.evil.example/@user/video/123", "tiktok"),
        ("https://user:password@www.tiktok.com/@user/video/123", "tiktok"),
        ("https://example.com/video.mp4", "instagram"),
        ("https://www.tiktok.com/@user/video/123", "instagram"),
    ],
)
def test_invalid_social_video_urls_are_rejected(url: str, platform: str) -> None:
    with pytest.raises(InvalidSocialVideoURL):
        validate_social_video_url(url, platform)


@pytest.mark.asyncio
async def test_download_uses_threaded_subprocess_and_returns_limited_media(monkeypatch: pytest.MonkeyPatch) -> None:
    invoked: dict[str, object] = {}

    class FakeProcess:
        returncode = 0

        def __init__(self, args, **kwargs):
            invoked["args"] = args
            invoked["kwargs"] = kwargs
            folder = Path(kwargs["cwd"])
            (folder / "video.mp4").write_bytes(b"test-video")

        def communicate(self):
            return b"", b""

        def wait(self):
            return self.returncode

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = -9

    monkeypatch.setattr(social_video.subprocess, "Popen", FakeProcess)
    result = await download_social_video("https://www.instagram.com/reel/ABC123/", "instagram")
    assert result.data == b"test-video"
    assert result.filename == "instagram_video.mp4"
    assert result.size_bytes == len(b"test-video")
    args = invoked["args"]
    assert isinstance(args, list)
    assert args[args.index("--impersonate") + 1] == "chrome"
    assert "--check-formats" in args
    assert args[args.index("--format") + 1] == "best[ext=mp4]/best"
    assert "--verbose" in args


@pytest.mark.asyncio
async def test_download_maps_platform_rate_limits_to_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_downloader(url: str, folder: Path) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ERROR: HTTP Error 429: Too Many Requests"

    monkeypatch.setattr(social_video, "_run_downloader", fake_run_downloader)
    with pytest.raises(SocialVideoRateLimited, match="limitou os pedidos"):
        await download_social_video("https://www.instagram.com/reel/ABC123/", "instagram")




@pytest.mark.asyncio
async def test_download_classifies_format_extractor_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_downloader(url: str, folder: Path) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ERROR: [TikTok] No video formats found!"

    monkeypatch.setattr(social_video, "_run_downloader", fake_run_downloader)
    with pytest.raises(SocialVideoExtractorError, match="canal nightly"):
        await download_social_video("https://www.tiktok.com/@user/video/123456789", "tiktok")


@pytest.mark.asyncio
async def test_download_classifies_dns_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run_downloader(url: str, folder: Path) -> tuple[int, bytes, bytes]:
        return 1, b"", b"ERROR: Unable to download webpage: [Errno 11001] getaddrinfo failed"

    monkeypatch.setattr(social_video, "_run_downloader", fake_run_downloader)
    with pytest.raises(SocialVideoNetworkError, match="rede"):
        await download_social_video("https://www.tiktok.com/@user/video/123456789", "tiktok")


def test_error_excerpt_redacts_urls() -> None:
    excerpt = social_video._error_excerpt(b"", b"ERROR: request failed at https://example.com/private?token=secret")
    assert "https://" not in excerpt
    assert "secret" not in excerpt


def test_history_imports_both_interaction_helpers_and_uses_compact_output() -> None:
    from pathlib import Path

    source = Path("app/discord/cogs/utility.py").read_text(encoding="utf-8")
    assert "from app.core.interactions import defer, respond" in source
    start = source.index("async def history(")
    end = source.index("async def _publish_social_video", start)
    history = source[start:end]
    assert "await defer(interaction, ephemeral=True)" in history
    assert "Não foi possível carregar o histórico agora." in history
    assert "CATEGORY_LABELS" not in history
    publish = source[source.index("async def _publish_social_video"):source.index('@command_rate_limit("instagram-video"')]
    assert publish.index("await defer(interaction, ephemeral=True)") < publish.index("await download_social_video(safe_url, platform)")


def test_social_commands_are_in_expected_command_matrix() -> None:
    from app.services.command_matrix import EXPECTED_COMMANDS, audit_commands, case_issues

    cases = {case.qualified_name: case for case in audit_commands()}
    assert {"instagram", "tiktok"}.issubset(EXPECTED_COMMANDS)
    assert all(name in cases for name in ("instagram", "tiktok"))
    assert case_issues(cases["instagram"]) == []
    assert case_issues(cases["tiktok"]) == []


def test_testall_checks_social_video_dependencies_and_registered_commands() -> None:
    from pathlib import Path

    source = Path("app/services/diagnostics.py").read_text(encoding="utf-8")
    assert '"yt-dlp", "curl-cffi"' in source
    assert "_social_video_runtime_check(bot)" in source
    assert '"instagram", "tiktok"' in source
    assert 'importlib.import_module("curl_cffi")' in source


def test_smoke_script_runs_the_same_limited_downloader() -> None:
    from pathlib import Path

    source = Path("scripts/smoke_social_video.py").read_text(encoding="utf-8")
    assert "download_social_video(url, platform)" in source
    assert "SocialVideoError" in source


def test_social_video_dependencies_include_impersonation_extras() -> None:
    from pathlib import Path

    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    project = Path("pyproject.toml").read_text(encoding="utf-8")
    assert "yt-dlp[default,curl-cffi]>=2026.8.19.dev0,<2027" in requirements
    assert "yt-dlp[default,curl-cffi]>=2026.8.19.dev0,<2027" in project
