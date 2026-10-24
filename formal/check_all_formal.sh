#!/usr/bin/env bash
set -euo pipefail

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$ROOT"

echo "=== [1/4] Verifying Lean 4 Toolchain ==="
lean_version=$(lean --version)
printf '%s\n' "$lean_version"
[[ "$lean_version" =~ version\ 4\.19\.0, ]]
python3 formal/theorem_inventory.py

echo "=== [2/4] Verifying Core and Sovereign Lean 4 Proof Modules ==="
module_list=$(python3 formal/theorem_inventory.py --modules)
mapfile -t MODULES <<< "$module_list"

audit_dir=$(mktemp -d)
trap 'rm -rf "$audit_dir"' EXIT

total_theorems=0

for file in "${MODULES[@]}"; do
    echo "-> Checking formal/$file.lean..."
    lean "formal/$file.lean"

    python3 - "$file" "$audit_dir" <<'PY'
import pathlib, re, sys
name, output = sys.argv[1:]
source = pathlib.Path('formal', name + '.lean').read_text()
code = re.sub(r'/\-[\s\S]*?\-/', '', source)
code = re.sub(r'--[^\n]*', '', code)
if re.search(r'\b(sorry|admit|axiom)\b', code):
    raise SystemExit(f'Forbidden proof escape in {name}')

# Detect namespace
ns_match = re.search(r'^namespace\s+([A-Za-z0-9_.]+)', source, re.M)
ns = ns_match.group(1) if ns_match else 'Corium'

theorems = re.findall(r'^theorem ([A-Za-z_][A-Za-z_0-9]*)', source, re.M)
if not theorems:
    raise SystemExit(f'No theorems found in {name}')

audit_content = source + '\n' + '\n'.join(f'#print axioms {ns}.{t}' for t in theorems) + '\n'
pathlib.Path(output, f'{name}_audit.lean').write_text(audit_content)
print(f'   {name}: {len(theorems)} theorems verified (namespace: {ns})')
PY

    lean "$audit_dir/${file}_audit.lean" > "$audit_dir/${file}_axioms.txt"
    python3 - "$audit_dir/${file}_axioms.txt" <<'PY'
import pathlib, re, sys
text = pathlib.Path(sys.argv[1]).read_text()
allowed = {'propext', 'Quot.sound', 'Classical.choice'}
for group in re.findall(r'depends on axioms: \[([^]]*)\]', text):
    used = set(filter(None, (s.strip() for s in group.split(','))))
    disallowed = used - allowed
    if disallowed:
        raise SystemExit(f'Unexpected proof axioms: {disallowed}')
if 'sorryAx' in text:
    raise SystemExit('Incomplete proof (sorryAx found)')
PY
done

echo "=== [3/4] Running Python comparisons against transcribed model formulas ==="
python3 formal/test_lean_differential.py
python3 formal/test_dna_correspondence.py

echo "=== [4/4] Verifying Source Correspondence ==="
python3 formal/check_source.py

echo "✅ All Lean 4 formal verification, axiom audits, and differential tests PASSED!"
