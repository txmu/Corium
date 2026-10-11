"""Native application transactions, objects, ACLs, encryption and Phoenix replay."""
import hashlib
import json
import shlex
import sqlite3
import unittest
from test_core import Fixture
import test_core

class Applications(Fixture):
    put_transaction = test_core.CoreTests.put_transaction
    validate_transaction = test_core.CoreTests.validate_transaction

    def transaction(self, kind, payload):
        result = self.run_core('blockchain_create_transaction '+shlex.quote(kind)+' '+shlex.quote(json.dumps(payload, ensure_ascii=False)))
        return result.stdout.splitlines()[-1]

    def mine(self):
        self.run_core('blockchain_mine_block')

    def group(self):
        self.run_core("corix_group create 'CI 群组🙂'")
        self.mine()
        with sqlite3.connect(self.forum) as db:
            return db.execute("SELECT id_hash FROM identity_cache WHERE type='group'").fetchone()[0]

    def phoenix(self):
        with sqlite3.connect(self.chain) as db:
            height = db.execute('SELECT MAX(height) FROM blocks').fetchone()[0]
        before = self.semantic()
        self.snapshot(height=height)
        self.run_core('_internal_rebuild_derived_state')
        self.assertEqual(self.semantic(), before)
        with sqlite3.connect(self.chain) as db:
            db.execute('DELETE FROM blocks'); db.execute('DELETE FROM transactions')
        self.run_core('_internal_import_phoenix_state "$CORIUM_ROOT/snapshot.json"')
        recovered = self.semantic()
        self.assertEqual(recovered['application'], before['application'])
        self.assertEqual({k:v for k,v in recovered['chain'].items() if k not in ('blocks','transactions')},
                         {k:v for k,v in before['chain'].items() if k not in ('blocks','transactions')})

    def test_wiki_create_lock_edit_unlock_objects_attachments_and_phoenix(self):
        gid = self.group()
        page = self.root/'page.md'; page.write_text('初版 "🙂"\n')
        attachments = self.root/'attachments'; attachments.mkdir(); (attachments/'附件.txt').write_text('附件')
        self.run_core('corix_wiki create '+shlex.quote(gid+'/page')+' --file '+shlex.quote(str(page))+' --message first --attach '+shlex.quote(str(attachments)))
        self.mine()
        with sqlite3.connect(self.forum) as db:
            page_tx, version, attach = db.execute('SELECT page_tx_hash,latest_version_hash,attachment_hash FROM wiki_pages').fetchone()
        self.assertEqual(page_tx, version); self.assertRegex(attach, r'^[a-f0-9]{64}$')
        self.assertIn('初版', self.run_core('corix_wiki show '+gid+'/page').stdout)
        self.transaction('wiki_page_lock', {'page_create_tx_hash': page_tx}); self.mine()
        page.write_text('第二版🙂\n')
        content = self.run_core('_p2p_upload_file '+shlex.quote(str(page))).stdout.splitlines()[-1]
        edit = self.transaction('wiki_page_edit', {'page_create_tx_hash':page_tx,'previous_version_hash':version,'content_hash':content,'commit_message':'edit','format':'md'})
        self.mine()
        self.assertIn('第二版', self.run_core('corix_wiki show '+gid+'/page').stdout)
        # Editing releases its lock; acquire another lock to exercise explicit unlock.
        self.transaction('wiki_page_lock', {'page_create_tx_hash':page_tx}); self.mine()
        self.transaction('wiki_page_unlock', {'page_create_tx_hash':page_tx}); self.mine()
        with sqlite3.connect(self.forum) as db:
            self.assertEqual(db.execute('SELECT latest_version_hash,locked_by_user_id FROM wiki_pages').fetchone(), (edit,None))
            self.assertEqual(db.execute('SELECT COUNT(*) FROM wiki_versions').fetchone()[0], 2)
        self.phoenix()

    def test_wiki_nonmember_edit_without_lock_stale_version_rejected(self):
        tx = self.put_transaction('wiki_page_create', {'group_id':'f'*64,'page_slug':'unauthorized','content_hash':'a'*64})
        self.validate_transaction(tx, ok=False)
        with sqlite3.connect(self.chain) as db: db.execute('DELETE FROM transactions WHERE hash=?', (tx,))
        gid = self.group()
        page = self.root/'page.md'; page.write_text('page')
        self.run_core('corix_wiki create '+gid+'/page --file '+str(page)+' --message initial'); self.mine()
        with sqlite3.connect(self.forum) as db:
            page_tx = db.execute('SELECT page_tx_hash FROM wiki_pages').fetchone()[0]
        edit = self.put_transaction('wiki_page_edit', {'page_create_tx_hash':page_tx,'previous_version_hash':'0'*64,'content_hash':'a'*64}, 3)
        self.validate_transaction(edit, ok=False)
        with sqlite3.connect(self.chain) as db: db.execute('DELETE FROM transactions WHERE hash=?', (edit,))
        self.transaction('wiki_page_lock', {'page_create_tx_hash':page_tx}); self.mine()
        edit = self.put_transaction('wiki_page_edit', {'page_create_tx_hash':page_tx,'previous_version_hash':'0'*64,'content_hash':'a'*64}, 3)
        self.validate_transaction(edit, ok=False)

    def test_nomen_register_resolve_transfer_ownership_and_phoenix(self):
        target = self.run_core("_internal_p2p_put_from_stdin <<< 'CI website🙂'").stdout.splitlines()[-1]
        self.transaction('nns_register', {'domain_name':'ci-native','target_hash':target,'proof_of_genesis_contribution':{'burned_amount':0}}); self.mine()
        self.assertEqual(self.run_core('_internal_nns_resolve ci-native').stdout.strip(), target)
        new_owner = 'b'*64
        tx = self.transaction('nns_transfer', {'domain_name':'ci-native','new_owner_id':new_owner,'contribution_tax':{'burned_amount':0}}); self.mine()
        with sqlite3.connect(self.forum) as db:
            self.assertEqual(db.execute("SELECT owner_id FROM nns_records WHERE domain_name='ci-native'").fetchone()[0], new_owner)
        unauthorized = self.put_transaction('nns_transfer', {'domain_name':'ci-native','new_owner_id':self.identity}, 50)
        self.validate_transaction(unauthorized, ok=False)
        self.phoenix()

    def test_nomen_invalid_names_and_missing_contribution_proof(self):
        for index, name in enumerate(['../escape','UPPER','-bad','bad-','a'*64, "x';DROP TABLE nns_records;--"]):
            with self.subTest(name=name):
                tx = self.put_transaction('nns_register', {'domain_name':name,'target_hash':'a'*64,'proof_of_genesis_contribution':{}}, index+1)
                self.validate_transaction(tx, ok=False)
        tx = self.put_transaction('nns_register', {'domain_name':'valid-domain','target_hash':'a'*64}, 99)
        self.validate_transaction(tx, ok=False)

    def test_social_group_policy_membership_leave_and_replay(self):
        gid = self.group()
        self.run_core('corix_group set-policy '+gid+' --join-mode open --desc '+shlex.quote('公开群组🙂')); self.mine()
        self.assertIn('公开群组', self.run_core('corix_group info '+gid).stdout)
        self.run_core('corix_group invite '+gid+' '+('b'*64)); self.mine()
        with sqlite3.connect(self.forum) as db:
            self.assertIn('member', db.execute('SELECT permissions FROM acl_state WHERE acl_id=? AND grantee_id=?',(gid,'b'*64)).fetchone()[0])
        self.run_core('corix_group kick '+gid+' '+('b'*64)); self.mine()
        self.run_core('_is_authorized_by_acl '+gid+' '+('b'*64)+' member', ok=False)
        self.phoenix()

    def test_mail_encrypted_payload_roundtrip_wrong_key_and_tamper(self):
        # RSA is a genuine supported OpenSSL encryption key; the identity defaults to EC.
        key = self.root/'mail-rsa.pem'; pub = self.root/'mail-rsa.pub'
        self.run_core('openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:2048 -out '+str(key)+'; openssl pkey -in '+str(key)+' -pubout -out '+str(pub))
        message = json.dumps({'subject':'私密🙂','body':'正文\n"quoted"','attachments':[]},ensure_ascii=False)
        cipher = self.run_core('_e2ee_encrypt_payload '+shlex.quote(message)+' '+str(pub)).stdout
        decrypted = self.run_core('USER_IDENTITY_FILE='+str(key)+'; _e2ee_decrypt_payload '+shlex.quote(cipher)).stdout
        self.assertEqual(json.loads(decrypted), json.loads(message))
        self.run_core('_e2ee_decrypt_payload '+shlex.quote(cipher), ok=False)
        broken = json.loads(cipher); broken['encrypted_session_key'] = 'AAAA'
        self.run_core('_e2ee_decrypt_payload '+shlex.quote(json.dumps(broken)), ok=False)

    def test_mail_native_identity_send_read_attachment_mine_and_phoenix(self):
        attachment = self.root/'附件🙂.bin'; attachment.write_bytes(b'\x00\xff\n')
        self.run_core('corix_mail send '+self.identity+' --subject '+shlex.quote('私密🙂')+' --body '+shlex.quote('正文🙂')+' --attach '+shlex.quote(str(attachment)))
        self.mine()
        with sqlite3.connect(self.forum) as db:
            tx = db.execute('SELECT tx_hash FROM mails WHERE recipient_id=?',(self.identity,)).fetchone()[0]
        output = self.run_core('corix_mail read '+tx).stdout
        self.assertIn('正文🙂',output); self.assertIn('附件🙂.bin',output)
        self.phoenix()

    def test_maillist_plaintext_object_inbox_delete_and_phoenix(self):
        gid = self.group()
        self.run_core('corix_maillist post '+gid+' --subject '+shlex.quote('列表🙂')+' --body '+shlex.quote('公开正文🙂')); self.mine()
        with sqlite3.connect(self.forum) as db:
            tx = db.execute('SELECT tx_hash FROM mails WHERE recipient_id=?',(gid,)).fetchone()[0]
        self.assertIn('公开正文🙂', self.run_core('corix_mail read '+tx).stdout)
        self.assertIn('列表🙂', self.run_core('corix_maillist archive '+gid).stdout)
        self.phoenix()
        self.run_core('corix_mail delete '+tx)
        with sqlite3.connect(self.forum) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM mails WHERE tx_hash=?',(tx,)).fetchone()[0],0)
