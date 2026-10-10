"""SIGKILL and ENOSPC at real filesystem/database transaction boundaries."""
import json
import os
import pathlib
import shlex
import signal
import sqlite3
import subprocess
import time
from test_core import Fixture
from test_gateway import SOURCE

class Faults(Fixture):
    def prepare_transaction(self):
        target=self.root/'usr/bin/tool'; target.parent.mkdir(parents=True); target.write_bytes(b'original\x00\n')
        (self.etc/'world').write_text('dev/tool:0\n')
        (self.root/'manifest').write_text('usr/bin/tool\n')
        return target

    def test_sigkill_restart_rolls_back_uncommitted_files_world_and_databases(self):
        target=self.prepare_transaction(); before=self.semantic()
        marker=self.root/'partial.ready'
        script=('source '+shlex.quote(str(SOURCE))+'\n_begin_transaction "$INSTALLED_DB"; '
                '_transaction_stage_files "$CORIUM_ROOT/manifest"; '
                'printf changed > "$CORIUM_ROOT/usr/bin/tool"; printf changed > "$WORLD_FILE"; '
                'db_execute_safe "$BLOCKCHAIN_DB" "DELETE FROM validators;"; '
                'sync; touch "$CORIUM_ROOT/partial.ready"; sleep 120')
        log=(self.root/'sigkill.log').open('w'); self.addCleanup(log.close)
        proc=subprocess.Popen(['bash','-c',script],env=self.env,stdout=log,stderr=log,start_new_session=True)
        try:
            deadline=time.monotonic()+30
            while time.monotonic()<deadline and not marker.exists() and proc.poll() is None: time.sleep(.05)
            self.assertTrue(marker.exists(),'Never reached the actual transaction fault point')
            os.killpg(proc.pid,signal.SIGKILL); proc.wait(timeout=10)
        finally:
            if proc.poll() is None: os.killpg(proc.pid,signal.SIGKILL); proc.wait()
        # A new production invocation must recover persisted journals by itself.
        self.run_core('_update_chain_state_cache')
        self.assertEqual(target.read_bytes(),b'original\x00\n')
        self.assertEqual((self.etc/'world').read_text(),'dev/tool:0\n')
        self.assertEqual(self.semantic(),before)

    def test_sqlite_write_disk_full_rejected_then_restart_is_consistent(self):
        before=self.semantic(); volume=pathlib.Path(os.environ['CORIUM_FAULT_VOLUME'])
        filler=volume/'fill.bin'
        try:
            # The actual mounted filesystem has no ext4 reserved blocks.
            with filler.open('wb',buffering=0) as stream:
                block=b'x'*(1024*1024)
                while True:
                    try: stream.write(block)
                    except OSError as error:
                        self.assertEqual(error.errno,28); break
            result=self.run_core("db_execute_safe \"$BLOCKCHAIN_DB\" \"INSERT INTO system_params VALUES ('enospc',hex(randomblob(1048576)));\"",ok=False)
            self.assertNotEqual(result.returncode,0)
        finally:
            filler.unlink(missing_ok=True)
        self.run_core('_update_chain_state_cache')
        self.assertEqual(self.semantic(),before)
        for path in (self.chain,self.forum,self.dht):
            with sqlite3.connect(path) as db: self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_disk_full_package_transaction_preserves_existing_files(self):
        target=self.prepare_transaction(); before=self.semantic()
        volume=pathlib.Path(os.environ['CORIUM_FAULT_VOLUME']); filler=volume/'fill.bin'
        try:
            with filler.open('wb',buffering=0) as stream:
                while True:
                    try: stream.write(b'x'*(1024*1024))
                    except OSError as error:
                        self.assertEqual(error.errno,28); break
            self.run_core('_begin_transaction "$INSTALLED_DB"',ok=False)
        finally:
            filler.unlink(missing_ok=True)
        self.assertEqual(target.read_bytes(),b'original\x00\n'); self.assertEqual(self.semantic(),before)
