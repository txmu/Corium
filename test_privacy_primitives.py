"""Real libsodium ABI, group arithmetic and experimental activation boundaries."""
import unittest
import shielded_ownership as s


class PrimitiveTests(unittest.TestCase):
    def test_fixed_ffi_contract_rejects_short_long_and_nonbytes_inputs(self):
        for name,(sizes,_) in s._ZS_OPS.items():
            for index,size in enumerate(sizes):
                for invalid in (b'',bytes(size-1),bytes(size+1),'0'*size,bytearray(size),None):
                    values=[bytes(length) for length in sizes];values[index]=invalid
                    with self.subTest(operation=name,index=index,size=size,kind=type(invalid).__name__),self.assertRaises(ValueError):s.zs_op(name,*values)
        with self.assertRaises(ValueError):s.zs_op('sodium_memzero',bytes(32))
        with self.assertRaises(ValueError):s.zs_op('crypto_core_ristretto255_scalar_reduce')
    def test_real_ristretto_group_and_canonical_scalar_arithmetic(self):
        one=(1).to_bytes(32,'little');two=(2).to_bytes(32,'little');three=(3).to_bytes(32,'little')
        p=s.zs_base(one);q=s.zs_base(two)
        self.assertEqual(s.zs_add(p,q),s.zs_base(three));self.assertEqual(s.zs_sub(q,p),p)
        self.assertEqual(s.zs_sadd(one,two),three);self.assertEqual(s.zs_smul(two,two),(4).to_bytes(32,'little'))
        self.assertEqual(s.zs_ssub(one,one),bytes(32));self.assertEqual(s.zs_mul(bytes(32),p),bytes(32))
        with self.assertRaises(ValueError):s.zs_sadd(bytes([255])*32,one)
        with self.assertRaises(ValueError):s.zs_point(bytes(32))
    def test_libsodium_return_types_and_nonzero_entropy(self):
        lib=s.zs_lib()
        self.assertIsNone(lib.crypto_core_ristretto255_scalar_reduce.restype)
        self.assertIsNotNone(lib.crypto_core_ristretto255_from_hash.restype)
        for _ in range(16):self.assertNotEqual(s.zs_random_scalar(),bytes(32))
    def test_mainnet_remains_unavailable_without_independent_audit(self):
        self.assertFalse(s.ZS_AUDITED)
        for network in ('ziokt-main','mainnet','testnet','test'):
            with self.assertRaisesRegex(ValueError,'testnet-only'):s.zs_testnet(network)
        for network in ('test-audit','dev-local'):s.zs_testnet(network)

if __name__=='__main__':unittest.main()
