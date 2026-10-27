"""Keyboard/mouse and canonical API integration for the terminal workspace."""
import argparse
import asyncio
import contextlib
import io
import json
import subprocess
import unittest
from unittest.mock import patch

from prompt_toolkit.input import create_pipe_input,DummyInput
from prompt_toolkit.output import DummyOutput
from prompt_toolkit.mouse_events import MouseEvent,MouseEventType,MouseButton
from prompt_toolkit.data_structures import Point
from prompt_toolkit.layout.controls import BufferControl

import test_terminal as fixtures
from compute import PROBE
from terminal_ui import ResearchTerminal
from terminal_presenter import readable,resource_info,phase_status


class TerminalPresentationTests(unittest.TestCase):
    def test_iterm_keymap_contains_only_the_requested_command_keys(self):
        keymap=json.loads((fixtures.ROOT/'desktop/BrainDance.itermkeymap').read_text())
        mappings=keymap['Key Mappings']
        self.assertEqual(set(mappings),{'0xf702-0x300000','0xf703-0x300000','0x7f-0x100000'})
        sequences={k:bytes(int(v,16) for v in action['Text'].split()).decode() for k,action in mappings.items()}
        self.assertTrue(all(action['Action']==11 for action in mappings.values()))
        self.assertEqual(sequences['0xf702-0x300000'],'\x1b[1;9D')
        self.assertEqual(sequences['0xf703-0x300000'],'\x1b[1;9C')
        self.assertEqual(sequences['0x7f-0x100000'],'\x1b[127;9u')
    def test_structured_reports_are_prose_without_losing_blockers_or_numbers(self):
        text=readable('```json\n{"ready":false,"blockers":["Missing checkpoint"],"metrics":{"accuracy":0},"code":"secret source"}\n```')
        self.assertIn('준비 여부: 아니요',text);self.assertIn('Missing checkpoint',text);self.assertIn('정확도: 0',text)
        self.assertNotIn('{',text);self.assertNotIn('secret source',text)

    def test_gpu_number_is_observed_not_inferred_from_list_position(self):
        compute=dict(profiles=[dict(id='remote',name='Test SSH',kind='ssh')],assignments={'p':dict(profile_id='remote',device_ids=['GPU-test'])},
            inventories={'remote':dict(connected=True,hostname='fixture-node',checked_at='2026-10-26T00:00:00+00:00',devices=[dict(id='cpu',name='CPU'),dict(id='GPU-test',name='Test GPU',kind='cuda',index=4)])})
        self.assertIn('GPU 4',resource_info(compute,'p')['text']);self.assertIn('fixture-node',resource_info(compute,'p')['text'])
        compute['inventories']['remote']['devices'][1]['index']=0
        self.assertIn('GPU 0',resource_info(compute,'p')['text']);self.assertNotIn('GPU 1',resource_info(compute,'p')['text'])
        del compute['inventories']['remote']['devices'][1]['index']
        self.assertIn('번호 미확인',resource_info(compute,'p')['text']);self.assertNotIn('GPU 0',resource_info(compute,'p')['text'])

    def test_fixed_hardware_probe_retains_physical_index_and_hostname(self):
        result=subprocess.CompletedProcess([],0,'4, GPU-test, Fixture GPU, 80000, 20000, 25\n','')
        with patch('shutil.which',return_value='/fixture/nvidia-smi'),patch('subprocess.run',return_value=result),patch('platform.node',return_value='fixture-node'),contextlib.redirect_stdout(io.StringIO()) as out:
            exec(compile(PROBE,'<probe>','exec'),{'__name__':'__main__'})
        actual=json.loads(out.getvalue());self.assertEqual(actual['hostname'],'fixture-node');self.assertEqual(actual['devices'][1]['index'],4)
        self.assertEqual(actual['devices'][1]['id'],'GPU-test')

    def test_stage_position_is_not_an_invented_training_percentage(self):
        result=phase_status(dict(runs=[],session=None),[dict(id='j',phase='coding',state='running')])
        self.assertIn('7/11',result);self.assertNotIn('%',result)


