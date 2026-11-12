"""Adapt our channel branding without regenerating the video's editorial content."""
import copy
import re
from channel.channel_profiles import CHANNELS


def channel_brand(channel):
    """Nombre de marca del canal, en texto ('Stunning Facts of History')."""
    if channel == 'nostalgic-mood':
        return 'Nostalgic Mood'
    return 'Stunning Facts of History' if channel == 'stunning-facts-of-history' else 'Stunning Revelations'


def metadata_for_channel(metadata, channel):
    profile = CHANNELS[channel]
    result = copy.deepcopy(metadata)
    handle = profile['name']
    brand = channel_brand(channel)
    tag = 'StunningFactsofHistory' if channel == 'stunning-facts-of-history' else 'StunningRevelations'
    aliases = r'Stunning[\s_-]*(?:Facts[\s_-]*of[\s_-]*History|Revelations)'
    pattern = re.compile(r'(?<!\w)([@#]?)' + aliases + r'(?!\w)', re.I)

    def adapt(text):
        def replace(match):
            prefix = match.group(1)
            return handle if prefix == '@' else '#' + tag if prefix == '#' else brand
        lines = []
        for line in str(text or '').split('\n'):
            # Attribution belongs to the source, even if it names one of our channels.
            if re.match(r'\s*(?:sources?|credits?|fuentes?|créditos?|attribution)\s*:', line, re.I):
                lines.append(line)
                continue
            line = re.sub(r'(https?://(?:www\.)?youtube\.com/)(?:@|c/|user/)' + aliases + r'(?!\w)',
                          lambda match: match.group(1) + handle, line, flags=re.I)
            line = pattern.sub(replace, line)
            for other in CHANNELS.values():
                line = line.replace('youtube.com/channel/' + other['channel_id'],
                                    'youtube.com/channel/' + profile['channel_id'])
            lines.append(line)
        return '\n'.join(lines)

    for field in ('title', 'description'):
        if field in result:
            result[field] = adapt(result[field])
    tags = result.get('tags') or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(',') if t.strip()]
    result['tags'] = list(dict.fromkeys(adapt(t) for t in tags))
    result['upload_channel'] = channel
    result['channel_profile'] = channel
    return result
