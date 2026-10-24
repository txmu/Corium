"""Exhaustive finite checks against executable Lean definitions, not crypto proofs."""
import ast
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import dna_protocol as dna
import cooperative_protocol as coop

class DNACorrespondence(unittest.TestCase):
    def evaluate(self,source,expression):
        with tempfile.TemporaryDirectory(prefix='corium-dna-lean-') as directory:
            file=Path(directory)/'Check.lean';file.write_text(source+'\n#eval '+expression+'\n')
            result=subprocess.run(['lean',str(file)],capture_output=True,text=True,timeout=30)
            if result.returncode:raise RuntimeError(result.stdout+result.stderr)
        return ast.literal_eval(result.stdout.replace('true','True').replace('false','False'))
    def test_actual_byte_encoding_matches_all_lean_cases(self):
        source=(ROOT/'formal/DNA.lean').read_text()
        actual=self.evaluate(source,'(List.range 256).map (fun n => let b := Corium.DNA.encodeByte n; (b.first,b.second,b.third,b.fourth))')
        for value,digits in enumerate(actual):
            expected=tuple(dna.ALPHABET.index(letter) for letter in dna.encode_bases(bytes([value])))
            self.assertEqual(digits,expected)
    def test_actual_quorum_matches_bounded_lean_cases(self):
        source=(ROOT/'formal/Cooperatives.lean').read_text()
        actual=self.evaluate(source,'(List.range 33).flatMap (fun n => (List.range (n+1)).map (fun v => (n,v,decide (Corium.Cooperatives.quorum v n))))')
        for members,voters,expected in actual:
            try:coop.quorum(dict.fromkeys(range(members)),dict.fromkeys(range(voters)));accepted=True
            except ValueError:accepted=False
            self.assertEqual(accepted,expected)

if __name__=='__main__':unittest.main()
