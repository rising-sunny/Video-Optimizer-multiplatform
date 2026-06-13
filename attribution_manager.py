# attribution_manager.py
"""
Manages video attributions for Creative Commons and other licensed content.
Automatically tracks sources used in video projects and generates attribution text.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional


class AttributionManager:
    """
    Manages attributions for videos and media used in projects.
    Saves attribution data and generates formatted credit text.
    """

    def __init__(self, project_dir: str = "auto_videos"):
        self.project_dir = Path(project_dir)
        self.attributions_file = self.project_dir / "attributions.json"
        self.attributions: List[Dict] = []
        self._load_attributions()

    def _load_attributions(self):
        """Load existing attributions from file"""
        if self.attributions_file.exists():
            try:
                with open(self.attributions_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.attributions = data.get('attributions', [])
            except Exception as e:
                print(f"Warning: Could not load attributions: {e}")
                self.attributions = []
        else:
            self.attributions = []

    def _save_attributions(self):
        """Save attributions to file"""
        try:
            self.project_dir.mkdir(parents=True, exist_ok=True)
            data = {
                'attributions': self.attributions,
                'last_updated': datetime.now().isoformat()
            }
            with open(self.attributions_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Error saving attributions: {e}")

    def add_attribution(self, video_data: Dict, source: str = 'youtube') -> bool:
        """
        Add attribution for a video source.

        Args:
            video_data: Dictionary with video information
            source: Source platform ('youtube', 'wikimedia', 'internet_archive', 'pexels')

        Returns:
            True if added successfully
        """
        # Extract relevant info based on source
        attribution = {
            'source': source,
            'added_date': datetime.now().isoformat(),
        }

        if source == 'youtube':
            attribution.update({
                'title': video_data.get('title', 'Untitled'),
                'author': video_data.get('channel', 'Unknown'),
                'url': video_data.get('url', ''),
                'license': video_data.get('license', 'Creative Commons'),
                'video_id': video_data.get('video_id', ''),
            })
        elif source == 'wikimedia':
            attribution.update({
                'title': video_data.get('title', 'Untitled'),
                'author': video_data.get('author', video_data.get('user', 'Unknown')),
                'url': video_data.get('url', video_data.get('video_url', '')),
                'license': video_data.get('license', 'Creative Commons'),
                'description': video_data.get('description', ''),
            })
        elif source == 'internet_archive':
            attribution.update({
                'title': video_data.get('title', 'Untitled'),
                'author': video_data.get('creator', video_data.get('author', 'Unknown')),
                'url': video_data.get('url', video_data.get('video_url', '')),
                'license': video_data.get('license', 'Public Domain'),
                'identifier': video_data.get('identifier', ''),
                'date': video_data.get('date', ''),
            })
        elif source == 'pexels':
            attribution.update({
                'title': video_data.get('title', 'Stock Video'),
                'author': video_data.get('photographer', video_data.get('user', {}).get('name', 'Unknown')),
                'url': video_data.get('url', ''),
                'license': 'Pexels License (Free to use)',
            })
        else:
            attribution.update({
                'title': video_data.get('title', 'Untitled'),
                'author': video_data.get('author', video_data.get('channel', 'Unknown')),
                'url': video_data.get('url', ''),
                'license': video_data.get('license', 'Unknown'),
            })

        # Check if already exists (by URL)
        url = attribution.get('url', '')
        if url and any(a.get('url') == url for a in self.attributions):
            return False  # Already exists

        self.attributions.append(attribution)
        self._save_attributions()
        return True

    def remove_attribution(self, url: str) -> bool:
        """Remove an attribution by URL"""
        initial_count = len(self.attributions)
        self.attributions = [a for a in self.attributions if a.get('url') != url]
        if len(self.attributions) < initial_count:
            self._save_attributions()
            return True
        return False

    def clear_attributions(self):
        """Clear all attributions"""
        self.attributions = []
        self._save_attributions()

    def get_attributions(self) -> List[Dict]:
        """Get all attributions"""
        return self.attributions.copy()

    def get_attributions_by_source(self, source: str) -> List[Dict]:
        """Get attributions filtered by source"""
        return [a for a in self.attributions if a.get('source') == source]

    def generate_attribution_text(self, format_type: str = 'youtube_description') -> str:
        """
        Generate formatted attribution text for video description.

        Args:
            format_type: Output format ('youtube_description', 'markdown', 'plain')

        Returns:
            Formatted attribution text
        """
        if not self.attributions:
            return ""

        lines = []

        if format_type == 'youtube_description':
            lines.append("=" * 50)
            lines.append("VIDEO CREDITS & ATTRIBUTIONS")
            lines.append("=" * 50)
            lines.append("")

            # Group by source
            sources = {}
            for attr in self.attributions:
                source = attr.get('source', 'other')
                if source not in sources:
                    sources[source] = []
                sources[source].append(attr)

            # YouTube videos
            if 'youtube' in sources:
                lines.append("YouTube (Creative Commons):")
                for attr in sources['youtube']:
                    title = attr.get('title', 'Untitled')
                    author = attr.get('author', 'Unknown')
                    url = attr.get('url', '')
                    lines.append(f"  - \"{title}\" by {author}")
                    if url:
                        lines.append(f"    {url}")
                lines.append("")

            # Wikimedia Commons
            if 'wikimedia' in sources:
                lines.append("Wikimedia Commons:")
                for attr in sources['wikimedia']:
                    title = attr.get('title', 'Untitled')
                    author = attr.get('author', 'Unknown')
                    license_type = attr.get('license', 'CC')
                    url = attr.get('url', '')
                    lines.append(f"  - \"{title}\" by {author} ({license_type})")
                    if url:
                        lines.append(f"    {url}")
                lines.append("")

            # Internet Archive
            if 'internet_archive' in sources:
                lines.append("Internet Archive (Public Domain):")
                for attr in sources['internet_archive']:
                    title = attr.get('title', 'Untitled')
                    author = attr.get('author', 'Unknown')
                    date = attr.get('date', '')
                    url = attr.get('url', '')
                    date_str = f" ({date})" if date else ""
                    lines.append(f"  - \"{title}\" by {author}{date_str}")
                    if url:
                        lines.append(f"    {url}")
                lines.append("")

            # Pexels
            if 'pexels' in sources:
                lines.append("Pexels (Free Stock Video):")
                for attr in sources['pexels']:
                    title = attr.get('title', 'Stock Video')
                    author = attr.get('author', 'Unknown')
                    url = attr.get('url', '')
                    lines.append(f"  - Video by {author}")
                    if url:
                        lines.append(f"    {url}")
                lines.append("")

            # Other sources
            if 'other' in sources:
                lines.append("Other Sources:")
                for attr in sources['other']:
                    title = attr.get('title', 'Untitled')
                    author = attr.get('author', 'Unknown')
                    license_type = attr.get('license', '')
                    url = attr.get('url', '')
                    license_str = f" ({license_type})" if license_type else ""
                    lines.append(f"  - \"{title}\" by {author}{license_str}")
                    if url:
                        lines.append(f"    {url}")
                lines.append("")

        elif format_type == 'markdown':
            lines.append("## Video Credits & Attributions\n")

            sources = {}
            for attr in self.attributions:
                source = attr.get('source', 'other')
                if source not in sources:
                    sources[source] = []
                sources[source].append(attr)

            source_names = {
                'youtube': 'YouTube (Creative Commons)',
                'wikimedia': 'Wikimedia Commons',
                'internet_archive': 'Internet Archive',
                'pexels': 'Pexels',
                'other': 'Other Sources'
            }

            for source, attrs in sources.items():
                lines.append(f"### {source_names.get(source, source.title())}\n")
                for attr in attrs:
                    title = attr.get('title', 'Untitled')
                    author = attr.get('author', 'Unknown')
                    url = attr.get('url', '')
                    license_type = attr.get('license', '')
                    if url:
                        lines.append(f"- [{title}]({url}) by {author}")
                    else:
                        lines.append(f"- \"{title}\" by {author}")
                    if license_type:
                        lines.append(f"  - License: {license_type}")
                lines.append("")

        else:  # plain text
            lines.append("VIDEO CREDITS & ATTRIBUTIONS\n")
            for attr in self.attributions:
                title = attr.get('title', 'Untitled')
                author = attr.get('author', 'Unknown')
                source = attr.get('source', 'Unknown')
                url = attr.get('url', '')
                license_type = attr.get('license', '')
                lines.append(f"- {title} by {author} (Source: {source.title()})")
                if license_type:
                    lines.append(f"  License: {license_type}")
                if url:
                    lines.append(f"  URL: {url}")
                lines.append("")

        return "\n".join(lines)

    def get_attribution_count(self) -> int:
        """Get total number of attributions"""
        return len(self.attributions)

    def export_to_file(self, output_path: str, format_type: str = 'youtube_description') -> bool:
        """
        Export attributions to a text file.

        Args:
            output_path: Path to save the file
            format_type: Output format

        Returns:
            True if successful
        """
        try:
            text = self.generate_attribution_text(format_type)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception as e:
            print(f"Error exporting attributions: {e}")
            return False


# Global instance for easy access
_attribution_manager: Optional[AttributionManager] = None


def get_attribution_manager(project_dir: str = "auto_videos") -> AttributionManager:
    """Get or create the global AttributionManager instance"""
    global _attribution_manager
    if _attribution_manager is None or str(_attribution_manager.project_dir) != project_dir:
        _attribution_manager = AttributionManager(project_dir)
    return _attribution_manager