class TerminalUITests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.TerminalTests('test_source_command_json_does_not_emit_logo_or_color');self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.client,self.server,self.project=self.fixture.client,self.fixture.server,self.fixture.project
        self.server.provider_status.get=lambda **kw:dict(providers=[dict(name='GPT',connection='connected',plan_label='Fixture plan',windows=[dict(minutes=10080,used_percent=7)])])

    async def wait_until(self,predicate,timeout=4):
        async def poll():
            while not predicate():await asyncio.sleep(.02)
        await asyncio.wait_for(poll(),timeout)

    def scenario(self,exercise):
        async def run(pipe):
            ui=ResearchTerminal(self.client,argparse.Namespace(no_color=True,no_banner=True,project=self.project['id']),input=pipe,output=DummyOutput())
            async def idle():await asyncio.Event().wait()
            ui.hardware=idle
            task=asyncio.create_task(ui.run())
            try:
                await self.wait_until(lambda:ui.project and ui.initialized and bool(ui.experiments))
                await exercise(ui,pipe)
            finally:
                # The app future can be resolved before run() finishes cleanup.
                # Avoid exiting twice while still awaiting that cleanup task.
                if not task.done() and not ui.app.is_done:ui.app.exit()
                await asyncio.wait_for(task,3)
        with create_pipe_input() as pipe:asyncio.run(run(pipe))

    def editable_fields(self,ui):
        return [c.buffer for c in ui.app.layout.find_all_controls() if isinstance(c,BufferControl) and c.buffer is not ui.editor.buffer and not c.buffer.read_only()]

    def test_keyboard_tabs_preserve_draft_and_send_one_shared_direction(self):
        async def exercise(ui,pipe):
            text='기준선은 보존하고 꼬리 지연을 비교해줘';ui.editor.text=text
            pipe.send_text('\x02'+'4')
            await self.wait_until(lambda:ui.tab==3)
            ui.render();self.assertEqual(ui.body.buffer.cursor_position,0)
            self.assertEqual(ui.editor.text,text)
            pipe.send_text('\x0f\x0f')
            await self.wait_until(lambda:ui.mode==2)
            pipe.send_text('\r')
            await self.wait_until(lambda:len(self.server.chat.messages(self.project['id'])['messages'])==2 and not ui.sending)
            rows=self.server.chat.messages(self.project['id'])['messages'];self.assertEqual(rows[0]['content'],text)
            self.assertEqual(rows[1]['metadata']['mode'],'next');self.assertEqual(ui.tab,0);self.assertEqual(ui.editor.text,'')
            self.assertEqual(len(self.server.autopilot.state(self.project['id'])['directions']),1)
        self.scenario(exercise)

    def test_project_picker_arrow_navigation_reaches_delete_and_restores_by_keyboard(self):
        other=self.fixture.call('new','Keyboard target','--goal','Disposable navigation fixture')['project_id']
        async def exercise(ui,pipe):
            pipe.send_text('/projects\r')
            await self.wait_until(lambda:bool(ui.modals))
            listing=ui.app.layout.current_control
            pipe.send_text('\x1b[B\x1b[B')
            await self.wait_until(lambda:ui.app.layout.has_focus(ui.modal_buttons[-1][0]))
            pipe.send_text('\x1b[C\x1b[C')
            await self.wait_until(lambda:ui.app.layout.has_focus(ui.modal_buttons[-1][2]))
            pipe.send_text('\x1b[A')
            await self.wait_until(lambda:ui.app.layout.current_control is listing)
            pipe.send_text('\r')
            await self.wait_until(lambda:ui.project and ui.project['id']==other and not ui.modals)
            pipe.send_text('/projects\r')
            await self.wait_until(lambda:bool(ui.modals))
            pipe.send_text('\x1b[B\x1b[C\x1b[C\r')
            await self.wait_until(lambda:len(ui.modals)==2)
            pipe.send_text('\r')
            await self.wait_until(lambda:ui.project is None and bool(self.server.cleanup.trash()['projects']))
            await self.wait_until(lambda:ui.modal_task is None or ui.modal_task.done())
            pipe.send_text('\x1b')
            await self.wait_until(lambda:not ui.modals)
            pipe.send_text('/trash\r')
            await self.wait_until(lambda:bool(ui.modals))
            pipe.send_text('\x1b[B\r')
            await self.wait_until(lambda:ui.project and ui.project['id']==other and not ui.modals)
            self.assertEqual(self.server.cleanup.trash()['projects'],[])
            self.assertEqual(self.client.messages(ui.project),[])
        self.scenario(exercise)

    def test_word_keys_follow_whitespace_and_do_not_switch_tabs(self):
        text='첫째/경로-값   둘째.결과:값\t셋째'
        mappings=json.loads((fixtures.ROOT/'desktop/BrainDance.itermkeymap').read_text())['Key Mappings']
        sequence=lambda k:bytes(int(value,16) for value in mappings[k]['Text'].split()).decode()
        async def exercise(ui,pipe):
            ui.editor.text=text;ui.editor.buffer.cursor_position=len(text)
            pipe.send_text(sequence('0xf702-0x300000'))
            await self.wait_until(lambda:ui.editor.buffer.cursor_position==text.index('셋째'))
            pipe.send_text(sequence('0xf702-0x300000'))
            await self.wait_until(lambda:ui.editor.buffer.cursor_position==text.index('둘째'))
            pipe.send_text(sequence('0xf703-0x300000'))
            await self.wait_until(lambda:ui.editor.buffer.cursor_position==text.index('\t'))
            pipe.send_text(sequence('0x7f-0x100000'))
            await self.wait_until(lambda:ui.editor.text=='첫째/경로-값   \t셋째')
            self.assertEqual(ui.tab,0)
            pipe.send_text('\x17')
            await self.wait_until(lambda:ui.editor.text=='\t셋째')
            pipe.send_text('\x1f')
            await self.wait_until(lambda:ui.editor.text=='첫째/경로-값   \t셋째')
            ui.new_project_dialog();field=self.editable_fields(ui)[0]
            field.text='두 단어 test';field.cursor_position=len(field.text)
            pipe.send_text('\x1b\x7f')
            await self.wait_until(lambda:field.text=='두 단어 ')
            pipe.send_text('\x1b[127;5u')
            await self.wait_until(lambda:field.text=='두 ')
            pipe.send_text('\x7f')
            await self.wait_until(lambda:field.text=='두')
            self.assertEqual(self.client.messages(self.project),[])
        self.scenario(exercise)

    def test_tab_buttons_and_dialog_fields_are_keyboard_reachable(self):
        async def exercise(ui,pipe):
            ui.app.layout.focus(ui.tab_control)
            pipe.send_text('\x1b[C\x1b[C')
            await self.wait_until(lambda:ui.tab==2)
            self.assertTrue(ui.app.layout.has_focus(ui.tab_control))
            pipe.send_text('\r')
            await self.wait_until(lambda:ui.app.layout.has_focus(ui.editor))
            ui.new_project_dialog();fields=self.editable_fields(ui)
            self.assertEqual(ui.app.current_buffer,fields[0])
            pipe.send_text('\t')
            await self.wait_until(lambda:ui.app.current_buffer is fields[1])
            pipe.send_text('\x1b[Z')
            await self.wait_until(lambda:ui.app.current_buffer is fields[0])
            pipe.send_text('\t\t')
            await self.wait_until(lambda:ui.app.layout.has_focus(ui.modal_buttons[-1][0]))
            pipe.send_text('\x1b[D')
            await self.wait_until(lambda:ui.app.layout.has_focus(ui.modal_buttons[-1][-1]))
            pipe.send_text('\x1b[A')
            await self.wait_until(lambda:ui.app.current_buffer is fields[1])
        self.scenario(exercise)

    def test_mouse_tab_and_issue_reply_keep_the_canonical_reference(self):
        session=self.server.autopilot.control(dict(project_id=self.project['id'],action='start'))['session']
        self.server.autopilot.save(session,'blocked','Fixture missing checkpoint')
        async def exercise(ui,pipe):
            fragments=ui.tab_fragments();mouse=MouseEvent(Point(0,0),MouseEventType.MOUSE_UP,MouseButton.LEFT,frozenset())
            fragments[1][2](mouse);self.assertEqual(ui.tab,1)
            ui.reply_issue();self.assertEqual(ui.tab,0);self.assertEqual(ui.reply_to,dict(type='session',id=session['id']))
            ui.editor.text='사용할 체크포인트는 기존 파일로 유지해줘';ui.accept()
            await self.wait_until(lambda:len(self.server.chat.messages(self.project['id'])['messages'])==2 and not ui.sending)
            row=self.server.chat.messages(self.project['id'])['messages'][-1]
            self.assertEqual(row['metadata']['reply_to']['id'],session['id'])
        self.scenario(exercise)

    def test_project_switch_isolates_drafts_and_does_not_move_an_inflight_send(self):
        other=self.fixture.call('new','Other UI fixture','--goal','Separate project')
        original_project=self.project
        async def exercise(ui,pipe):
            ui.editor.text='첫 프로젝트 방향';original=self.client.send
            def delayed(*args):
                import time
                time.sleep(.15);return original(*args)
            with patch.object(self.client,'send',side_effect=delayed):
                sending=asyncio.create_task(ui.send(ui.editor.text));await asyncio.sleep(.03)
                second=self.client.project(other['project_id']);await ui.select_project(second)
                ui.editor.text='두 번째 프로젝트 임시 입력';await sending
            self.assertEqual(ui.editor.text,'두 번째 프로젝트 임시 입력')
            self.assertEqual(self.client.messages(second),[])
            self.assertEqual(self.client.messages(original_project)[0]['content'],'첫 프로젝트 방향')
            await ui.select_project(original_project);self.assertEqual(ui.editor.text,'첫 프로젝트 방향')
        self.scenario(exercise)

    def test_budget_dialog_updates_the_existing_session_without_resetting_it(self):
        session=self.server.autopilot.control(dict(project_id=self.project['id'],action='start',max_model_calls=10,token_budget=200000))['session']
        self.server.autopilot.control(dict(project_id=self.project['id'],action='pause'))
        async def exercise(ui,pipe):
            ui.limits_dialog();fields=self.editable_fields(ui);self.assertEqual(len(fields),2)
            fields[0].text='15';fields[1].text='300000'
            ui.modal_buttons[-1][0].handler()
            await self.wait_until(lambda:not ui.modals)
            actual=self.server.autopilot.state(self.project['id'])
            self.assertEqual(actual['session']['id'],session['id']);self.assertEqual(actual['session']['status'],'paused')
            self.assertEqual(actual['usage']['calls'],0);self.assertEqual(actual['usage']['max_calls'],15)
        self.scenario(exercise)

    def test_new_project_wizard_selects_device_before_persisting(self):
        async def exercise(ui,pipe):
            ui.new_project_dialog();fields=self.editable_fields(ui);self.assertEqual(len(fields),2)
            fields[0].text='Created by tabbed UI';fields[1].text='CPU fixture only'
            ui.modal_buttons[-1][0].handler()
            self.assertIsNotNone(ui.resource_form);ui.resource_form['minutes'].text='2'
            ui.modal_buttons[-1][1].handler()
            await self.wait_until(lambda:ui.project['title']=='Created by tabbed UI')
            assignment=self.server.compute.state()['assignments'][ui.project['id']]
            self.assertEqual(assignment['device_ids'],['cpu']);self.assertEqual(assignment['time_budget_minutes'],2)
            self.assertFalse(self.server.autopilot.sessions(ui.project['id']))
        self.scenario(exercise)

    def test_settings_slashes_open_controls_without_starting_login_or_model_calls(self):
        async def exercise(ui,pipe):
            with patch('terminal_ui.subprocess.call') as login:
                await ui.slash('/settings');self.assertEqual(ui.tab,5)
                await ui.slash('/gpt');self.assertEqual(len(ui.modals),1);login.assert_not_called()
                ui.close_dialog();await ui.slash('/ssh');self.assertEqual(len(ui.modals),1);login.assert_not_called()
            self.assertEqual(self.server.chat.messages(self.project['id'])['messages'],[])
        self.scenario(exercise)

    def test_idea_details_and_reports_hide_structural_json_and_other_projects(self):
        node=self.server.store.add_node(self.client.root(self.project)['id'],'Selected hypothesis',metadata=dict(experiment=dict(control='Preserve baseline'),novelty=4))
        other=self.fixture.call('new','Private second fixture','--goal','Separate')
        self.server.store.add_note(other['node']['id'],'analysis','Other private result','DO_NOT_CROSS_PROJECTS')
        self.server.store.add_note(node['id'],'analysis','Structured report','{"ready":false,"blockers":["NEEDED_CHECKPOINT"]}')
        async def exercise(ui,pipe):
            ui.select_tab(2);ui.render();self.assertIn('Preserve baseline',ui.body.text)
            ui.select_tab(0);ui.render();self.assertIn('NEEDED_CHECKPOINT',ui.body.text)
            self.assertNotIn('"ready"',ui.body.text);self.assertNotIn('DO_NOT_CROSS_PROJECTS',ui.body.text)
        self.scenario(exercise)

    def test_intervention_links_to_a_live_cpu_run_and_does_not_stop_it_implicitly(self):
        plan=self.server.experiments.create(dict(node_id=self.client.root(self.project)['id'],title='Live UI CPU fixture',timeout_seconds=12,code="import time\nprint('UI_CPU_PROGRESS',flush=True)\ntime.sleep(8)"))
        approval=self.server.experiments.approve(plan['id'],plan['digest'],True)
        run=self.server.experiments.enqueue(plan['id'],approval['id'])
        async def exercise(ui,pipe):
            await self.wait_until(lambda:self.server.experiments.run_info(run['id'])['state']=='running')
            ui.select_tab(4);ui.render();ui.direct_run()
            self.assertEqual(ui.reply_to,dict(type='run',id=run['id']));self.assertEqual(ui.mode,2)
            ui.editor.text='현재 실험은 유지하고 다음 비교에서 시드 수를 늘려줘';ui.accept()
            await self.wait_until(lambda:len(self.server.chat.messages(self.project['id'])['messages'])==2 and not ui.sending)
            self.assertEqual(self.server.experiments.run_info(run['id'])['state'],'running')
            self.assertEqual(self.server.chat.messages(self.project['id'])['messages'][-1]['metadata']['reply_to']['id'],run['id'])
            await ui.cancel_run()
            await self.wait_until(lambda:self.server.experiments.run_info(run['id'])['state']=='cancelled')
        self.scenario(exercise)

    def test_quit_does_not_wait_for_a_slow_background_connection_check(self):
        import threading
        entered=threading.Event();release=threading.Event();self.addCleanup(release.set)
        def slow():entered.set();release.wait(10)
        async def exercise(ui,pipe):
            ui.spawn(ui.call(slow))
            await self.wait_until(entered.is_set)
            pipe.send_text('\x11')
            await self.wait_until(lambda:not ui.app.is_running,timeout=1)
        self.scenario(exercise)

    def test_exit_leaves_every_tab_even_while_sending_without_posting_to_chat(self):
        from terminal_ui import SLASH
        self.assertIn('/exit',SLASH)
        for tab in range(7):
            async def exercise(ui,pipe):
                ui.select_tab(tab);ui.sending=True
                pipe.send_text('/exit\r')
                await self.wait_until(lambda:not ui.app.is_running,timeout=1)
            self.scenario(exercise)
        self.assertEqual(self.client.messages(self.project),[])

    def test_project_delete_restore_and_confirmed_purge_use_the_same_store(self):
        from terminal_ui import SLASH
        for command in ['/delete','/trash','/restore','/purge']:self.assertIn(command,SLASH)
        pid=self.project['id'];title=self.project['title']
        async def exercise(ui,pipe):
            from terminal import ClientError
            with self.assertRaises(ClientError):await ui.slash('/delete --unknown-option')
            self.assertTrue(ui.app.is_running)
            ui.editor.text='Preserve this project draft'
            await ui.slash('/delete')
            self.assertEqual(len(ui.modal_buttons[-1]),2)
            ui.modal_buttons[-1][0].handler()
            await self.wait_until(lambda:ui.project is None and bool(self.server.cleanup.trash()['projects']))
            await self.wait_until(lambda:ui.modal_task is None or ui.modal_task.done())
            await ui.slash('/restore --project '+pid)
            self.assertEqual(ui.project['id'],pid)
            self.assertEqual(ui.editor.text,'Preserve this project draft')
            self.assertEqual(self.server.cleanup.trash()['projects'],[])
            await ui.slash('/delete');ui.modal_buttons[-1][0].handler()
            await self.wait_until(lambda:ui.project is None)
            await self.wait_until(lambda:ui.modal_task.done())
            await ui.slash('/purge --project '+pid)
            fields=self.editable_fields(ui);self.assertEqual(len(fields),1)
            fields[0].text='wrong name';ui.modal_buttons[-1][0].handler()
            await self.wait_until(lambda:bool(ui.error) and ui.modal_task.done())
            self.assertEqual(len(self.server.cleanup.trash()['projects']),1)
            fields[0].text=title;ui.modal_buttons[-1][0].handler()
            await self.wait_until(lambda:not self.server.cleanup.trash()['projects'])
            await self.wait_until(lambda:ui.modal_task.done())
            self.assertNotIn(pid,ui.drafts)
            self.assertEqual(self.server.store.export_json()['projects'],[])
        self.scenario(exercise)

    def test_code_view_preserves_python_operators_instead_of_treating_them_as_markdown(self):
        code="print(2**3)\nprint({'accuracy': 0.7})"
        self.server.experiments.create(dict(node_id=self.client.root(self.project)['id'],title='Code viewer fixture',timeout_seconds=2,code=code))
        async def exercise(ui,pipe):
            ui.select_tab(3);ui.render();ui.code_dialog()
            buffers=[c.buffer for c in ui.app.layout.find_all_controls() if isinstance(c,BufferControl)]
            self.assertTrue(any(b.text==code for b in buffers))
        self.scenario(exercise)

    def test_wheel_scrolls_wrapped_korean_history_without_moving_input_or_jumping_on_reports(self):
        message=self.server.chat.send(dict(node_id=self.client.root(self.project)['id'],content='Scroll history fixture',mode='ask',request_id='scroll-history-fixture-001'))
        paragraph='관측 신선도와 비동기 추론 지연을 측정한 기록입니다. ' * 220
        self.server.chat.finish(message['id'],paragraph,'completed',message['metadata'])
        async def exercise(ui,pipe):
            await self.wait_until(lambda:ui.body.window.render_info is not None and ui.body.window.vertical_scroll>0)
            old=ui.body.window.vertical_scroll;input_y=ui.editor.window.render_info._y_offset
            draft='새 실험 방향을 작성 중';ui.editor.text=draft
            event=MouseEvent(Point(10,3),MouseEventType.SCROLL_UP,MouseButton.NONE,frozenset())
            ui.body.control.mouse_handler(event)
            await self.wait_until(lambda:ui.body.window.render_info.vertical_scroll<old)
            stopped=ui.body.window.vertical_scroll
            pipe.send_text('\x1b[5~')
            await self.wait_until(lambda:ui.body.window.render_info.vertical_scroll<stopped)
            stopped=ui.body.window.vertical_scroll
            self.assertFalse(ui.follow);self.assertEqual(ui.editor.text,draft)
            self.assertIs(ui.app.layout.current_control,ui.editor.control)
            self.server.store.add_note(self.client.root(self.project)['id'],'analysis','New report during scroll','REPORT_WHILE_READING')
            await ui.refresh();ui.app.invalidate();await asyncio.sleep(.05)
            self.assertEqual(ui.body.window.vertical_scroll,stopped);self.assertEqual(ui.editor.window.render_info._y_offset,input_y)
            self.assertTrue(ui.unread)
            ui.bottom();await self.wait_until(lambda:ui.body.window.render_info.bottom_visible)
            self.assertTrue(ui.follow);self.assertEqual(ui.editor.text,draft)
        self.scenario(exercise)

    def test_input_remains_at_terminal_bottom_across_every_tab(self):
        async def exercise(ui,pipe):
            await self.wait_until(lambda:ui.editor.window.render_info is not None)
            start=ui.editor.window.render_info._y_offset
            for index in range(7):
                ui.select_tab(index);await asyncio.sleep(.04)
                info=ui.editor.window.render_info
                self.assertEqual(info._y_offset,start)
                self.assertEqual(info._y_offset+info.window_height+1,ui.app.output.get_size().rows)
        self.scenario(exercise)

    def test_notion_masked_setup_and_results_preserve_the_shared_input(self):
        from notion_reports import NotionAPI
        from test_notion_reports import RemoteFixture,PARENT,TOKEN
        from prompt_toolkit.layout.processors import PasswordProcessor
        remote=RemoteFixture()
        async def exercise(ui,pipe):
            draft='기존 연구 방향 유지';ui.editor.text=draft
            await ui.notion_dialog()
            fields=self.editable_fields(ui);self.assertEqual(len(fields),2)
            fields[0].text=PARENT;fields[1].text=TOKEN
            controls=[c for c in ui.app.layout.find_all_controls() if isinstance(c,BufferControl) and c.buffer is fields[1]]
            self.assertTrue(any(isinstance(getattr(p,'processor',p),PasswordProcessor) for c in controls for p in c.input_processors))
            next(b for b in ui.modal_buttons[-1] if b.text=='저장').handler()
            await self.wait_until(lambda:not ui.modals)
            await ui.report_action(False)
            await self.wait_until(lambda:bool(self.server.publications.state(self.project['id'])['report']))
            await ui.refresh();ui.render()
            self.assertEqual(ui.tab,6);self.assertIn('결과 · Notion',ui.body.text)
            self.assertEqual(ui.editor.text,draft)
            self.assertTrue(all(m['role']!='user' for m in self.client.messages(self.project)))
        with patch.object(NotionAPI,'request',autospec=True,side_effect=remote.request):self.scenario(exercise)


if __name__=='__main__':unittest.main()
