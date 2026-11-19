from pathlib import Path

PROJECT = Path('/home/videoagent/Video-Optimizer-multiplatform')
LAB = Path('/var/lib/one-rule-lab')
MATH = Path('/var/lib/mathrelaxing-auto')
DAILY = {'history': Path('/home/videoagent/foh-daily/days'),
         'mood': Path('/home/videoagent/nm-daily/days')}
# Credentials stay in each channel's existing publisher.
ACCOUNTS = {
    'lab': ('The Daily Lab', 'UCL_hJ6d1LMKmkD9C-cNXT1Q', LAB/'oauth.json'),
    'math': ('MathRelaxing', 'UCn8REDiVrUNYYVoPLSkXWqQ', Path('/etc/mathrelaxing-publisher/youtube-token.json')),
    'history': ('Stunning Facts of History', 'UCXQ1_6A-JkBeQsMkiDcunGA', PROJECT/'token.json'),
    'mood': ('Nostalgic Mood', 'UCmJPkyu-VyieqHVa9hbyS4w', PROJECT/'token_nostalgic-mood.json'),
}
