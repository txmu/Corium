"""Actual Btrfs/ZFS product snapshot lifecycle on disposable loopback storage."""
import os
from contextlib import closing
import pathlib
import shutil
import sqlite3
import subprocess
from test_core import Fixture

class Filesystems(Fixture):
    def command(self,*args):
        subprocess.run(args,check=True)

    def setUp(self):
        super().setUp()
        self.backend=os.environ['CORIUM_FS_BACKEND']
        (self.etc/'world').write_text('')
        old=self.root/'original-state'; self.base.rename(old)
        if self.backend=='btrfs':
            self.command('btrfs','subvolume','create',str(self.base))
            self.addCleanup(self.cleanup_btrfs)
        elif self.backend=='zfs':
            self.dataset=os.environ['CORIUM_ZPOOL']+'/case'
            self.command('zfs','create','-o','mountpoint='+str(self.base),self.dataset)
            self.addCleanup(self.command,'zfs','destroy','-rf',self.dataset)
        else:
            raise AssertionError('Unknown real backend '+self.backend)
        shutil.copytree(old,self.base,dirs_exist_ok=True); shutil.rmtree(old)
        self.expected=self.semantic()

    def cleanup_btrfs(self):
        # Delete only subvolumes inside this case before TemporaryDirectory cleanup.
        roots = [self.root]
        directories = [p for p in self.root.rglob('*') if p.is_dir() and not p.is_symlink()]
        for path in sorted(directories, key=lambda p:len(p.parts), reverse=True):
            probe=subprocess.run(['btrfs','subvolume','show',str(path)],capture_output=True)
            if probe.returncode==0:
                subprocess.run(['btrfs','subvolume','delete',str(path)],check=True)

    def native_reference_snapshot(self):
        target=self.base/'snapshots/native'; target.mkdir(parents=True)
        shutil.copytree(self.etc,target/'etc')
        (target/'snapshot.meta').write_text('name=native\ntype='+self.backend+'\ncorix_version=108\n')
        if self.backend=='btrfs':
            self.command('btrfs','subvolume','snapshot','-r',str(self.base),str(target/'var'))
        else:
            self.command('zfs','snapshot',self.dataset+'@corix_native')
        return target

    def test_product_create_uses_actual_backend(self):
        self.run_core('corix_snapshot_create created')
        meta=(self.base/'snapshots/created/snapshot.meta').read_text()
        self.assertIn('type='+self.backend,meta,'Backend silently fell back to rsync')
        if self.backend=='btrfs':
            self.command('btrfs','subvolume','show',str(self.base/'snapshots/created/var'))
        else:
            self.command('zfs','list','-t','snapshot',self.dataset+'@corix_created')

    def test_product_rollback_restores_database_configuration_and_installed_state(self):
        self.native_reference_snapshot()
        (self.etc/'world').write_text('#changed\n')
        with closing(sqlite3.connect(self.chain)) as db, db: db.execute('DELETE FROM validators')
        self.run_core('corix_snapshot_rollback native <<< y')
        self.assertEqual(self.semantic(),self.expected)
        self.assertEqual((self.etc/'world').read_text(),'')
        for path in (self.chain,self.forum,self.dht):
            with closing(sqlite3.connect(path)) as db: self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_product_delete_destroys_real_snapshot(self):
        target=self.native_reference_snapshot()
        self.run_core('corix_snapshot_delete native <<< y')
        self.assertFalse(target.exists())
        if self.backend=='zfs':
            self.assertNotEqual(subprocess.run(['zfs','list','-t','snapshot',self.dataset+'@corix_native'],capture_output=True).returncode,0)

    def test_corrupt_snapshot_metadata_rollback_fails_without_changes(self):
        target=self.native_reference_snapshot()
        (target/'snapshot.meta').write_text('name=native\ntype='+self.backend+'\ncorix_version=999\n')
        self.run_core('corix_snapshot_rollback native <<< y',ok=False)
        self.assertEqual(self.semantic(),self.expected)
