# video_source_alternatives.py
"""
Alternative sources for video when YouTube download fails.

Design:
- Prioritize local fallback first (fast and offline-safe).
- Keep remote sources as optional best-effort.
- Never generate fake/corrupt MP4 bytes.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

import requests


class AlternativeVideoSources:
    """Provide alternative videos when YouTube cannot be downloaded."""

    def __init__(self) -> None:
        # Local first to avoid blocking on network.
        self.alternative_sources = {
            "local_fallback": self._create_local_fallback,
            "wikimedia": self._get_wikimedia_videos,
            "pexels_sample": self._get_pexels_sample_videos,
        }

    def search_alternatives(self, query: str, max_results: int = 10) -> List[Dict]:
        print(f"Searching alternative videos for: '{query}'")
        all_videos: List[Dict] = []

        for source_name, source_func in self.alternative_sources.items():
            try:
                print(f"   Source: {source_name}")
                videos = source_func(query, max_results)
                if videos:
                    all_videos.extend(videos)
                    print(f"   Found: {len(videos)}")
                else:
                    print("   No videos found")
            except Exception as exc:
                print(f"   Source error: {exc}")

            if len(all_videos) >= max_results:
                break

        return all_videos[:max_results]

    def _create_local_fallback(self, query: str, max_results: int) -> List[Dict]:
        """Return at least one valid local mp4 if possible."""
        local_dir = Path(__file__).parent / "local_videos"
        local_dir.mkdir(parents=True, exist_ok=True)

        preferred = local_dir / "fallback_black.mp4"
        if not self._is_valid_video_file(preferred):
            self._create_fallback_video(preferred)

        candidates = []
        for path in local_dir.glob("*.mp4"):
            if self._is_valid_video_file(path):
                candidates.append(path)

        if not candidates:
            print("   No valid local fallback videos available.")
            return []

        # Prefer canonical fallback file first.
        candidates.sort(key=lambda p: 0 if p.name == "fallback_black.mp4" else 1)
        video_path = candidates[0]

        return [
            {
                "url": str(video_path),
                "title": f"Local fallback for {query}",
                "description": "Local fallback video",
                "channel": "Local System",
                "published_at": "",
                "thumbnail": "",
                "duration": 10,
                "view_count": 0,
                "like_count": 0,
                "source": "local",
                "query": query,
                "license": "Local",
            }
        ]

    def _create_fallback_video(self, output_path: Path) -> None:
        """Create a simple black 10s mp4 with ffmpeg if available."""
        ffmpeg_path = shutil.which("ffmpeg")
        if not ffmpeg_path:
            print("   ffmpeg not found; cannot auto-create local fallback video.")
            return

        cmd = [
            ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=black:size=1280x720:duration=10:rate=30",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ]

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if result.returncode == 0 and self._is_valid_video_file(output_path):
                print(f"   Local fallback created: {output_path}")
            else:
                print("   Could not create local fallback video with ffmpeg.")
        except Exception as exc:
            print(f"   ffmpeg fallback creation error: {exc}")

    def _get_wikimedia_videos(self, query: str, max_results: int) -> List[Dict]:
        """Best-effort Wikimedia lookup."""
        api_url = "https://commons.wikimedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": f"{query} filetype:video",
            "gsrnamespace": "6",
            "gsrlimit": min(max_results, 10),
            "prop": "imageinfo",
            "iiprop": "url|size|dimensions|extmetadata",
        }

        try:
            response = requests.get(api_url, params=params, timeout=8)
            response.raise_for_status()
            data = response.json()
        except Exception:
            return []

        pages = data.get("query", {}).get("pages", {})
        videos: List[Dict] = []
        for page in pages.values():
            imageinfo = page.get("imageinfo", [])
            if not imageinfo:
                continue
            media_url = imageinfo[0].get("url", "")
            if not media_url:
                continue
            videos.append(
                {
                    "url": media_url,
                    "title": page.get("title", "").replace("File:", ""),
                    "description": "",
                    "channel": "Wikimedia Commons",
                    "published_at": "",
                    "thumbnail": "",
                    "duration": 0,
                    "view_count": 0,
                    "like_count": 0,
                    "source": "wikimedia",
                    "query": query,
                    "license": "Creative Commons or Public Domain",
                }
            )
        return videos

    def _get_pexels_sample_videos(self, query: str, max_results: int) -> List[Dict]:
        """Static sample URL as optional last resort."""
        return [
            {
                "url": "https://sample-videos.com/zip/10/mp4/SampleVideo_1280x720_1mb.mp4",
                "title": f"Sample video for {query}",
                "description": "Sample fallback video",
                "channel": "Sample Videos",
                "published_at": "",
                "thumbnail": "",
                "duration": 10,
                "view_count": 0,
                "like_count": 0,
                "source": "sample",
                "query": query,
                "license": "Sample",
            }
        ][:max_results]

    @staticmethod
    def _is_valid_video_file(path: Path) -> bool:
        try:
            return path.exists() and path.is_file() and path.stat().st_size > 1024
        except Exception:
            return False


def get_alternative_videos(query: str, max_results: int = 10) -> List[Dict]:
    source = AlternativeVideoSources()
    return source.search_alternatives(query, max_results=max_results)


if __name__ == "__main__":
    found = get_alternative_videos("ufo incident", 5)
    for item in found:
        print(f"- {item['title']} ({item['source']})")
