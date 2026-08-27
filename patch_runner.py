import os
import re

file_path = r'd:\Workbase\Plugins\Gum\PokemonAutoShiny\core\plan_runner.py'
with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip = False
for i, line in enumerate(lines):
    # 1. Remove dead code _eval_condition (lines 343 to 451 approximately)
    if 'def _eval_condition(' in line and 'default_next: Optional[int] = None) -> int:' in lines[i+1]:
        skip = True
        
    if skip:
        # Check if we reached the next method which is _make_inline_handler
        if 'def _make_inline_handler(self, loop_n: int):' in line or '── Inline OCR handler' in line:
            skip = False
        else:
            continue

    # 2. Imports
    if line == 'import random\n' and lines[i+1] == 'from typing import Callable, Optional\n':
        new_lines.append('import random\n')
        new_lines.append('import re\n')
        continue
        
    # 3. _text_matches re
    if 'import re as _re' in line:
        continue # remove this line
    if 'return bool(_re.search(pattern, text, _re.IGNORECASE))' in line:
        new_lines.append(line.replace('_re.search', 're.search').replace('_re.IGNORECASE', 're.IGNORECASE'))
        continue
    if 'except _re.error:' in line:
        new_lines.append(line.replace('_re.error', 're.error'))
        continue

    # 4. Flags to Event
    if 'self._stop_flag  = False' in line:
        new_lines.append('        self._abort_event = threading.Event()\n')
        continue
    if 'self._stop_flag   = False' in line:
        new_lines.append('        self._abort_event.clear()\n')
        continue
    if 'self._stop_flag = True' in line:
        new_lines.append('        self._abort_event.set()\n')
        continue
        
    # Condition updates: not self._stop_flag and not self._shiny_flag
    if 'and not self._stop_flag and not self._shiny_flag' in line:
        new_lines.append(line.replace('and not self._stop_flag and not self._shiny_flag', 'and not self._abort_event.is_set()'))
        continue
    if 'self._stop_flag or self._shiny_flag' in line:
        new_lines.append(line.replace('self._stop_flag or self._shiny_flag', 'self._abort_event.is_set()'))
        continue
    if 'self._stop_flag' in line:
        new_lines.append(line.replace('self._stop_flag', 'self._abort_event.is_set()'))
        continue

    # Add try-except in the main loop and indent
    if 'while not self._abort_event.is_set():' in line or 'while not self._stop_flag:' in line:
        pass # Handle below
        
    new_lines.append(line)

# Now join and do a second pass for the try/except block and wait logic
content = "".join(new_lines)

# Fix time.sleep to wait
content = content.replace(
'''                                wait_deadline = time.time() + interval
                                while time.time() < wait_deadline and not self._abort_event.is_set():
                                    time.sleep(0.05)''',
'''                                self._abort_event.wait(interval)''')

content = content.replace(
'''                            deadline = time.time() + total_delay
                            while time.time() < deadline and not self._abort_event.is_set():
                                time.sleep(0.05)''',
'''                            if total_delay > 0:
                                self._abort_event.wait(total_delay)''')

# Add try-except around the inside of `while not self._abort_event.is_set():`
# We'll use a regex to replace the block
pattern = r'(while not self\._abort_event\.is_set\(\):\n)(                if self\._total_loops > 0.*?)(        finally:\n)'
match = re.search(pattern, content, re.DOTALL)
if match:
    while_stmt = match.group(1)
    inner_block = match.group(2)
    finally_stmt = match.group(3)
    
    # Indent inner_block by 4 spaces
    indented_block = "\n".join("    " + l if l else l for l in inner_block.split("\n"))
    
    new_block = while_stmt + "                try:\n" + indented_block
    new_block = new_block.rstrip() + "\n"
    new_block += "                except Exception as exc:\n"
    new_block += "                    dlog(f\"[plan] FATAL ERROR in run loop: {exc}\")\n"
    new_block += "                    self._abort_event.set()\n"
    new_block += "                    break\n\n"
    new_block += finally_stmt
    
    content = content[:match.start()] + new_block + content[match.end():]

# Set abort_event when shiny is found
content = content.replace(
'''            if is_shiny:
                self._shiny_flag = True
                if self.on_shiny:''',
'''            if is_shiny:
                self._shiny_flag = True
                self._abort_event.set()
                if self.on_shiny:''')

with open(file_path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Patch applied successfully.")
