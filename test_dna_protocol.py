import copy
import hashlib
import unittest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.exceptions import InvalidSignature
import dna_protocol as dna


class DNAProtocolTests(unittest.TestCase):
    def test_all_byte_encodings_and_complements(self):
        for value in range(256):
            raw=bytes([value]);strand=dna.encode_bases(raw)
            self.assertEqual(dna.decode_bases(strand),raw)
            self.assertEqual(dna.complement(dna.complement(strand)),strand)
        self.assertEqual(dna.encode_bases(bytes([0,255])), 'AAAATTTT')

    def test_authenticated_strand_repair_and_coherent_tampering(self):
        raw=b'cooperative state';gene=dna.duplex(raw);root=gene['root']
        self.assertEqual(dna.restore(gene,root),raw)
        for strand in ('sense','antisense'):
            damaged=copy.deepcopy(gene);damaged[strand]='X'+damaged[strand][1:]
            with self.assertRaises(ValueError):dna.restore(damaged,root)
            self.assertEqual(dna.restore(damaged,root,repair=True),raw)
        with self.assertRaises(ValueError):dna.restore(dna.duplex(b'forged new state'),root,repair=True)
        damaged=copy.deepcopy(gene);damaged['sense']='X'+damaged['sense'][1:];damaged['antisense']='X'+damaged['antisense'][1:]
        with self.assertRaises(ValueError):dna.restore(damaged,root,repair=True)

    def test_rna_domains_sequences_and_actual_signatures(self):
        key=ec.generate_private_key(ec.SECP256K1());pem=dna.public_key(key);sender=hashlib.sha256(pem.encode()).hexdigest()
        frame=dna.rna_sign(key,'a'*64,'b'*64,sender,1,100,b'actual RNA payload')
        def verify(value,chain='a'*64,previous=0,now=110):return dna.rna_open(value,pem,chain,'b'*64,sender,previous,now)
        self.assertEqual(verify(frame),b'actual RNA payload')
        for changes in [{'chain':'c'*64},{'previous':1},{'now':221}]:
            with self.assertRaises(ValueError):verify(frame,**changes)
        for part in ('signature','rna'):
            altered=copy.deepcopy(frame);altered[part]=('0' if part=='signature' else 'A')+altered[part][1:]
            with self.assertRaises((ValueError,InvalidSignature)):verify(altered)
        altered=copy.deepcopy(frame);altered['header']['sequence']=2
        with self.assertRaises(InvalidSignature):verify(altered)

    def test_input_budgets_and_canonical_json(self):
        for text in ['{"x":1,"x":2}','{"x":1.5}','{"x":NaN}']:
            with self.assertRaises(ValueError):dna.loads(text)
        for raw in (b'x'*(dna.MAX_GENE_BYTES+1),'not bytes'):
            with self.assertRaises(ValueError):dna.encode_bases(raw)
        for bases in ('ACT','AXGT','acgt'):
            with self.assertRaises(ValueError):dna.decode_bases(bases)
