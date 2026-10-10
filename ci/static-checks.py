"""Compile Python files and directly invoked Python heredocs without executing them."""
import pathlib
import re

for path in pathlib.Path('.').glob('*.py'):
    compile(path.read_text(), str(path), 'exec')
source = pathlib.Path('corix_v108.sh').read_text()
lines = source.splitlines(keepends=True)
count = 0
for index, line in enumerate(lines):
    if not re.search(r'python3|PYTHON_CMD', line):
        continue
    match = re.search(r"<<(-?)\s*['\"]?([A-Za-z_][A-Za-z_0-9]*)['\"]?", line)
    if not match:
        continue
    body = []
    for candidate in lines[index + 1:]:
        normalized = candidate.lstrip('\t') if match[1] else candidate
        if normalized.rstrip('\n') == match[2]:
            break
        body.append(normalized)
    else:
        raise AssertionError(f'Unterminated heredoc at {index + 1}')
    compile(''.join(body), f'corix_v108.sh:{index + 2}', 'exec')
    count += 1
assert count > 0, 'No embedded Python found'
print(f'Compiled {count} directly invoked Python heredocs')
