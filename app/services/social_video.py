from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import logging
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

MAX_SOCIAL_VIDEO_BYTES = 18 * 1024 * 1024
SOCIAL_VIDEO_TIMEOUT_SECONDS = 75
SOCIAL_VIDEO_MAX_CONCURRENT_DOWNLOADS = 2
SOCIAL_VIDEO_CONCURRENCY = asyncio.Semaphore(SOCIAL_VIDEO_MAX_CONCURRENT_DOWNLOADS)
LOGGER = logging.getLogger("bn_bot.social_video")

INSTAGRAM_HOSTS = {
    "instagram.com",
    "www.instagram.com",
    "m.instagram.com",
    "instagr.am",
    "www.instagr.am",
}
TIKTOK_HOSTS = {
    "tiktok.com",
    "www.tiktok.com",
    "m.tiktok.com",
    "vm.tiktok.com",
    "vt.tiktok.com",
}
MEDIA_EXTENSIONS = {".mp4", ".webm", ".mov", ".m4v"}


class SocialVideoError(Exception):
    pass


class InvalidSocialVideoURL(SocialVideoError):
    pass


class SocialVideoTooLarge(SocialVideoError):
    pass


class SocialVideoTimedOut(SocialVideoError):
    pass


class SocialVideoUnavailable(SocialVideoError):
    pass


class SocialVideoRateLimited(SocialVideoError):
    pass


class SocialVideoDependencyError(SocialVideoError):
    pass


class SocialVideoExtractorError(SocialVideoError):
    pass


class SocialVideoNetworkError(SocialVideoError):
    pass


@dataclass(frozen=True)
class DownloadedSocialVideo:
    data: bytes
    filename: str
    size_bytes: int


def validate_social_video_url(url: str, platform: str) -> str:
    if platform not in {"instagram", "tiktok"}:
        raise InvalidSocialVideoURL("Plataforma não suportada.")

    value = url.strip()
    if not value or len(value) > 2048:
        raise InvalidSocialVideoURL("Informe um link válido.")

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise InvalidSocialVideoURL("O link não é válido.") from exc

    if parsed.scheme.lower() != "https" or parsed.username or parsed.password or port not in {None, 443}:
        raise InvalidSocialVideoURL("Use um link HTTPS público da plataforma.")

    host = (parsed.hostname or "").lower().rstrip(".")
    valid_hosts = INSTAGRAM_HOSTS if platform == "instagram" else TIKTOK_HOSTS
    if host not in valid_hosts:
        raise InvalidSocialVideoURL("O link não pertence à plataforma escolhida.")

    path = parsed.path.lower()
    if platform == "instagram" and host not in {"instagr.am", "www.instagr.am"}:
        if not path.startswith(("/reel/", "/reels/", "/p/")):
            raise InvalidSocialVideoURL("Envie um link de Reel ou publicação pública do Instagram.")

    if platform == "tiktok" and host not in {"vm.tiktok.com", "vt.tiktok.com"}:
        if "/video/" not in path and not path.startswith("/t/"):
            raise InvalidSocialVideoURL("Envie um link de vídeo público do TikTok.")

    return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))


def _folder_size(folder: Path) -> int:
    total = 0
    for path in folder.rglob("*"):
        if path.is_file():
            with contextlib.suppress(OSError):
                total += path.stat().st_size
    return total


