# youtube_downloader_fixed.py
"""
Robust YouTube downloader with fast fallback behavior.

Goals:
- Avoid long retry loops when yt-dlp requires a JavaScript runtime.
- Try extractor args that often work without Node.js.
- Fallback quickly to alternative sources.
"""

import os
import random
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional


NODEJS_REQUIRED = "NODEJS_REQUIRED"


class FixedYouTubeDownloader:
    """Enhanced downloader with multi-strategy yt-dlp and alternative sources."""

    def __init__(self) -> None:
        self.user_agents = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]

    def download_video(self, video_info: Dict, output_path: str, max_attempts: int = 1) -> Optional[str]:
        """Download YouTube video. Returns resulting file path or None."""
        video_url = (video_info or {}).get("url", "")
        if not video_url:
            print("   ERROR: Missing YouTube URL")
            return None

        print("   Downloading video from YouTube...")
        print(f"   Video: {video_info.get('title', 'Untitled')}")

        output_dir = Path(output_path).parent
        output_dir.mkdir(parents=True, exist_ok=True)

        strategies = [
            self._download_with_yt_dlp_enhanced,
            self._download_with_yt_dlp_simple,
            self._download_with_yt_dlp_legacy,
            self._download_with_yt_dlp_audio_only,
        ]

        attempts = max(1, int(max_attempts))

        for attempt in range(attempts):
            for index, strategy in enumerate(strategies):
                try:
                    print(f"   Attempt {attempt + 1}, Strategy {index + 1}/{len(strategies)}")

                    if attempt > 0 or index > 0:
                        wait_time = random.uniform(0.4, 1.0)
                        print(f"   Waiting {wait_time:.1f}s...")
                        time.sleep(wait_time)

                    result = strategy(video_url, output_path, video_info)

                    if result == NODEJS_REQUIRED:
                        print("   JS runtime is required for this video.")
                        print("   Switching to alternative sources (no more YouTube retries).")
                        return self._offer_alternatives(video_info, output_path)

                    if self._is_valid_file(result):
                        file_size = os.path.getsize(result)
                        print(f"   Downloaded: {Path(result).name} ({file_size:,} bytes)")
                        return result

                except Exception as exc:
                    print(f"   Strategy error ({index + 1}): {exc}")

        print(f"   Could not download from YouTube after {attempts} attempt(s).")
        return self._offer_alternatives(video_info, output_path)

    def _offer_alternatives(self, video_info: Dict, output_path: str) -> Optional[str]:
        """Try alternative sources. Prioritize local assets first for speed."""
        print("   Looking for alternative video sources...")

        try:
            from media.video_source_alternatives import get_alternative_videos
        except Exception as exc:
            print(f"   Alternatives module not available: {exc}")
            return None

        query = video_info.get("title") or video_info.get("query") or "video"

        try:
            alternatives = get_alternative_videos(query, max_results=5)
        except Exception as exc:
            print(f"   Error getting alternatives: {exc}")
            return None

        if not alternatives:
            print("   No alternatives found.")
            return None

        # Local alternatives first to avoid network delays.
        alternatives = sorted(
            alternatives,
            key=lambda item: 0 if item.get("source") == "local" else 1,
        )

        for item in alternatives:
            source = item.get("source", "")
            alt_url = item.get("url", "")
            title = item.get("title", "alternative")

            try:
                if source == "local" and alt_url and os.path.exists(alt_url):
                    shutil.copy2(alt_url, output_path)
                    if self._is_valid_file(output_path):
                        print(f"   Local fallback copied: {title}")
                        return output_path
                    continue

                if alt_url:
                    result = self._download_simple_url(alt_url, output_path)
                    if self._is_valid_file(result):
                        print(f"   Alternative downloaded: {title}")
                        return result

            except Exception as exc:
                print(f"   Alternative failed ({title}): {exc}")

        print("   No viable alternatives available.")
        return None

    def _download_simple_url(self, url: str, output_path: str) -> Optional[str]:
        """Download a direct file URL with requests."""
        try:
            import requests

            with requests.get(url, stream=True, timeout=30) as response:
                response.raise_for_status()
                with open(output_path, "wb") as file_obj:
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            file_obj.write(chunk)

            return output_path if self._is_valid_file(output_path) else None
        except Exception as exc:
            print(f"   Direct URL download error: {exc}")
            return None

    def _download_with_yt_dlp_enhanced(self, video_url: str, output_path: str, video_info: Dict) -> Optional[str]:
        cmd = self._build_yt_dlp_cmd(
            video_url=video_url,
            output_path=output_path,
            format_selector="bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            extra_args=["--no-cache", "--retries", "3", "--fragment-retries", "3"],
        )
        return self._execute_cmd(cmd, output_path)

    def _download_with_yt_dlp_simple(self, video_url: str, output_path: str, video_info: Dict) -> Optional[str]:
        cmd = self._build_yt_dlp_cmd(
            video_url=video_url,
            output_path=output_path,
            format_selector="best[ext=mp4]/best",
        )
        return self._execute_cmd(cmd, output_path)

    def _download_with_yt_dlp_legacy(self, video_url: str, output_path: str, video_info: Dict) -> Optional[str]:
        cmd = self._build_yt_dlp_cmd(
            video_url=video_url,
            output_path=output_path,
            format_selector="worst[ext=mp4]/worst",
            extra_args=["--prefer-insecure"],
        )
        return self._execute_cmd(cmd, output_path)

    def _download_with_yt_dlp_audio_only(self, video_url: str, output_path: str, video_info: Dict) -> Optional[str]:
        audio_path = str(Path(output_path).with_suffix(".mp3"))
        cmd = self._build_yt_dlp_cmd(
            video_url=video_url,
            output_path=audio_path,
            format_selector="bestaudio[ext=m4a]/bestaudio/best",
            extra_args=["--extract-audio", "--audio-format", "mp3"],
        )
        result = self._execute_cmd(cmd, audio_path)
        if self._is_valid_file(result):
            print("   Audio downloaded. Creating static video...")
            return self._create_video_from_audio(result, output_path)
        return result if result == NODEJS_REQUIRED else None

    def _build_yt_dlp_cmd(
        self,
        video_url: str,
        output_path: str,
        format_selector: str,
        extra_args: Optional[List[str]] = None,
    ) -> List[str]:
        user_agent = random.choice(self.user_agents)
        cmd = [
            sys.executable,
            "-m",
            "yt_dlp",
            "-f",
            format_selector,
            "-o",
            str(output_path),
            "--no-playlist",
            "--no-warnings",
            "--user-agent",
            user_agent,
            "--no-check-certificate",
            "--socket-timeout",
            "30",
            "--extractor-args",
            "youtube:player_client=android,web",
        ]
        if extra_args:
            cmd.extend(extra_args)
        cmd.append(video_url)
        return cmd

    def _create_video_from_audio(self, audio_path: str, video_path: str) -> Optional[str]:
        """Create a simple black background video from an audio file."""
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=1280x720:rate=30",
            "-i",
            audio_path,
            "-c:v",
            "libx264",
            "-c:a",
            "aac",
            "-shortest",
            "-pix_fmt",
            "yuv420p",
            video_path,
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if result.returncode == 0 and self._is_valid_file(video_path):
                try:
                    os.remove(audio_path)
                except Exception:
                    pass
                return video_path
        except Exception as exc:
            print(f"   Error creating video from audio: {exc}")
        return None

    def _execute_cmd(self, cmd: List[str], output_path: str) -> Optional[str]:
        """Execute command and inspect output robustly."""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=180)

            if self._is_valid_file(output_path):
                return output_path

            combined_output = "\n".join(part for part in [result.stderr, result.stdout] if part)
            combined_output_lc = combined_output.lower()

            if self._is_nodejs_required_error(combined_output_lc):
                print("   Node.js (or another JS runtime) is required by yt-dlp for this video.")
                return NODEJS_REQUIRED

            if "http error 403" in combined_output_lc or "403 forbidden" in combined_output_lc:
                print("   HTTP 403: YouTube blocked this download attempt.")
                return None

            if combined_output.strip():
                first_line = next((line.strip() for line in combined_output.splitlines() if line.strip()), "")
                if first_line:
                    print(f"   Error: {first_line[:240]}")

            return None

        except subprocess.TimeoutExpired:
            print("   Download timeout.")
            return None
        except Exception as exc:
            print(f"   Command execution error: {exc}")
            return None

    @staticmethod
    def _is_valid_file(path: Optional[str]) -> bool:
        return bool(path) and os.path.exists(path) and os.path.getsize(path) > 0

    @staticmethod
    def _is_nodejs_required_error(output_text_lc: str) -> bool:
        if not output_text_lc:
            return False
        markers = [
            "no supported javascript runtime could be found",
            "youtube extraction without a js runtime has been deprecated",
            "--js-runtimes",
            "javascript runtime",
            "requires a javascript runtime",
            "js runtime",
        ]
        return any(marker in output_text_lc for marker in markers)


def download_video_fixed(video_info: Dict, output_path: str) -> Optional[str]:
    """Compatibility wrapper."""
    downloader = FixedYouTubeDownloader()
    return downloader.download_video(video_info, output_path)


if __name__ == "__main__":
    sample_video = {
        "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "title": "Test Video",
    }
    result_path = download_video_fixed(sample_video, "test_video.mp4")
    if result_path:
        print(f"OK: {result_path}")
    else:
        print("FAILED")
