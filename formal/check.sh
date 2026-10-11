#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$root"
lean --version | tee /dev/stderr | rg -q 'version 4\.19\.0,'
python3 formal/check_source.py
audit_dir=$(mktemp -d)
trap 'rm -rf "$audit_dir"' EXIT
for file in Models Implementation Refinements; do
    echo "Checking formal/$file.lean"
    lean "formal/$file.lean"
    python3 - "$file" "$audit_dir" <<'PY'
import pathlib, re, sys
name, output = sys.argv[1:]
source = pathlib.Path('formal', name+'.lean').read_text()
code = re.sub(r'/\-[\s\S]*?\-/', '', source)
code = re.sub(r'--[^\n]*', '', code)
if re.search(r'\b(sorry|admit|axiom)\b', code):
    raise SystemExit('Forbidden proof escape in '+name)
namespace = {'Models':'Corium','Implementation':'Corium.Implementation','Refinements':'Corium.Refinements'}[name]
theorems = re.findall(r'^theorem ([A-Za-z_][A-Za-z_0-9]*)', source, re.M)
if not theorems: raise SystemExit('No theorems in '+name)
pathlib.Path(output, 'audit.lean').write_text(source+'\n'+'\n'.join('#print axioms '+namespace+'.'+t for t in theorems)+'\n')
print(f'{name}: {len(theorems)} theorems')
PY
    lean "$audit_dir/audit.lean" > "$audit_dir/axioms.txt"
    cat "$audit_dir/axioms.txt"
    python3 - "$audit_dir/axioms.txt" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text()
allowed = {'propext', 'Quot.sound', 'Classical.choice'}
for group in re.findall(r'depends on axioms: \[([^]]*)\]', text):
    used = set(filter(None, (s.strip() for s in group.split(','))))
    if used - allowed: raise SystemExit('Unexpected proof axioms: '+str(used-allowed))
if 'sorryAx' in text: raise SystemExit('Incomplete proof')
PY
done
echo 'All Lean checks and axiom audits passed.'
