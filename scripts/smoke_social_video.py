from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.social_video import SocialVideoError, download_social_video

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")


async def run(platform: str, url: str) -> int:
    try:
        version = importlib.metadata.version("yt-dlp")
    except importlib.metadata.PackageNotFoundError:
        version = "ausente"
    print(f"yt-dlp: {version}")
    try:
        video = await download_social_video(url, platform)
    except SocialVideoError as exc:
        print(f"FAIL {platform}: {exc}")
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    stem = Path(video.filename).stem
    suffix = Path(video.filename).suffix
    output = Path.cwd() / f"{stem}_{stamp}{suffix}"
    output.write_bytes(video.data)
    print(f"PASS {platform}: {video.size_bytes} bytes saved to {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Testa o downloader social com um link informado.")
    parser.add_argument("platform", choices=("instagram", "tiktok"))
    parser.add_argument("url")
    args = parser.parse_args()
    return asyncio.run(run(args.platform, args.url))


if __name__ == "__main__":
    raise SystemExit(main())
