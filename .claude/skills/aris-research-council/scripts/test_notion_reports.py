"""Real local APIs, rendered PNGs, and a protocol fixture; no paid accounts/GPU."""
import json
import io
import os
import threading
import time
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid
import urllib.error

import terminal
import test_terminal as fixtures
from notion_reports import NotionAPI,NotionError,PublicationService,blocks_for,page_id,block_signature
from research_reports import build_report,project_data,report_html,signature
from tree_store import now

PARENT='11111111-2222-4333-8444-555555555555'
TOKEN='ntn_private_fixture_token_not_a_live_secret'
PUBLICATION_LOOP=PublicationService.loop


class RemoteFixture:
    def __init__(self):
        self.blocks={PARENT:[]};self.calls=[];self.uploads={};self.fail_after_append=False;self.fail_after_create=False
        self.databases={};self.sources={};self.entries={};self.views=[];self.pages={};self.query_page_size=100;self.fail_after_move=False

    def request(self,api,method,path,payload=None,content_type=None):
        self.calls.append((method,path,payload))
        if path=='/users/me':return dict(bot=dict(workspace_name='Fixture workspace'))
        if method=='GET' and path.startswith('/pages/'):return self.pages.get(path.split('/')[2],dict(id=PARENT,archived=False))
        if method=='POST' and path.endswith('/move'):
            identity=path.split('/')[2];record=self.pages[identity]
            for source,rows in self.entries.items():self.entries[source]=[r for r in rows if r['id']!=identity]
            record['parent']=payload['parent'];title=record['properties']['제목']['title'][0]['text']['content']
            self.blocks[payload['parent']['page_id']].append(dict(id=identity,type='child_page',child_page=dict(title=title)))
            if self.fail_after_move:self.fail_after_move=False;raise NotionError('Fixture lost move response',retryable=True)
            return record
        if method=='POST' and path=='/databases':
            identity=str(uuid.uuid4());source=str(uuid.uuid4());props={name:{**definition,'id':'property-'+str(i),'type':next(iter(definition))} for i,(name,definition) in enumerate(payload['initial_data_source']['properties'].items())}
            record=dict(id=identity,data_sources=[dict(id=source)]);self.databases[identity]=record;self.sources[source]=dict(id=source,properties=props);self.entries[source]=[]
            self.blocks[payload['parent']['page_id']].append(dict(id=identity,type='child_database',child_database=dict(title=payload['title'][0]['text']['content'])))
            if self.fail_after_create:self.fail_after_create=False;raise NotionError('Fixture lost database create response',retryable=True)
            return record
        if method=='GET' and path.startswith('/databases/'):return self.databases[path.split('/')[2]]
        if method=='GET' and path.startswith('/data_sources/'):return self.sources[path.split('/')[2]]
        if method=='GET' and path.startswith('/views?'):return dict(results=[dict(object='view',id=v['id']) for v in self.views],has_more=False)
        if method=='GET' and path.startswith('/views/'):return next(v for v in self.views if v['id']==path.split('/')[2])
        if method=='POST' and path=='/views':
            view=dict(id=str(uuid.uuid4()),**payload);self.views.append(view);return view
        if method=='POST' and path.startswith('/data_sources/'):
            condition=payload['filter']['rich_text'];rows=self.entries[path.split('/')[2]]
            rows=[r for r in rows if (r['properties']['보고서 키']['rich_text'][0]['text']['content']==condition['equals'] if 'equals' in condition else r['properties']['보고서 키']['rich_text'][0]['text']['content'].startswith(condition['starts_with']))]
            start=int(payload.get('start_cursor',0));end=start+self.query_page_size
            return dict(results=rows[start:end],has_more=end<len(rows),next_cursor=str(end) if end<len(rows) else None)
        if method=='GET' and path.startswith('/blocks/'):
            identity=path.split('/')[2];return dict(results=self.blocks[identity],has_more=False)
        if method=='POST' and path=='/pages':
            if payload['parent'].get('type')=='data_source_id':
                identity=str(uuid.uuid4());self.blocks[identity]=[]
                record=dict(id=identity,properties=payload['properties'],parent=payload['parent']);self.pages[identity]=record;self.entries[payload['parent']['data_source_id']].append(record)
                if self.fail_after_create:self.fail_after_create=False;raise NotionError('Fixture lost entry create response',retryable=True)
                return record
            identity=str(uuid.uuid4());title=payload['properties']['title']['title'][0]['text']['content']
            self.blocks[identity]=[];self.blocks[payload['parent']['page_id']].append(dict(id=identity,type='child_page',child_page=dict(title=title)))
            if self.fail_after_create:self.fail_after_create=False;raise NotionError('Fixture lost creation response',retryable=True)
            return dict(id=identity)
        if method=='POST' and path=='/file_uploads':
            identity=str(uuid.uuid4());self.uploads[identity]=payload;return dict(id=identity,status='pending',upload_url='https://untrusted.invalid/never-follow')
        if method=='POST' and path.startswith('/file_uploads/'):
            self.uploads[path.split('/')[2]]['sent']=payload
            assert 'multipart/form-data; boundary=' in content_type
            return dict(status='uploaded')
        if method=='PATCH' and path.startswith('/pages/'):
            self.pages[path.split('/')[2]]['properties'].update(payload['properties']);return self.pages[path.split('/')[2]]
        if method=='PATCH':
            blocks=json.loads(json.dumps(payload['children']))
            for block in blocks:
                block['id']=str(uuid.uuid4())
                if block['type']=='toggle':self.blocks[block['id']]=[]
            target=self.blocks[path.split('/')[2]]
            if payload.get('position',{}).get('type')=='start':target[0:0]=blocks
            elif payload.get('position',{}).get('type')=='after_block':
                offset=next(i for i,b in enumerate(target) if b['id']==payload['position']['after_block']['id'])+1;target[offset:offset]=blocks
            else:target.extend(blocks)
            if self.fail_after_append:self.fail_after_append=False;raise NotionError('Fixture lost append response',retryable=True)
            return dict(results=blocks)
        raise AssertionError((method,path))


