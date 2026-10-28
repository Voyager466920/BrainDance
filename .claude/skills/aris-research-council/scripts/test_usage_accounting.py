import unittest
from usage_accounting import calculate,total,stream_usage

class UsageAccountingTests(unittest.TestCase):
    def test_resumed_receipt_counts_only_increment_not_historical_session_total(self):
        baseline=dict(input_tokens=100,output_tokens=1000,cache_read_input_tokens=1000000,cache_creation_input_tokens=50000)
        stream=dict(input_tokens=10,output_tokens=90,cache_read_input_tokens=10000,cache_creation_input_tokens=100)
        models={'claude':dict(inputTokens=110,outputTokens=1100,cacheReadInputTokens=1010000,cacheCreationInputTokens=50100)}
        observed,source=calculate(stream,models,baseline)
        self.assertEqual(observed['cache_read_input_tokens'],10000);self.assertEqual(observed['output_tokens'],100)
        self.assertEqual(source,'resumed_provider_delta');self.assertEqual(total(observed),10210)
    def test_interrupted_invocation_preserves_stream_and_cache_breakdown(self):
        stream=stream_usage({'m1':dict(input_tokens=12,output_tokens=30,cache_read_input_tokens=1000,cache_creation_input_tokens=200)})
        observed,source=calculate(stream,None)
        self.assertEqual(total(observed),1242);self.assertEqual(source,'per_invocation_stream')
    def test_per_call_counter_reset_does_not_subtract_old_session_totals(self):
        baseline=dict(input_tokens=10000,output_tokens=10000,cache_read_input_tokens=1000000,cache_creation_input_tokens=1000)
        stream=dict(input_tokens=10,output_tokens=20,cache_read_input_tokens=500,cache_creation_input_tokens=0)
        raw={'claude':dict(inputTokens=10,outputTokens=25,cacheReadInputTokens=500,cacheCreationInputTokens=0)}
        observed,source=calculate(stream,raw,baseline)
        self.assertEqual(total(observed),535);self.assertEqual(source,'provider_counter_reset')

    def test_historical_correction_preserves_calls_raw_receipts_and_is_idempotent(self):
        import json,sqlite3,tempfile
        from pathlib import Path
        from contextlib import contextmanager
        from usage_accounting import reconcile
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);database=root/'tree.sqlite3';ledger=root/'ledger.json';workspace=root/'native'
            class Store:
                db_path=str(database)
                @contextmanager
                def _connect(self):
                    c=sqlite3.connect(database);c.row_factory=sqlite3.Row
                    try:
                        with c:yield c
                    finally:c.close()
            store=Store()
            with store._connect() as c:c.execute('CREATE TABLE research_jobs(id TEXT,config TEXT,run_dir TEXT,project_id TEXT,created_at TEXT)')
            models=[dict(inputTokens=10,outputTokens=20,cacheReadInputTokens=1000,cacheCreationInputTokens=0),dict(inputTokens=15,outputTokens=40,cacheReadInputTokens=3000,cacheCreationInputTokens=0)]
            streams=[dict(input_tokens=10,output_tokens=10,cache_read_input_tokens=1000),dict(input_tokens=5,output_tokens=15,cache_read_input_tokens=2000)]
            keys=[]
            for i in range(2):
                work=root/str(i);work.mkdir();path=work/'native-usage.json';keys.append(str(path))
                (work/'native.stdout.jsonl').write_text('{"session_id":"OFFLINE same resumed session"}\n')
                path.write_text(json.dumps(dict(tokens=[1030,3055][i],usage={'message'+str(i):streams[i]},model_usage={'claude':models[i]})))
                config=dict(native_workspace=str(workspace),session_budget=str(ledger))
                with store._connect() as c:c.execute('INSERT INTO research_jobs VALUES(?,?,?,?,?)',(str(i),json.dumps(config),str(work),'p','2026-01-01T00:00:0'+str(i)))
            ledger.write_text(json.dumps(dict(calls=2,max_calls=10,token_budget=1000000,charges=dict(zip(keys,[1030,3055])),observed=dict(zip(keys,[1030,3055])))))
            changes=reconcile(store,'p');data=json.loads(ledger.read_text());self.assertEqual(data['calls'],2)
            self.assertEqual(sum(data['observed'].values()),3055);self.assertEqual(changes[-1]['after'],2025)
            self.assertTrue((root/'1/native-usage.before-v2.json').is_file());before=ledger.read_bytes()
            self.assertEqual(reconcile(store,'p'),[]);self.assertEqual(ledger.read_bytes(),before)
