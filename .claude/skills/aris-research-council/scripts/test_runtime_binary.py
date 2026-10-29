"""Regression: a live image must survive replacement of the installation entry."""
from pathlib import Path
import tempfile
import unittest
from runtime_binary import pin
from native_pipeline import freeze_advisory
import council


class ImmutableRuntimeTests(unittest.TestCase):
    def test_update_never_replaces_old_pinned_image(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);entry=root/'installed';entry.write_bytes(b'old archive offsets')
            old=pin(entry,root/'runtime');inode=old.stat().st_ino
            entry.write_bytes(b'new archive and different offsets')
            new=pin(entry,root/'runtime')
            self.assertNotEqual(old,new)
            self.assertEqual(old.read_bytes(),b'old archive offsets')
            self.assertEqual(old.stat().st_ino,inode)
            self.assertEqual(pin(entry,root/'runtime'),new)
            new.chmod(0o755);new.write_bytes(b'corrupt')
            with self.assertRaisesRegex(RuntimeError,'integrity'):pin(entry,root/'runtime')

    def test_advisory_retry_ignores_volatile_receipts_but_binds_real_evidence(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);lit=root/'LITERATURE.md';lit.write_text('actual source excerpt')
            evidence=root/'verified.json';papers=[dict(id='p1',source_excerpt='result',verification_status='verified')]
            council.dump(evidence,dict(papers=papers,verification=dict(checked_at=1,raw_logs='/attempt1')))
            first=freeze_advisory(root,'results',lit,evidence,'run1',dict(peer_model='haiku'))
            self.assertFalse(first[0].exists(),'new Council output must remain empty')
            before=(first[1]/'evidence.json').read_bytes()
            council.dump(evidence,dict(papers=papers,verification=dict(checked_at=2,raw_logs='/attempt2')))
            self.assertEqual(first,freeze_advisory(root,'results',lit,evidence,'run1',dict(peer_model='haiku')))
            self.assertEqual(before,(first[1]/'evidence.json').read_bytes())
            papers[0]['source_excerpt']='changed scientific claim';council.dump(evidence,dict(papers=papers))
            self.assertNotEqual(first,freeze_advisory(root,'results',lit,evidence,'run1',dict(peer_model='haiku')))
            self.assertEqual(before,(first[1]/'evidence.json').read_bytes())
            self.assertNotEqual(first,freeze_advisory(root,'results',lit,evidence,'run2',dict(peer_model='haiku')))


if __name__=='__main__':unittest.main()
