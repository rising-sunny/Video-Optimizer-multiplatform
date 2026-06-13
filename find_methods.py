import ast

with open('video_optimizer_pyqt6.py', 'r', encoding='utf-8-sig') as f:
    source = f.read()

tree = ast.parse(source)

def find_method_source(name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node.lineno, node.end_lineno
    return None

methods = [
    'create_analysis_tab', 'analyze_topic', 'on_analysis_finished', 'on_analysis_error',
    'research_topic', 'on_research_finished', 'on_research_error', '_on_research_item_changed',
    '_update_selected_research', '_select_all_research', '_deselect_all_research',
    'get_selected_research_context', 'show_video_recommendations', 'search_trends',
    'on_search_finished', 'on_search_error', 'refresh_trends',
    
    'create_thumbnails_tab', 'open_thumbnail_generator', 'open_interactive_thumbnail_editor',
    
    'create_log_panel'
]

results = {}
for m in methods:
    bounds = find_method_source(m)
    if bounds:
        results[m] = bounds

for m, b in results.items():
    print(f"{m}: {b[0]} - {b[1]}")
