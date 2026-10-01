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


# Global instance for easy access
_attribution_manager: Optional[AttributionManager] = None


def get_attribution_manager(project_dir: str = "auto_videos") -> AttributionManager:
    """Get or create the global AttributionManager instance"""
    global _attribution_manager
    if _attribution_manager is None or str(_attribution_manager.project_dir) != project_dir:
        _attribution_manager = AttributionManager(project_dir)
    return _attribution_manager
