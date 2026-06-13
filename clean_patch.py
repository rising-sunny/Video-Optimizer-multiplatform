import sys
import re

with open('auto_video_generator_v2.py', 'r', encoding='utf-8') as f:
    content = f.read()

# Replace all debug_loop.txt writes
content = re.sub(r'^[ \t]*with open\("debug_loop\.txt", "a".*?\n', '', content, flags=re.MULTILINE)

# Remove the base exception block we added earlier
old_except = '''            except Exception as e:
                import traceback
                self.log(f"      âš ï¸  Error en clip {i+1}: {e}")
                with open("debug_loop.txt", "a", encoding="utf-8") as f: f.write(f"Item {i}: Exception\\n{traceback.format_exc()}\\n")
            except BaseException as be:
                import traceback
                with open("debug_loop.txt", "a", encoding="utf-8") as f: f.write(f"Item {i}: BASE EXCEPTION\\n{traceback.format_exc()}\\n")
                raise'''

new_except = '''            except Exception as e:
                self.log(f"      âš ï¸  Error en clip {i+1}: {e}")'''

content = content.replace(old_except, new_except)

# Add time.sleep(0.1) before sp.run to fix the race condition!
content = content.replace('result = sp.run(cmd,', '_time.sleep(0.15)\n                result = sp.run(cmd,')

# Wait, `import time as _time` is already at the top of auto_video_generator_v2.py, let's verify if _time is used. Yes, in `_time.time()`.

with open('auto_video_generator_v2.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Patch cleaned and sleep added!")