def _start_process(args: list[str], folder: Path) -> subprocess.Popen[bytes]:
    if sys.platform == "win32":
        return subprocess.Popen(
            args,
            cwd=folder,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    return subprocess.Popen(args, cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


async def _stop_process(process: subprocess.Popen[bytes], communication: asyncio.Task[tuple[bytes, bytes]]) -> None:
    if process.poll() is None:
        with contextlib.suppress(OSError):
            process.kill()
    try:
        await asyncio.wait_for(asyncio.shield(communication), timeout=3)
    except TimeoutError:
        communication.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await communication
    except asyncio.CancelledError:
        communication.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await communication
    with contextlib.suppress(Exception):
        await asyncio.to_thread(process.wait)


def _error_excerpt(stdout: bytes, stderr: bytes) -> str:
    combined = (stderr + b"\n" + stdout).decode("utf-8", errors="replace")
    combined = re.sub(r"https?://\S+", "[URL]", combined)
    combined = re.sub(r"(?i)(cookie|authorization|token|password|secret)(\s*[=:]\s*)[^\s,;]+", r"\1\2[REDACTED]", combined)
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if not lines:
        return "yt-dlp terminou sem informar detalhes"
    markers = ("ERROR:", "HTTP Error", "Unable to extract", "No video formats", "Requested format", "login required", "timed out", "Name or service not known", "Failed to resolve")
    relevant = [line for line in lines if any(marker.casefold() in line.casefold() for marker in markers)]
    return " | ".join((relevant or lines)[-3:])[:360]


def _yt_dlp_version() -> str:
    try:
        return importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        return "desconhecida"


async def _run_downloader(url: str, folder: Path) -> tuple[int, bytes, bytes]:
    output_template = str(folder / "video.%(ext)s")
    args = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--no-config",
        "--no-playlist",
        "--no-progress",
        "--verbose",
        "--socket-timeout",
        "15",
        "--retries",
        "1",
        "--fragment-retries",
        "1",
        "--extractor-retries",
        "1",
        "--impersonate",
        "chrome",
        "--check-formats",
        "--max-filesize",
        "18M",
        "--format",
        "best[ext=mp4]/best",
        "--output",
        output_template,
        "--no-write-thumbnail",
        "--no-write-info-json",
        "--no-write-subs",
        "--no-write-auto-subs",
        url,
    ]

    try:
        process = _start_process(args, folder)
    except FileNotFoundError as exc:
        raise SocialVideoDependencyError("O Python ou o yt-dlp não está disponível neste ambiente.") from exc
    except OSError as exc:
        raise SocialVideoDependencyError("Não foi possível iniciar o downloader de vídeo.") from exc

    communication = asyncio.create_task(asyncio.to_thread(process.communicate))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + SOCIAL_VIDEO_TIMEOUT_SECONDS
    try:
        while not communication.done():
            await asyncio.sleep(0.4)
            if _folder_size(folder) > MAX_SOCIAL_VIDEO_BYTES:
                await _stop_process(process, communication)
                raise SocialVideoTooLarge("O vídeo passa do limite de 18 MB.")
            if loop.time() >= deadline:
                await _stop_process(process, communication)
                raise SocialVideoTimedOut("O download demorou demais.")
        stdout, stderr = communication.result()
    except asyncio.CancelledError:
        await _stop_process(process, communication)
        raise

    return int(process.returncode if process.returncode is not None else 1), stdout, stderr


async def download_social_video(url: str, platform: str) -> DownloadedSocialVideo:
    safe_url = validate_social_video_url(url, platform)

    async with SOCIAL_VIDEO_CONCURRENCY:
        with tempfile.TemporaryDirectory(prefix="bn-social-video-") as temporary:
            folder = Path(temporary)
            code, stdout, stderr = await _run_downloader(safe_url, folder)
            if code != 0:
                error_text = (stderr + b"\n" + stdout).decode("utf-8", errors="replace").lower()
                excerpt = _error_excerpt(stdout, stderr)
                LOGGER.warning(
                    "social video extraction failed platform=%s exit_code=%s yt_dlp=%s detail=%s",
                    platform,
                    code,
                    _yt_dlp_version(),
                    excerpt,
                )
                if "max-filesize" in error_text or "file is larger than" in error_text or "filesize is larger" in error_text:
                    raise SocialVideoTooLarge("O vídeo passa do limite de 18 MB.")
                if "no module named yt_dlp" in error_text or "curl_cffi" in error_text or "impersonation target" in error_text:
                    raise SocialVideoDependencyError("Faltam dependências de download. Reinstale o requirements.txt.")
                if "ffmpeg" in error_text and any(token in error_text for token in ("not found", "not installed", "not available")):
                    raise SocialVideoDependencyError("Este formato precisa do FFmpeg. Instale o FFmpeg e adicione-o ao PATH.")
                if "429" in error_text or "too many requests" in error_text or "rate limit" in error_text:
                    raise SocialVideoRateLimited("A plataforma limitou os pedidos. Espere um pouco antes de tentar novamente.")
                if any(token in error_text for token in ("name or service not known", "failed to resolve", "temporary failure in name resolution", "network is unreachable", "connection reset", "getaddrinfo failed", "unable to download webpage", "timed out")):
                    raise SocialVideoNetworkError("Não foi possível acessar a plataforma pela rede. Verifique a conexão do bot e tente novamente.")
                if any(token in error_text for token in ("login required", "log in", "private", "sign in", "requested content is not available")):
                    raise SocialVideoUnavailable("A plataforma não liberou o vídeo sem autenticação. Ele pode exigir login, ser privado ou estar indisponível.")
                if any(token in error_text for token in ("no video formats found", "unable to extract webpage video data", "requested format is not available", "video info extraction failed", "instagram sent an empty media response")):
                    raise SocialVideoExtractorError("O extrator não encontrou um formato compatível. Atualize o yt-dlp para o canal nightly e tente novamente; a plataforma pode ter alterado o formato de entrega.")
                if "http error 403" in error_text or "http error 404" in error_text:
                    raise SocialVideoUnavailable("A plataforma recusou a extração ou não encontrou a publicação. Se ela abrir normalmente no navegador, o extrator pode precisar de atualização.")
                raise SocialVideoExtractorError("O extrator falhou sem identificar uma causa conhecida. Consulte o log sanitizado do BN Bot para ver o detalhe técnico.")

            files = [
                path
                for path in folder.iterdir()
                if path.is_file() and path.suffix.lower() in MEDIA_EXTENSIONS and not path.name.endswith(".part")
            ]
            if not files:
                LOGGER.warning(
                    "social video extractor succeeded without a media file platform=%s yt_dlp=%s files=%s",
                    platform,
                    _yt_dlp_version(),
                    ",".join(path.suffix.lower() for path in folder.iterdir() if path.is_file())[:120] or "none",
                )
                raise SocialVideoExtractorError("O extrator terminou sem gerar um vídeo. Atualize o yt-dlp para o canal nightly e tente novamente; consulte o log do bot para o diagnóstico.")

            media_path = max(files, key=lambda path: path.stat().st_size)
            size_bytes = media_path.stat().st_size
            if size_bytes <= 0:
                raise SocialVideoUnavailable("O arquivo de vídeo veio vazio.")
            if size_bytes > MAX_SOCIAL_VIDEO_BYTES:
                raise SocialVideoTooLarge("O vídeo passa do limite de 18 MB.")

            data = await asyncio.to_thread(media_path.read_bytes)
            return DownloadedSocialVideo(data=data, filename=f"{platform}_video{media_path.suffix.lower()}", size_bytes=size_bytes)
