"""Real distro rootfs, native PM lifecycle and Corium Strata APIs."""
import os
import pathlib
import shlex
import shutil
import subprocess
import tarfile
from test_core import Fixture
from test_gateway import SOURCE

class Strata(Fixture):
    def run_core(self, script, ok=True):
        result=subprocess.run(['bash','-c','source '+shlex.quote(str(SOURCE))+'\nSANDBOX_TOOL=bwrap; STRATA_HOME_MODE=none; STRATA_EXPOSE_HOST_PKGCACHE=0; '+script],env=self.env,capture_output=True,text=True,timeout=1800)
        if ok and result.returncode: self.fail(script+'\n'+result.stdout+result.stderr)
        if not ok and not result.returncode: self.fail('Invalid operation accepted: '+script)
        return result

    def setUp(self):
        super().setUp()
        self.pm=os.environ['CORIUM_STRATA_PM']
        self.strata=self.root/'usr/corix/strata/networks/default/native'
        self.strata.mkdir(parents=True)
        # docker export supplies the actual filesystem and package database.
        subprocess.run(['tar','--numeric-owner','-xf',os.environ['CORIUM_STRATA_ROOTFS'],'-C',str(self.strata)],check=True)
        (self.strata/'.corix_strata').write_text('name=native\npm='+self.pm+'\ncorix_version=108\n')
        (self.etc/'world').write_text('')
        self.env['SANDBOX_TOOL']='bwrap'
        self.env['STRATA_HOME_MODE']='none'
        self.env['STRATA_EXPOSE_HOST_PKGCACHE']='0'

    def test_native_manager_install_query_export_promote_rebuild_remove_destroy(self):
        commands={
            'apt':('apt-get update && apt-get install -y hello','dpkg-query -W hello','apt-get remove -y hello'),
            'pacman':('pacman -Syu --noconfirm hello','pacman -Q hello','pacman -R --noconfirm hello'),
            'dnf':('dnf install -y hello','rpm -q hello','dnf remove -y hello'),
            'portage':('emerge --sync && emerge --ask=n app-portage/gentoolkit app-misc/hello','equery list app-misc/hello','emerge --unmerge app-misc/hello'),
        }
        install,query,remove=commands[self.pm]
        self.run_core('corix_strata_execute native '+shlex.quote(install))
        self.assertIn('hello',self.run_core('corix_strata_execute native '+shlex.quote(query)).stdout)
        exported=self.run_core('corix_strata_export_pkgs native').stdout
        self.assertIn('hello',exported)
        self.run_core('corix_strata_promote native')
        world=(self.etc/'world').read_text(); self.assertIn('strata:native:'+self.pm,world); self.assertIn('hello',world)
        self.run_core('corix_strata_promote native'); self.assertEqual((self.etc/'world').read_text(),world)
        self.run_core('corix_rebuild_from_world --force')
        self.run_core('corix_strata_execute native '+shlex.quote(remove))
        self.run_core('corix_strata_execute native '+shlex.quote(query),ok=False)
        self.run_core('corix_strata_destroy native <<< y'); self.assertFalse(self.strata.exists())

    def test_native_create_supported_backend(self):
        # The actual creation path is independent of the pre-provisioned lifecycle.
        arguments={'apt':'apt https://deb.debian.org/debian bookworm','pacman':'pacman','dnf':'dnf 43','portage':'portage'}
        self.run_core('mkdir -p "$STRATA_DIR" "$SOURCE_CACHE"; corix_strata_create created '+arguments[self.pm])
        created=self.strata.parent/'created'
        self.assertTrue((created/'.corix_strata').exists())
        self.assertIn('pm='+self.pm,(created/'.corix_strata').read_text())
        self.run_core('corix_strata_execute created /bin/sh -c '+shlex.quote('test -e /etc/os-release'))
        self.run_core('corix_strata_destroy created <<< y'); self.assertFalse(created.exists())

    def test_path_traversal_and_missing_strata_fail(self):
        before=(self.etc/'world').read_text()
        self.run_core('corix_strata_create ../escape '+self.pm,ok=False)
        self.run_core('corix_strata_execute missing /bin/true',ok=False)
        self.assertEqual((self.etc/'world').read_text(),before)