class PublicationTests(unittest.TestCase):
    def setUp(self):
        stop=patch('notion_reports.PublicationService.loop',return_value=None);stop.start();self.addCleanup(stop.stop)
        self.fixture=fixtures.TerminalTests('test_source_command_json_does_not_emit_logo_or_color');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.server,self.client,self.project=self.fixture.server,self.fixture.client,self.fixture.project
        self.service=self.server.publications;self.remote=RemoteFixture()
        request=patch.object(NotionAPI,'request',autospec=True,side_effect=self.remote.request);request.start();self.addCleanup(request.stop)

    def configure(self,automatic=False,layout='pages'):
        return self.client.request('/api/notion/configure',dict(project_id=self.project['id'],parent=PARENT,token=TOKEN,auto_sync=automatic,layout=layout))

    def test_database_calendar_and_date_sorted_reports_are_idempotent_and_include_charts(self):
        self.add_measurement();self.configure(True,layout='database')
        job=self.service.enqueue(self.project['id'],True);state=self.run_job(job)
        self.assertEqual(len(self.remote.databases),1);self.assertEqual(len(self.remote.views),2)
        self.assertEqual([v['type'] for v in self.remote.views],['table','calendar'])
        self.assertEqual(self.remote.views[0]['sorts'],[dict(property='날짜',direction='descending')])
        entry=next(iter(self.remote.entries.values()))[0];props=entry['properties']
        self.assertRegex(props['날짜']['date']['start'],r'^\d{4}-\d{2}-\d{2}T');self.assertEqual(props['정상 측정']['number'],1)
        self.assertTrue(any(b['type']=='image' for b in self.remote.blocks[state['jobs'][0]['section_id']]))
        self.assertEqual(self.service.enqueue(self.project['id'],True)['id'],job['id'])
        self.assertEqual(len(next(iter(self.remote.entries.values()))),1)
        self.assertNotIn(TOKEN,json.dumps(state))

    def test_uncertain_database_and_row_creates_reconcile_without_duplicates(self):
        self.configure(layout='database');job=self.service.enqueue(self.project['id'],True)
        self.remote.fail_after_create=True
        with self.assertRaises(NotionError):self.run_job(job)
        self.remote.fail_after_create=True
        with self.assertRaises(NotionError):self.run_job(job)
        self.remote.fail_after_append=True
        with self.assertRaises(NotionError):self.run_job(job)
        self.run_job(job)
        self.assertEqual(len(self.remote.databases),1);self.assertEqual(len(next(iter(self.remote.entries.values()))),1)

    def test_database_date_uses_korea_day_across_utc_midnight(self):
        api=NotionAPI(TOKEN);destination=api.research_database(PARENT)
        identity=api.research_entry(destination,dict(project_id=self.project['id'],digest='offline-date-fixture',title='Date fixture',created_at='2026-10-28T16:30:00+00:00'),dict(runs=[]))
        entry=next(r for r in next(iter(self.remote.entries.values())) if r['id']==identity)
        self.assertTrue(entry['properties']['날짜']['date']['start'].startswith('2026-10-29T'))

    def test_changed_results_and_renaming_reuse_project_page_and_preserve_manual_content(self):
        self.add_measurement();self.configure(layout='database');first=self.run_job(self.service.enqueue(self.project['id'],True))
        page=first['jobs'][0]['page_id'];section=first['jobs'][0]['section_id'];saved=json.dumps(self.remote.blocks[section],sort_keys=True)
        self.remote.blocks[page].append(dict(type='paragraph',paragraph=dict(rich_text=[dict(text=dict(content='HUMAN NOTE'))])))
        with self.server.store._connect() as c:c.execute('UPDATE projects SET title=? WHERE id=?',('Renamed project',self.project['id']))
        self.add_measurement();second=self.run_job(self.service.enqueue(self.project['id'],True))
        self.assertEqual(second['jobs'][0]['page_id'],page);self.assertNotEqual(second['jobs'][0]['section_id'],section)
        entries=next(iter(self.remote.entries.values()));self.assertEqual(len(entries),1)
        self.assertEqual(entries[0]['properties']['제목']['title'][0]['text']['content'],'Renamed project')
        self.assertEqual(entries[0]['properties']['정상 측정']['number'],2)
        self.assertEqual(json.dumps(self.remote.blocks[section],sort_keys=True),saved)
        self.assertTrue(any(block_signature(b)==('paragraph','HUMAN NOTE') for b in self.remote.blocks[page]))
        self.assertEqual(self.remote.blocks[page][0]['id'],second['jobs'][0]['section_id'])

    def test_identical_titles_in_different_projects_never_share_a_page(self):
        api=NotionAPI(TOKEN);destination=api.research_database(PARENT)
        record=dict(project_id=self.project['id'],digest='first',title='Same title',created_at='2026-10-28T12:00:00+00:00')
        one=api.research_entry(destination,record,dict(runs=[]));record={**record,'project_id':str(uuid.uuid4())}
        two=api.research_entry(destination,record,dict(runs=[]));self.assertNotEqual(one,two)
        self.assertEqual(len(next(iter(self.remote.entries.values()))),2)

    def test_legacy_rows_are_moved_intact_and_uncertain_move_reconciles_with_pagination(self):
        self.configure(layout='database');api=NotionAPI(TOKEN);destination=api.research_database(PARENT)
        legacy=[]
        for i in range(3):
            properties={'제목':{'title':[dict(text=dict(content='Previous '+str(i)))]},'보고서 키':{'rich_text':[dict(text=dict(content=self.project['id']+':legacy-'+str(i)))]}}
            row=api.request('POST','/pages',dict(parent=dict(type='data_source_id',data_source_id=destination['data_source_id']),properties=properties));legacy.append(row['id'])
            self.remote.blocks[row['id']]=[dict(type='paragraph',paragraph=dict(rich_text=[dict(text=dict(content='HUMAN '+str(i)))]))]
        properties={'제목':{'title':[dict(text=dict(content='Unrelated'))]},'보고서 키':{'rich_text':[dict(text=dict(content=str(uuid.uuid4())+':legacy'))]}}
        unrelated=api.request('POST','/pages',dict(parent=dict(type='data_source_id',data_source_id=destination['data_source_id']),properties=properties))['id']
        preserved={i:json.dumps(self.remote.blocks[i],sort_keys=True) for i in legacy};self.remote.query_page_size=1;self.remote.fail_after_move=True
        job=self.service.enqueue(self.project['id'],True)
        with self.assertRaises(NotionError):self.run_job(job)
        state=self.run_job(job);canonical=state['jobs'][0]['page_id'];remaining=next(iter(self.remote.entries.values()))
        self.assertEqual({r['id'] for r in remaining},{canonical,unrelated})
        archive=next(b['id'] for b in self.remote.blocks[canonical] if b['type']=='child_page')
        self.assertEqual({b['id'] for b in self.remote.blocks[archive]},set(legacy))
        self.assertTrue(all(self.remote.pages[i]['parent']['page_id']==archive and json.dumps(self.remote.blocks[i],sort_keys=True)==preserved[i] for i in legacy))
        self.assertFalse(any(method=='DELETE' for method,_,_ in self.remote.calls))

    def test_old_completed_job_is_queued_once_for_project_page_migration(self):
        self.configure(layout='database');job=self.service.enqueue(self.project['id'],True)
        self.service.update(job['id'],'completed','Old publisher',page_id=str(uuid.uuid4()))
        self.assertEqual(self.service.enqueue(self.project['id'],True)['state'],'queued')
        state=self.run_job(job);self.assertIsNotNone(state['jobs'][0]['section_id'])
        self.assertEqual(self.service.enqueue(self.project['id'],True)['state'],'completed')

    def test_retry_of_an_older_report_cannot_regress_latest_metadata_or_section_order(self):
        api=NotionAPI(TOKEN);destination=api.research_database(PARENT)
        latest=dict(project_id=self.project['id'],digest='latest',title='Latest title',created_at='2026-10-29T14:00:00+00:00')
        page=api.research_entry(destination,latest,dict(runs=[]));latest_section=api.report_section(page,latest)
        old={**latest,'digest':'old','title':'Old title','created_at':'2026-10-28T14:00:00+00:00'}
        self.assertEqual(api.research_entry(destination,old,dict(runs=[])),page);old_section=api.report_section(page,old)
        self.assertEqual(self.remote.pages[page]['properties']['제목']['title'][0]['text']['content'],'Latest title')
        self.assertEqual([b['id'] for b in self.remote.blocks[page]],[latest_section,old_section])

    def test_manual_edit_within_a_report_is_preserved_and_retry_does_not_create_another_section(self):
        self.configure(layout='database');job=self.service.enqueue(self.project['id'],True);state=self.run_job(job)
        page=state['jobs'][0]['page_id'];section=state['jobs'][0]['section_id'];before=len(self.remote.blocks[page])
        self.remote.blocks[section][0]['heading_2']['rich_text'][0]['text']['content']='HUMAN EDIT'
        with self.assertRaisesRegex(ValueError,'수동 변경'):self.run_job(job)
        self.assertEqual(len(self.remote.blocks[page]),before);self.assertEqual(block_signature(self.remote.blocks[section][0]),('heading_2','HUMAN EDIT'))

    def test_network_failure_retries_durably_without_a_human_resend(self):
        self.configure(layout='database');job=self.service.enqueue(self.project['id'],True);self.remote.fail_after_create=True
        worker=threading.Thread(target=PUBLICATION_LOOP,args=(self.service,),daemon=True);worker.start()
        try:
            deadline=time.monotonic()+5;retried=False
            while time.monotonic()<deadline:
                with self.service.connect() as conn:row=dict(conn.execute('SELECT * FROM jobs WHERE id=?',(job['id'],)).fetchone())
                if row['attempts']:
                    retried=True
                    with self.service.connect() as conn:conn.execute('UPDATE jobs SET next_retry=0 WHERE id=?',(job['id'],))
                if row['state']=='completed':break
                time.sleep(.02)
            self.assertTrue(retried);self.assertEqual(row['state'],'completed')
            self.assertEqual(len(self.remote.databases),1);self.assertEqual(len(next(iter(self.remote.entries.values()))),1)
        finally:self.service.stop.set();worker.join(3)

    def run_job(self,response):
        with self.service.connect() as conn:job=dict(conn.execute('SELECT * FROM jobs WHERE id=?',(response['id'],)).fetchone())
        self.service.process(job)
        return self.service.state(self.project['id'])

    def add_measurement(self,state='succeeded'):
        engine=self.server.experiments;node=self.client.root(self.project)
        plan=engine.create(dict(node_id=node['id'],title='Retained fixture measurement',timeout_seconds=2,code='print(1)',metric='accuracy',direction='maximize'))
        approval=engine.approve(plan['id'],plan['digest'],True);identity=str(uuid.uuid4())
        run_dir=engine.root/identity;run_dir.mkdir()
        result=dict(metrics=dict(baseline=dict(accuracy=.65),candidate=dict(accuracy=.8)),analysis=dict(status='compared',baseline=.65,candidate=.8,delta=.15))
        with self.server.store._connect() as conn:
            conn.execute('INSERT INTO experiment_runs(id,experiment_id,approval_id,project_id,epoch,state,timeout_seconds,queued_at,started_at,finished_at,exit_code,duration_seconds,run_dir,result,error) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(identity,plan['id'],approval['id'],self.project['id'],'fixture',state,2,now(),now(),now(),0,1,str(run_dir),json.dumps(result),None))
        return identity

    def test_page_url_and_credentials_are_private_and_unchanged_project_is_idempotent(self):
        self.assertEqual(page_id('https://app.notion.com/p/ExampleResearch-11111111222243338444555555555555?source=copy_link'),PARENT)
        for url in ['http://notion.so/'+PARENT,'https://notion.so.evil.invalid/'+PARENT,'https://example.com/'+PARENT]:
            with self.assertRaises(ValueError):page_id(url)
        state=self.configure();self.assertTrue(state['connected'])
        self.assertEqual(os.stat(self.service.secret).st_mode&0o777,0o600)
        self.assertNotIn(TOKEN,json.dumps(state));self.assertNotIn(TOKEN,json.dumps(self.server.store.export_json()))
        first=self.client.request('/api/reports/build',dict(project_id=self.project['id']));state=self.run_job(first)
        again=self.client.request('/api/reports/build',dict(project_id=self.project['id']))
        self.assertEqual(first['id'],again['id']);self.assertEqual(state['report']['charts'],[])
        rows=self.client.messages(self.project);self.assertEqual(rows[-1]['role'],'report')
        self.assertEqual(signature(project_data(self.server.store,self.project['id'])),state['report']['digest'])

    def test_unconnected_destination_can_be_saved_without_claiming_connection(self):
        state=self.client.request('/api/notion/configure',dict(project_id=self.project['id'],parent=PARENT))
        self.assertFalse(state['connected']);self.assertEqual(state['link']['parent_id'],PARENT)
        self.assertFalse(self.remote.calls)
        with self.assertRaises(terminal.ClientError):self.client.request('/api/notion/sync',dict(project_id=self.project['id']))

    def test_measured_plot_preserves_values_and_has_local_and_notion_images(self):
        identity=self.add_measurement();self.configure()
        state=self.run_job(self.client.request('/api/notion/sync',dict(project_id=self.project['id'])))
        report=state['report'];self.assertEqual(len(report['charts']),1)
        chart=report['charts'][0];self.assertEqual(chart['rows'][0]['run_id'],identity)
        self.assertEqual(chart['rows'][0]['values'],[['Baseline',.65],['Candidate',.8]])
        png=self.service.file(self.project['id'],report['digest'],chart['file']);self.assertTrue(png.read_bytes().startswith(b'\x89PNG'))
        from PIL import Image
        with Image.open(png) as image:self.assertGreater(image.size[0],1000)
        query='?project_id='+self.project['id']+'&digest='+report['digest']+'&file='
        self.assertIn('image/png',self.client.opener.open(self.client.url+'/api/reports/file'+query+chart['file']).headers['Content-Type'])
        self.assertEqual(state['jobs'][0]['state'],'completed')
        page=state['jobs'][0]['section_id'];self.assertTrue(any(b['type']=='image' for b in self.remote.blocks[page]))
        self.assertEqual(len(self.remote.uploads),2)
        self.assertNotIn(TOKEN,self.service.file(self.project['id'],report['digest'],'results.json').read_text())
        self.assertFalse(any('untrusted.invalid' in path for _,path,_ in self.remote.calls))

    def test_partial_remote_write_is_reconciled_without_duplicate_pages_or_blocks(self):
        self.configure();response=self.service.enqueue(self.project['id'],True)
        self.remote.fail_after_create=True
        with self.assertRaises(NotionError):self.run_job(response)
        self.service.update(response['id'],'failed','Fixture retry')
        self.remote.fail_after_append=True
        with self.assertRaises(NotionError):self.run_job(self.service.enqueue(self.project['id'],True))
        self.service.update(response['id'],'failed','Fixture retry')
        state=self.run_job(self.service.enqueue(self.project['id'],True));page=state['jobs'][0]['section_id']
        self.assertEqual(len(self.remote.blocks),3) # parent, project page, report section
        self.assertEqual(len(self.remote.blocks[page]),len(blocks_for(state['report']))+1)
        calls=len(self.remote.calls);again=self.service.enqueue(self.project['id'],True)
        self.assertEqual(again['state'],'completed');self.assertEqual(len(self.remote.calls),calls)

    def test_report_excludes_other_projects_and_raw_runtime_secrets_and_escapes_html(self):
        other=self.fixture.call('new','Foreign project','--goal','FOREIGN_REPORT_SENTINEL')
        node=self.client.root(self.project)
        self.server.store.update_node(node['id'],metadata=dict(idea='A finding <script>alert(1)</script> '+TOKEN,token=TOKEN,config=dict(password=TOKEN)))
        self.server.store.add_note(node['id'],'result','Raw receipt','RAW_PRIVATE_RECEIPT '+TOKEN)
        self.server.store.add_note(node['id'],'analysis','Structured report',json.dumps(dict(summary='RESEARCH_FINDING',config=dict(secret='PRIVATE_CONFIGURATION_SENTINEL'),code='PRIVATE_SOURCE_CODE_SENTINEL',metrics=dict(tokens_per_second=123))))
        data=project_data(self.server.store,self.project['id']);serialized=json.dumps(data)
        self.assertNotIn(TOKEN,serialized);self.assertNotIn('FOREIGN_REPORT_SENTINEL',serialized);self.assertNotIn('RAW_PRIVATE_RECEIPT',serialized)
        self.assertNotIn('PRIVATE_CONFIGURATION_SENTINEL',serialized);self.assertNotIn('PRIVATE_SOURCE_CODE_SENTINEL',serialized)
        self.assertIn('RESEARCH_FINDING',serialized);self.assertIn('tokens_per_second: 123',serialized)
        report=build_report(self.service.root,data);preview=report_html(report)
        self.assertNotIn(b'<script>',preview);self.assertIn(b'&lt;script&gt;',preview)
        with self.assertRaises(ValueError):self.service.file(self.project['id'],report['digest'],'../../credentials.json')
        with self.assertRaises(ValueError):self.service.file(other['project_id'],report['digest'],'report.md')

    def test_failed_runs_never_get_a_successful_comparison_chart(self):
        self.add_measurement('failed');record=build_report(self.service.root,project_data(self.server.store,self.project['id']))
        self.assertEqual(record['charts'],[])
        self.assertIn('failed',self.service.file(self.project['id'],record['digest'],'report.md').read_text())

    def test_auto_sync_has_no_feedback_loop_and_disconnect_stops_future_publication(self):
        self.add_measurement();self.configure(True);self.service.tick()
        with self.service.connect() as conn:job=dict(conn.execute('SELECT * FROM jobs').fetchone())
        self.run_job(job);self.service.tick()
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],1)
        self.client.request('/api/notion/disconnect',{});self.assertFalse(self.service.secret.exists())
        self.server.store.add_note(self.client.root(self.project)['id'],'analysis','New finding','New observation')
        self.service.tick()
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_global_setup_needs_no_project_and_future_projects_inherit_connection(self):
        self.server.store.set_project_deleted(self.project['id'],True)
        with patch.object(self.client,'project',side_effect=AssertionError('Global Notion setup must not select projects')),patch('sys.stdin.isatty',return_value=True),patch('getpass.getpass',return_value=TOKEN):
            state=terminal.dispatch(self.client,terminal.parser().parse_args(['notion','setup','--parent',PARENT]))
            self.assertEqual(state['scope'],'all_projects');self.assertTrue(state['connected']);self.assertTrue(state['link']['auto_sync'])
        record=terminal.dispatch(self.client,terminal.parser().parse_args(['new','Future Notion project','--goal','OFFLINE fixture']))
        saved=self.service.state(record['project_id']);self.assertTrue(saved['connected']);self.assertEqual(saved['link']['parent_id'],PARENT);self.assertTrue(saved['link']['auto_sync'])
        self.assertNotIn(TOKEN,json.dumps(self.server.store.export_json()))

    def test_persistent_global_connection_survives_restart_and_disconnect_is_global(self):
        self.configure(True,layout='database');secret=self.service.secret.read_bytes()
        restarted=PublicationService(self.server.store,autostart=False);self.addCleanup(restarted.close)
        self.assertTrue(restarted.state()['connected']);self.assertEqual(restarted.state()['link']['parent_id'],PARENT);self.assertEqual(secret,restarted.secret.read_bytes())
        restarted.disconnect();self.assertFalse(restarted.state()['connected']);self.assertFalse(restarted.settings()['auto_sync'])
        record=terminal.dispatch(self.client,terminal.parser().parse_args(['new','Disconnected project','--goal','OFFLINE fixture']))
        self.assertFalse(restarted.state(record['project_id'])['connected']);self.assertFalse(restarted.state(record['project_id'])['link']['auto_sync'])

    def test_global_auto_sync_waits_for_results_instead_of_creating_empty_pages(self):
        self.configure(True);self.service.tick()
        with self.service.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.add_measurement();self.service.tick()
        with self.service.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM jobs').fetchone()[0],1)

    def test_purge_releases_local_report_storage_and_keeps_remote_pages(self):
        self.add_measurement();self.configure();state=self.run_job(self.service.enqueue(self.project['id'],True));pages=len(self.remote.blocks)
        self.client.request('/api/project/delete',dict(project_id=self.project['id']))
        preview=self.client.request('/api/project/purge-preview?project_id='+self.project['id']);self.assertGreater(preview['local_file_bytes'],10000)
        self.client.request('/api/project/purge',dict(project_id=self.project['id'],confirmation_name=self.project['title']))
        self.assertFalse((self.service.root/self.project['id']).exists());self.assertEqual(len(self.remote.blocks),pages)
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],0)

    def test_blocks_stay_within_notion_unicode_limits_without_truncation(self):
        body='한글🙂'*2500;blocks=blocks_for(dict(sections=[('제목',body)]))
        self.assertEqual(''.join(b['paragraph']['rich_text'][0]['text']['content'] for b in blocks[1:]),body)
        self.assertTrue(all(len(b[b['type']]['rich_text'][0]['text']['content'].encode('utf-16-le'))//2<=2000 for b in blocks))

    def test_reading_report_cites_urls_only_and_formats_tables_and_code(self):
        self.add_measurement();node=self.client.root(self.project)
        with self.server.store._connect() as conn:conn.execute('UPDATE nodes SET evidence=? WHERE id=?',(json.dumps([dict(url='https://arxiv.org/abs/2601.00001',title='BIBLIOGRAPHY_SENTINEL',source_excerpt='ABSTRACT_SENTINEL')]),node['id']))
        self.server.store.add_note(node['id'],'analysis','연구 보고 요약',json.dumps(dict(problem='메모리 병목',approach='**재사용**을 검증',findings='확인된 측정 결과만 비교합니다.',limitations=['추가 모델 검증 필요'],next_steps=['절제 실험'])))
        self.configure(layout='database');state=self.run_job(self.service.enqueue(self.project['id'],True))
        markdown=self.service.file(self.project['id'],state['report']['digest'],'report.md').read_text()
        self.assertIn('## 해결하려는 문제',markdown);self.assertIn('https://arxiv.org/abs/2601.00001',markdown)
        self.assertNotIn('BIBLIOGRAPHY_SENTINEL',markdown);self.assertNotIn('ABSTRACT_SENTINEL',markdown)
        self.assertIn('experiment-runs/',markdown);self.assertIn('모듈 직접 실행',markdown)
        entry=next(iter(self.remote.entries.values()))[0];blocks=self.remote.blocks[state['jobs'][0]['section_id']]
        table=next(b for b in blocks if b['type']=='table');self.assertTrue(table['table']['has_column_header'])
        kinds=[b['type'] for b in blocks];self.assertLess(kinds.index('image'),next(i for i,b in enumerate(blocks) if b['type']=='heading_2' and b['heading_2']['rich_text'][0]['text']['content']=='한계와 다음 단계'))
        first=block_signature(table);table['table']['children'][1]['table_row']['cells'][0][0]['text']['content']='HUMAN_EDIT'
        self.assertNotEqual(block_signature(table),first)
        self.assertFalse(any(v['filename']=='results.json' for v in self.remote.uploads.values()))
        self.assertEqual(entry['id'],state['jobs'][0]['page_id'])

    def test_automatic_publication_waits_for_results_or_reader_summary(self):
        self.configure(True,layout='database');self.service.tick()
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        node=self.client.root(self.project);self.server.store.add_note(node['id'],'analysis','내부 검토','중간 사고 기록')
        self.service.tick()
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],0)
        self.server.store.add_note(node['id'],'analysis','연구 보고 요약',json.dumps(dict(problem='확인할 문제',approach='검증할 방법',findings='아직 측정 전',limitations=[],next_steps=[])))
        self.service.tick()
        with self.service.connect() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM jobs').fetchone()[0],1)


