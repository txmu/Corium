"""Additional integration coverage; only executed on GitHub runners."""
import shlex
import unittest
from test_core import Fixture

class NativeIntegrationTests(Fixture):
    def sandbox(self, command, timeout=10, ok=True):
        build = self.root / 'native build'
        package = self.root / 'native package'
        (build / 'src').mkdir(parents=True, exist_ok=True)
        package.mkdir(exist_ok=True)
        script = (f'SANDBOX_TOOL=bubblewrap; _internal_create_build_sandbox '
                  f'{shlex.quote(str(build))} {shlex.quote(str(package))} '
                  f"'options=!network' {timeout} {shlex.quote(command)}")
        return self.run_core(script, ok=ok), package

    def test_native_build_compiles_and_writes_package_with_space_paths(self):
        result, package = self.sandbox("printf 'int main(void){return 0;}\\n' > main.c; gcc main.c -o /pkg/hello; /pkg/hello")
        self.assertTrue((package / 'hello').is_file(), result.stderr)
        self.assertGreater((package / 'hello').stat().st_size, 0)

    def test_native_build_hides_host_files_and_readonly_system(self):
        secret = self.root / 'host-secret'
        secret.write_text('must not be visible')
        command = f'test ! -e {shlex.quote(str(secret))} && ! touch /usr/corium-write-probe && echo isolated > /pkg/result'
        _, package = self.sandbox(command)
        self.assertEqual((package / 'result').read_text().strip(), 'isolated')
        self.assertEqual(secret.read_text(), 'must not be visible')

    def test_native_build_timeout_is_failure(self):
        result, _ = self.sandbox('sleep 30', timeout=1, ok=False)
        self.assertEqual(result.returncode, 124)

    def test_wiki_missing_page_rejected_without_state_changes(self):
        before = self.semantic()
        self.run_core("corix_wiki show 'missing/不存在'", ok=False)
        self.assertEqual(self.semantic(), before)

    def test_mail_delete_binds_untrusted_identifier(self):
        before = self.semantic()
        self.run_core('corix_mail delete '+shlex.quote("'; DROP TABLE mails; --"))
        self.assertEqual(self.semantic(), before)
        self.run_core('test "$(sqlite3 "$FORUM_DB" "PRAGMA integrity_check;")" = ok')

if __name__ == '__main__':
    unittest.main(verbosity=2)
