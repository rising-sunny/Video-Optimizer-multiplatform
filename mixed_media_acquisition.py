import os
import random
import subprocess
from pathlib import Path

# Import the existing YouTube client
from youtube_video_client import YouTubeVideoClient

def acquire_youtube_mixed_media(storyboard: dict, output_dir: Path):
    """
    Acquires YouTube videos for a portion of the segments (Mixed Media).
    The remaining segments are left empty to be processed by the AI/Real Image generator.
    Modifies storyboard in-place to add video_path where applicable.
    """
    yt_client = YouTubeVideoClient()
    project_media_dir = Path(output_dir) / "project_media"
    project_media_dir.mkdir(parents=True, exist_ok=True)
    
    segments = storyboard.get("segments", [])
    total_segments = len(segments)
    if total_segments == 0:
        return storyboard
        
    # Determine mix: approx 40-50% YouTube videos
    num_yt = max(1, int(total_segments * 0.45))
    
    # Randomly select indices for YouTube videos
    yt_indices = set(random.sample(range(total_segments), num_yt))
    
    for i, seg in enumerate(segments):
        assigned_filename = f"segment_{i+1:03d}"
        
        # Check if already has valid media
        if seg.get("video_path") and os.path.exists(seg.get("video_path")):
            continue
        if seg.get("image_path") and os.path.exists(seg.get("image_path")):
            continue
            
        if i in yt_indices:
            print(f"\n[Mixed Media] Acquiring YouTube video for segment {i+1}...")
            topic = storyboard.get("topic", "history")
            
            # Build search query based on topic and visual prompt
            visual_prompt = seg.get("visual_prompt", "")
            vp_keywords = " ".join(visual_prompt.split()[:5])
            search_query = f"{topic} {vp_keywords} historical footage"
            
            print(f"[Mixed Media] Searching YouTube with yt-dlp for: {search_query}")
            
            temp_mp4 = project_media_dir / f"{assigned_filename}_raw.mp4"
            final_mp4 = project_media_dir / f"{assigned_filename}.mp4"
            
            # Download using yt-dlp search directly
            dl_cmd = [
                "yt-dlp", 
                f"ytsearch1:{search_query}",
                "-f", "bestvideo[ext=mp4]",
                "-o", str(temp_mp4),
                "--no-playlist",
                "--max-downloads", "1"
            ]
            
            try:
                subprocess.run(dl_cmd, capture_output=True, timeout=45)
            except subprocess.TimeoutExpired:
                print(f"[Mixed Media] Timeout fetching video for {search_query}. Skipping.")
            
            if temp_mp4.exists():
                duration = seg.get("duration", 5.0)
                # Add padding to duration for transition overlap
                padded_duration = duration + 1.0 
                
                print(f"[Mixed Media] Trimming and cropping to vertical format ({padded_duration}s)...")
                # Trim and crop video: take a clip starting at 15 seconds to skip intros
                trim_cmd = [
                    "ffmpeg", "-y", "-i", str(temp_mp4),
                    "-ss", "00:00:15",
                    "-t", str(padded_duration),
                    "-vf", "crop=ih*9/16:ih,scale=1080:1920",
                    "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                    "-an", # remove audio
                    str(final_mp4)
                ]
                
                try:
                    subprocess.run(trim_cmd, capture_output=True, timeout=45)
                except subprocess.TimeoutExpired:
                    print(f"[Mixed Media] Timeout trimming video. Skipping.")
                
                if final_mp4.exists() and final_mp4.stat().st_size > 0:
                    seg["video_path"] = str(final_mp4)
                    seg["video_source"] = "youtube"
                    print(f"[Mixed Media] Success: {final_mp4}")
                else:
                    print(f"[Mixed Media] Failed to process video with FFmpeg.")
                    
                try:
                    os.remove(temp_mp4)
                except:
                    pass
            else:
                print(f"[Mixed Media] No YouTube results found for segment {i+1}.")
                
    return storyboard