class NotionTransportTests(unittest.TestCase):
    def test_authentication_version_rate_limit_and_remote_error_redaction(self):
        from unittest.mock import Mock
        stop=Mock();stop.is_set.return_value=False;api=NotionAPI(TOKEN,stop)
        rate=urllib.error.HTTPError('https://api.notion.com',429,'limit',{'Retry-After':'1'},None)
        with patch.object(api.opener,'open',side_effect=[rate,io.StringIO('{"ok":true}')]) as transport:
            self.assertEqual(api.request('GET','/users/me'),dict(ok=True))
            request=transport.call_args.args[0]
            self.assertEqual(request.get_header('Authorization'),'Bearer '+TOKEN)
            self.assertEqual(request.get_header('Notion-version'),'2026-03-11')
            self.assertEqual(request.full_url,'https://api.notion.com/v1/users/me')
            stop.wait.assert_called_once_with(1)
        denied=urllib.error.HTTPError('https://api.notion.com',401,'secret '+TOKEN,{},io.BytesIO(TOKEN.encode()))
        with patch.object(api.opener,'open',side_effect=denied):
            with self.assertRaises(NotionError) as caught:api.request('GET','/users/me')
            self.assertNotIn(TOKEN,str(caught.exception))


if __name__=='__main__':unittest.main()
