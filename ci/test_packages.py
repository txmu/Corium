"""Full source build, signed archive install, rebuild, slots and ABI conflicts."""
import hashlib
import io
import platform
import shlex
import tarfile
from test_core import Fixture
from test_pgp_fixture import OpenPGPFixture

class Packages(Fixture):
    def setUp(self):
        super().setUp()
        self.signer=OpenPGPFixture()
        zone=self.etc/'trust_zones/dev'; zone.mkdir(parents=True); (zone/'keyring.gpg').write_bytes(self.signer.keyring())
        (self.etc/'world').write_text('')
        self.repo=self.root/'repo/dev/hello'; self.repo.mkdir(parents=True)
        configs=self.etc/'repos.conf.d'; configs.mkdir(); (configs/'local.conf').write_text('type=local\npath='+str(self.root/'repo')+'\n')
        self.cache=self.root/'var/cache/corix/binaries'; self.cache.mkdir(parents=True,exist_ok=True)
        self.build=self.repo/'hello.build'

    def binary(self,slot,version=1,path='usr/bin/hello',depends=''):
        self.build.write_text(f'pkgname=hello\npkgver={version}\nslot={slot}\ndepends=({depends})\nsource=()\n')
        archive=self.cache/f'dev_hello-{version}-{slot.replace("/","_")}-{platform.machine()}.corix.tar.gz'
        data=f'#!/bin/sh\necho version-{version}\n'.encode()
        with tarfile.open(archive,'w:gz') as tf:
            item=tarfile.TarInfo(path); item.size=len(data); item.mode=0o755; tf.addfile(item,io.BytesIO(data))
        type(archive)(str(archive)+'.sig.gpg').write_bytes(self.signer.signature(archive.read_bytes()))
        self.run_core('_update_metadata_cache')
        return archive

    def test_source_build_publish_sign_install_rebuild_and_remove(self):
        source=self.repo/'hello.c'; source.write_text('#include <stdio.h>\nint main(void){puts("native-source-ci");return 0;}\n')
        digest=hashlib.sha256(source.read_bytes()).hexdigest()
        self.build.write_text(f'''pkgname=hello
pkgver=1
slot=0
source=(hello.c)
sha256sums=({digest})
depends=()
options=(!network)
build() {{
    gcc hello.c -o hello
}}
package() {{
    mkdir -p "$pkgdir/usr/bin"
    cp hello "$pkgdir/usr/bin/hello"
}}
''')
        self.run_core('SANDBOX_TOOL=bubblewrap; corix_build dev/hello build_result')
        archives=list(self.cache.glob('*.corix.tar.*')); self.assertEqual(len(archives),1)
        archive=archives[0]; type(archive)(str(archive)+'.sig.gpg').write_bytes(self.signer.signature(archive.read_bytes()))
        self.run_core('DEP_MODE=auto; corix_install dev/hello:0')
        target=self.root/'usr/bin/hello'; self.assertIn('native-source-ci',self.run_core(str(target)).stdout)
        expected=self.semantic(); target.unlink()
        self.run_core('DEP_MODE=auto; corix_rebuild_from_world --force')
        self.assertTrue(target.exists()); self.assertIn('native-source-ci',self.run_core(str(target)).stdout)
        self.assertEqual(self.semantic(),expected)
        self.run_core('corix_remove dev/hello:0 <<< y'); self.assertFalse(target.exists())

    def test_parallel_slots_distinct_paths_and_removal_preserves_other_slot(self):
        self.binary('0',path='usr/bin/hello0'); self.run_core('DEP_MODE=auto; corix_install dev/hello:0')
        self.binary('1',path='usr/bin/hello1'); self.run_core('DEP_MODE=auto; corix_install dev/hello:1')
        self.assertTrue((self.root/'usr/bin/hello0').exists()); self.assertTrue((self.root/'usr/bin/hello1').exists())
        self.run_core('corix_remove dev/hello:0 <<< y')
        self.assertFalse((self.root/'usr/bin/hello0').exists()); self.assertTrue((self.root/'usr/bin/hello1').exists())

    def test_different_slot_file_conflict_is_atomic(self):
        self.binary('0'); self.run_core('DEP_MODE=auto; corix_install dev/hello:0')
        before=self.semantic(); contents=(self.root/'usr/bin/hello').read_bytes(); world=(self.etc/'world').read_text()
        self.binary('1',version=2); self.run_core('DEP_MODE=auto; corix_install dev/hello:1',ok=False)
        self.assertEqual(self.semantic(),before); self.assertEqual((self.root/'usr/bin/hello').read_bytes(),contents); self.assertEqual((self.etc/'world').read_text(),world)

    def test_slot_abi_version_dependency_binding(self):
        for slot in ('0/1','0/2'):
            with self.subTest(slot=slot):
                archive=self.binary(slot,path='usr/lib/libhello-'+slot.split('/')[1]+'.so')
                self.run_core('DEP_MODE=auto; corix_install '+shlex.quote('dev/hello:'+slot))
                self.run_core('dep_resolve_topological '+shlex.quote('dev/hello:'+slot))
        self.run_core('dep_resolve_topological dev/hello:0/9',ok=False)

    def test_source_checksum_tamper_rejected_without_installed_state(self):
        source=self.repo/'hello.c'; source.write_text('int main(void){return 0;}\n')
        self.build.write_text('pkgname=hello\npkgver=1\nslot=0\nsource=(hello.c)\nsha256sums=('+('0'*64)+')\ndepends=()\noptions=(!network)\nbuild() { gcc hello.c -o hello; }\npackage() { mkdir -p "$pkgdir/usr/bin"; cp hello "$pkgdir/usr/bin/hello"; }\n')
        before=self.semantic(); self.run_core('SANDBOX_TOOL=bubblewrap; corix_build dev/hello build_result',ok=False)
        self.assertEqual(self.semantic(),before); self.assertFalse((self.root/'usr/bin/hello').exists())
