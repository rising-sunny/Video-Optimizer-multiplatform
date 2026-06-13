import os

with open('video_optimizer_pyqt6.py', 'r', encoding='utf-8-sig') as f:
    lines = f.readlines()

analysis_ranges = [
    (900, 1082), (1244, 1272), (1274, 1285), (1287, 1293), (1297, 1321),
    (1323, 1357), (1359, 1364), (1366, 1368), (1370, 1390), (1392, 1398),
    (1400, 1406), (1408, 1410), (1412, 1443), (1445, 1481), (1483, 1487),
    (1489, 1492), (1494, 1540)
]

thumbnails_ranges = [
    (1084, 1213), (1716, 1763), (1765, 1796), (2497, 2513), (2745, 2794),
    (3031, 3050), (3052, 3116), (3118, 3190), (3192, 3242), (3244, 3256)
]

# Recolectar imports
importsText = """from PyQt6.QtWidgets import *
from PyQt6.QtCore import *
from PyQt6.QtGui import *
import json
from pathlib import Path
from PIL import Image
import threading
import time
from ui_workers import AnalysisWorker, ResearchWorker, TrendsWorker, SearchWorker
"""

analysis_methods = []
thumbnails_methods = []

def extract_bounds(ranges, dest_list):
    for start, end in ranges:
        # lines are 0-indexed, ranges were 1-indexed from ast
        # start-1 to end
        method_lines = lines[start-1:end]
        dest_list.append("".join(method_lines))

extract_bounds(analysis_ranges, analysis_methods)
extract_bounds(thumbnails_ranges, thumbnails_methods)

# Escribir analysis_mixin.py
with open('analysis_mixin.py', 'w', encoding='utf-8') as f:
    f.write(importsText + "\\n")
    f.write("class AnalysisMixin:\\n")
    for m in analysis_methods:
        f.write(m + "\\n")

# Escribir thumbnails_mixin.py
with open('thumbnails_mixin.py', 'w', encoding='utf-8') as f:
    f.write(importsText + "\\n")
    f.write("class ThumbnailsMixin:\\n")
    for m in thumbnails_methods:
        f.write(m + "\\n")

# Borrar del archivo original (de abajo hacia arriba para no romper los indices)
all_ranges = analysis_ranges + thumbnails_ranges
all_ranges.sort(key=lambda x: x[0], reverse=True)

new_lines = list(lines)
for start, end in all_ranges:
    del new_lines[start-1:end]

# Buscar class VideoOptimizerGUI y modificar los imports
text = "".join(new_lines)
import_str = "from analysis_mixin import AnalysisMixin\\nfrom thumbnails_mixin import ThumbnailsMixin\\n"

# insertar debajo del ultimo import
text = text.replace("from ui_themes import STYLESHEET", import_str + "from ui_themes import STYLESHEET")
text = text.replace("class VideoOptimizerGUI(QMainWindow):", "class VideoOptimizerGUI(QMainWindow, AnalysisMixin, ThumbnailsMixin):")

with open('video_optimizer_pyqt6.py', 'w', encoding='utf-8') as f:
    f.write(text)

print("Mixins creados exitosamente")
