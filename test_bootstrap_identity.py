"""A failed seed cannot replace a validated route with a hash of its address."""
import sqlite3,unittest
from test_core import Fixture

class BootstrapIdentityTests(Fixture):
    def bootstrap(self,setup,response):
        self.run_core('''
_p2p_update_node_trust_tier_in_db(){ :; }
dht_server_daemon(){ :; }
mkdir -p "$(dirname "$DAEMON_PID_FILE")"
printf '%s' "$BASHPID" > "$DAEMON_PID_FILE"
DHT_BOOTSTRAP_NODES_STRING=ipv4:127.0.0.1:19999
'''+setup+'\ndht_send_message(){ '+response+'; }\ndht_bootstrap\n')
        with sqlite3.connect(self.dht) as db:return db.execute('SELECT id,address,port FROM nodes').fetchall()
    def test_preserves_established_id_before_ping_and_on_failed_seed(self):
        peer='a'*64
        rows=self.bootstrap('dht_add_node '+peer+' ipv4 127.0.0.1 19999','[ "$1" = '+peer+' ] || exit 9; return 1')
        self.assertEqual(rows,[(peer,'127.0.0.1',19999)])
    def test_new_seed_promotes_temporary_id_to_real_pinned_peer(self):
        peer='b'*64
        rows=self.bootstrap('',"printf 'PONG:"+peer+"'")
        self.assertEqual(rows,[(peer,'127.0.0.1',19999)])
    def test_failed_new_seed_and_self_seed_leave_no_phantom_routes(self):
        self.assertEqual(self.bootstrap('','return 1'),[])
        self.assertEqual(self.bootstrap('alias=$(_internal_hash_text "ipv4:127.0.0.1:19999"); dht_add_node "$alias" ipv4 127.0.0.1 19999','return 1'),[])
        self.assertEqual(self.bootstrap('',"printf 'PONG:"+self.identity+"'"),[])
