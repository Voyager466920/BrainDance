"""Tabbed terminal workspace over the existing BrainDance API and project stream."""
import asyncio
from contextlib import suppress,redirect_stderr
from datetime import datetime
import json
import io
import os
import shlex
import subprocess
import threading
import time
import urllib.parse
import uuid

from prompt_toolkit.application import Application,run_in_terminal
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition,has_focus,has_completions
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.bindings.focus import focus_next,focus_previous
from prompt_toolkit.layout import Layout,HSplit,VSplit,Window,Float,FloatContainer,ConditionalContainer,DynamicContainer
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import TextArea,Label,Button,Dialog,RadioList,CheckboxList,Checkbox,Box,Frame

from terminal import LOGO_ASSETS,ClientError,parser,dispatch,safe_text,purge_summary,file_size
from terminal_presenter import (STATES,readable,short,clock,duration,provider_line,device_label,
    resource_info,phase_status,conversation,progress_view,idea_view,plan_view,run_view,report_view,clip_cells,wrap_cells,connection_error)

TABS=['대화','진행','아이디어','계획','실험','설정','결과']
MODES=[('auto','대화'),('ask','질문만'),('next','다음 방향'),('restart','중지 후 재준비')]
SLASH=['/settings','/gpt','/claude','/ssh','/gpu','/notion','/reports','/projects','/new','/delete','/trash','/restore','/purge','/help','/exit','/quit']


class ResearchTerminal:
    @property
    def notice(self):return self._notice if time.monotonic()-self.notice_at<8 else ''

    @notice.setter
    def notice(self,value):self._notice=safe_text(value);self.notice_at=time.monotonic()

    def __init__(self,client,args,*,input=None,output=None):
        self.client,self.args=client,args
        self.project=None;self.epoch=0;self.tab=0;self.body_key=None;self.mode=0;self.reply_to=None;self.scope=None
        self.reports={}
        self.tree={};self.compute={};self.providers={};self.state={};self.messages=[];self.experiments={};self.jobs=[];self.job_info=None;self.run_info=None
        self.projects=[];self.drafts={};self.pending={};self.welcome=not getattr(args,'no_banner',False);self.follow=True;self.unread=False;self.initialized=False;self.error='';self.transport_error='';self.notice=''
        self.sending=False;self.probing=set();self.modals=[];self.modal_buttons=[];self.modal_task=None;self.resource_form=None;self.last_probe={};self.wakeup=asyncio.Event()
        self.body=TextArea(read_only=True,scrollbar=True,wrap_lines=False,focusable=True,focus_on_click=True,style='class:body')
        self._original_body_mouse=self.body.control.mouse_handler
        self.body.control.mouse_handler=self.body_mouse
        self.idea_list=RadioList([('','아이디어 없음')],show_scrollbar=True,select_on_focus=True)
        self.plan_list=RadioList([('','계획 없음')],show_scrollbar=True,select_on_focus=True)
        self.run_list=RadioList([('','실험 없음')],show_scrollbar=True,select_on_focus=True)
        for listing in (self.idea_list,self.plan_list,self.run_list):
            listing.window.dont_extend_height=lambda:False
        self.editor=TextArea(height=3,multiline=True,wrap_lines=True,prompt=' › ',style='class:input',
            completer=WordCompleter(SLASH),complete_while_typing=Condition(lambda:self.editor.text.startswith('/')),scrollbar=True,name='project-input')
        self.editor.buffer.on_text_changed+=self._typing
        self.help_text='Ctrl+B→1–7 탭 · 휠/PgUp·PgDn 스크롤 · Enter 전송 · Alt+Enter 줄바꿈'
        self._build(input,output)

    def _typing(self,_):
        if self.editor.text:self.welcome=False

    def _build(self,input,output):
        kb=KeyBindings();normal=Condition(lambda:not self.modals)
        for index in range(len(TABS)):
            def choose(event,i=index):self.select_tab(i)
            kb.add('c-b',str(index+1),filter=normal)(choose)
            kb.add('escape',str(index+1),filter=normal)(choose)
        for keys,delta in [(('c-b','n'),1),(('c-b','N'),1),(('c-b','p'),-1),(('c-b','P'),-1),(('c-b','right'),1),(('c-b','left'),-1),(('escape','right'),1),(('escape','left'),-1)]:
            kb.add(*keys,filter=normal)(lambda event,d=delta:self.select_tab((self.tab+d)%len(TABS)))
        kb.add('tab',filter=normal & ~has_completions)(focus_next);kb.add('s-tab',filter=normal & ~has_completions)(focus_previous)
        kb.add('tab',filter=normal & has_focus(self.editor) & has_completions)(lambda event:event.current_buffer.complete_next())
        kb.add('s-tab',filter=normal & has_focus(self.editor) & has_completions)(lambda event:event.current_buffer.complete_previous())
        kb.add('c-p',filter=normal)(lambda event:self.project_dialog())
        kb.add('c-l',filter=normal)(lambda event:self.app.layout.focus(self.editor))
        kb.add('c-o',filter=normal)(lambda event:self.cycle_mode())
        kb.add('enter',filter=normal & has_focus(self.editor))(lambda event:self.accept())
        for keys in [('escape','enter'),('c-j',)]:
            kb.add(*keys,filter=normal & has_focus(self.editor))(lambda event:self.editor.buffer.insert_text('\n'))
        kb.add('pageup',filter=normal)(lambda event:self.scroll_page(-1))
        kb.add('pagedown',filter=normal)(lambda event:self.scroll_page(1))
        kb.add('c-b','g',filter=normal)(lambda event:self.bottom())
        kb.add('c-b','G',filter=normal)(lambda event:self.bottom())
        @kb.add('c-c')
        def interrupt(event):
            if self.modals:self.close_dialog()
            elif self.editor.text:self.editor.text=''
            else:event.app.exit()
        kb.add('c-q')(lambda event:event.app.exit())
        kb.add('escape',filter=Condition(lambda:bool(self.modals)))(lambda event:self.close_dialog())
        self.controls=[
            ConditionalContainer(self.buttons([('전체 대화',lambda:self.select_tab(0)),('프로젝트',self.project_dialog)]),Condition(lambda:self.tab==0 and self.welcome)),
            ConditionalContainer(self.buttons([('자동 시작',self.start_dialog),('일시정지',lambda:self.spawn(self.automatic('pause'))),('재개',lambda:self.spawn(self.automatic('resume'))),('중지',lambda:self.spawn(self.automatic('stop'))),('한도',self.limits_dialog),('문제에 답글',self.reply_issue)]),Condition(lambda:self.tab==1)),
            ConditionalContainer(self.buttons([('가설에 지시',self.direct_idea),('활성',lambda:self.spawn(self.node_status('active'))),('보류',lambda:self.spawn(self.node_status('held'))),('폐기',lambda:self.spawn(self.node_status('discarded')))]),Condition(lambda:self.tab==2)),
            ConditionalContainer(self.buttons([('계획에 지시',self.direct_plan),('코드 보기',self.code_dialog)]),Condition(lambda:self.tab==3)),
            ConditionalContainer(self.buttons([('실험에 지시',self.direct_run),('이 실험 중지',lambda:self.spawn(self.cancel_run()))]),Condition(lambda:self.tab==4)),
            ConditionalContainer(HSplit([self.buttons([('GPT 연결',lambda:self.provider_dialog('GPT')),('Claude 연결',lambda:self.provider_dialog('Claude')),('SSH 추가',self.ssh_dialog),('서버·GPU',self.resource_dialog)]),self.buttons([('연결 갱신',lambda:self.spawn(self.refresh_providers(True))),('장치 조회',lambda:self.spawn(self.probe_selected())),('한도',self.limits_dialog),('새 프로젝트',self.new_project_dialog),('Notion',lambda:self.spawn(self.notion_dialog()))])]),Condition(lambda:self.tab==5)),
            ConditionalContainer(self.buttons([('보고서 만들기',lambda:self.spawn(self.report_action(False))),('시각화 열기',lambda:self.spawn(self.open_report())),('Notion 동기화',lambda:self.spawn(self.report_action(True))),('Notion 설정',lambda:self.spawn(self.notion_dialog()))]),Condition(lambda:self.tab==6))]
        lists=HSplit([
            ConditionalContainer(Box(self.idea_list,padding=0),Condition(lambda:self.tab==2)),
            ConditionalContainer(Box(self.plan_list,padding=0),Condition(lambda:self.tab==3)),
            ConditionalContainer(Box(self.run_list,padding=0),Condition(lambda:self.tab==4)),
        ])
        sidebar=Frame(Box(lists,padding=0,style='class:sidebar'),title=lambda:{2:'아이디어 목록',3:'계획 목록',4:'실험 목록'}.get(self.tab,''),width=28,style='class:sidebar-frame')
        detail=Frame(Box(self.body,padding=0,style='class:detail'),title=self.detail_title,style='class:detail-frame')
        split=VSplit([sidebar,detail],padding=1)
        content=DynamicContainer(lambda:split if self.tab in {2,3,4} else detail)
        composer=Frame(HSplit([
            Window(FormattedTextControl(self.composer_fragments),height=1,style='class:composer-mode'),
            VSplit([self.editor,Button('전송',handler=self.accept,width=8)],padding=1),
        ]),title='프로젝트 대화',height=6,style='class:composer-frame')
        root=HSplit([
            Window(FormattedTextControl(self.header),height=1,style='class:header'),
            Window(FormattedTextControl(lambda:provider_line(self.providers,compact=True)),height=1,style='class:muted'),
            Window(FormattedTextControl(self.progress_header),height=1,style='class:progress'),
            Window(FormattedTextControl(self.resource_header),height=1,style='class:muted'),
            Window(FormattedTextControl(self.issue_fragments),height=1,style='class:notice'),
            content,*self.controls,
            Window(FormattedTextControl(self.tab_fragments,focusable=True,show_cursor=False),height=1,style='class:tabs'),
            Window(FormattedTextControl(lambda:self.notice or self.help_text),height=1,style='class:muted'),
            composer,
        ])
        self.container=FloatContainer(root,[Float(xcursor=True,ycursor=True,content=CompletionsMenu(max_height=8,scroll_offset=0,extra_filter=has_focus(self.editor)))])
        colored=not getattr(self.args,'no_color',False) and 'NO_COLOR' not in os.environ
        style=Style.from_dict({
            '':'bg:#0c141b #d1d8d5',
            'header':'bold bg:#13232c #b8cfc0','body':'bg:#101b24 #d1d8d5','input':'bg:#172e25 #d6e4db',
            'sidebar':'bg:#003f5f #b4cbd7','sidebar-frame':'bg:#003f5f #6fa7c5',
            'detail':'bg:#101b24 #d1d8d5','detail-frame':'bg:#101b24 #537886',
            'composer-frame':'bg:#14291f #75a98d','composer-mode':'bg:#14291f #9fc7ae',
            'progress':'#8fbc9c','muted':'#87998e','notice':'#d3bd82','tabs':'#83978a',
            'tab.active':'bold bg:#304638 #c9ddce','button':'#a8c5b0','button.focused':'bold bg:#304638 #e3ece5',
            'dialog':'bg:#17241f','dialog.body':'bg:#17241f #d1d8d5','dialog shadow':'bg:#101715',
            'radio-selected':'bold bg:#315f83 #e1edf2','radio-checked':'bg:#214d66 #bfd6e2','checkbox-selected':'bold #c1d8c8',
            'completion-menu.completion':'bg:#17241f #a8c5b0','completion-menu.completion.current':'bold bg:#304638 #e3ece5',
        }) if colored else Style.from_dict({})
        self.app=Application(layout=Layout(self.container,focused_element=self.editor),key_bindings=kb,
            full_screen=True,mouse_support=True,style=style,input=input,output=output,erase_when_done=True,
            before_render=lambda app:self.render())

    def invoke(self,callback):
        try:return callback()
        except Exception as exc:self.error=safe_text(exc);self.app.invalidate()

    def buttons(self,items):return VSplit([Button(text,handler=lambda f=handler:self.invoke(f),width=max(10,len(text)*2+2)) for text,handler in items],padding=1,height=1)

    def header(self):return ' BrainDance  /  '+safe_text(self.project['title'] if self.project else '프로젝트 선택')

    def detail_title(self):
        title={0:'대화',1:'진행 상황',2:'아이디어 상세',3:'계획 상세',4:'실험 상세',5:'설정',6:'결과 · 시각화'}.get(self.tab,'')
        result=[('class:header',title+' '),('class:button',' ↑ ',self.click(lambda:self.scroll(-6))),('class:button',' ↓ ',self.click(lambda:self.scroll(6)))]
        if self.tab==0:result.append(('class:button',' 최신 ',self.click(self.bottom)))
        return result

    def progress_header(self):
        if not self.project:return ' 대화에서 연구를 시작하고 아래 탭으로 기록을 확인하세요.'
        usage=self.state.get('usage')
        return ' '+phase_status(self.state,self.jobs,self.job_info)+(f" · 호출 {usage['calls']}/{usage['max_calls']}" if usage else '')

    def resource_header(self):
        resource=resource_info(self.compute,self.project['id'] if self.project else '')
        checking=resource['profile'] and resource['profile']['id'] in self.probing
        return ' '+('조회 중 · ' if checking else '')+resource['text']

    def issue(self):
        for job in self.jobs[:1]:
            if job['state'] in {'failed','blocked'} or job.get('phase')=='blocked':return dict(type='job',id=job['id'],title='연구 작업',message=job.get('error') or job.get('message',''))
        item=self.state.get('session')
        if item and item['status']=='blocked':return dict(type='session',id=item['id'],title='자동 연구',message=item['message'])
        for run in self.runs()[:1]:
            if run['state'] in {'blocked','failed','timed_out'}:return dict(type='run',id=run['id'],title=run['title'],message=run.get('error') or STATES[run['state']])
        return None

    def issue_fragments(self):
        if self.error:return [('class:notice',' '+short(self.error,100))]
        if self.transport_error:return [('class:notice',' 연결 확인 · '+short(self.transport_error,90))]
        issue=self.issue()
        width=self.app.output.get_size().columns
        return [('class:notice',' 확인 필요 · '+clip_cells(issue['message'],width-24)+'  '),('class:button','[답글]',self.click(self.reply_issue))] if issue else [('', '')]

    def tab_fragments(self):
        result=[]
        for i,name in enumerate(TABS):result.append(('class:tab.active' if i==self.tab else 'class:tabs',' '+str(i+1)+' '+name+(' ●' if i==0 and self.unread else '')+' ',self.click(lambda n=i:self.select_tab(n))))
        return result

    def composer_fragments(self):
        text=' '+MODES[self.mode][1]+' · '+(self.project['title'] if self.project else '프로젝트를 선택하세요')
        if self.scope:text+=' · '+short(self.scope.get('title',''),28)
        if self.reply_to:text+=' · 답글 연결됨'
        if self.sending:text+=' · 전송 중'
        text=clip_cells(text,self.app.output.get_size().columns-28)
        return [('class:muted',safe_text(text)+'  '),('class:button','[방식 변경]',self.click(self.cycle_mode)),('class:button',' [범위 해제]',self.click(self.clear_scope))]

    @staticmethod
    def click(callback):
        def handler(event):
            if event.event_type==MouseEventType.MOUSE_UP:callback()
        return handler

    def select_tab(self,index):
        self.tab=index;self.welcome=False;self.notice='';self.app.layout.focus(self.editor);self.wakeup.set();self.app.invalidate()
        if index==0:self.follow=True;self.unread=False

    def cycle_mode(self):self.mode=(self.mode+1)%len(MODES);self.app.invalidate()
    def clear_scope(self):self.scope=None;self.reply_to=None;self.app.invalidate()

    def scroll_page(self,direction):
        info=self.body.window.render_info
        self.scroll(direction*max(1,(info.window_height if info else 8)-1))

    def scroll(self,delta):
        buffer=self.body.buffer;window=self.body.window;info=window.render_info
        height=max(1,info.window_height if info else 8)
        if self.tab==0:
            self.follow=False
            if self.welcome:
                self.welcome=False;self.render()
                window.vertical_scroll=max(0,buffer.document.line_count-height)
        maximum=max(0,buffer.document.line_count-height)
        top=max(0,min(maximum,window.vertical_scroll+delta))
        row=top if delta<0 else min(buffer.document.line_count-1,top+height-1)
        buffer.cursor_position=buffer.document.translate_row_col_to_index(row,0)
        window.vertical_scroll=top
        if self.tab==0 and delta>0 and top==maximum:self.follow=True;self.unread=False
        self.app.invalidate()

    def body_mouse(self,event):
        if event.event_type in {MouseEventType.SCROLL_UP,MouseEventType.SCROLL_DOWN}:
            self.scroll(-3 if event.event_type==MouseEventType.SCROLL_UP else 3)
            return None
        if self.tab==0 and event.event_type==MouseEventType.MOUSE_DOWN:self.follow=False
        return self._original_body_mouse(event)

    def bottom(self):
        self.follow=True;self.unread=False
        if self.tab==0 and self.welcome:self.welcome=False;self.render()
        self.body.buffer.cursor_position=len(self.body.text);self.app.invalidate()

    def update_body(self,text,follow=False):
        width=self.app.output.get_size().columns-3-(29 if self.tab in {2,3,4} else 0)
        text=wrap_cells(safe_text(text),width)
        if text==self.body.text:return
        cursor=len(text) if follow else min(self.body.buffer.cursor_position,len(text))
        self.body.buffer.set_document(Document(text,cursor_position=cursor),bypass_readonly=True)

    def selected_node(self):return next((n for n in self.nodes() if n['id']==self.idea_list.current_value),None)
    def selected_plan(self):return next((p for p in self.plans() if p['id']==self.plan_list.current_value),None)
    def selected_run(self):return next((r for r in self.runs() if r['id']==self.run_list.current_value),None)

    def nodes(self):
        pid=self.project['id'] if self.project else None
        return sorted([n for n in self.tree.get('nodes',[]) if n.get('project_id')==pid and n.get('parent_id')],key=lambda n:(n['status']=='discarded',-n['priority'],n['created_at']))

    def plans(self):
        plans=list(self.experiments.get('experiments',[]));ids={n['id'] for n in self.nodes()}
        registered={p['node_id'] for p in plans}
        for node in self.nodes():
            if node['id'] in registered:continue
            for key in ['experiment','expected_experiment','experiment_plan']:
                if node.get('metadata',{}).get(key):
                    plans.append(dict(id='design:'+node['id'],title='예상 설계 · '+node['title'],content=node['metadata'][key]));break
        if self.project:
            ids.update(n['id'] for n in self.tree.get('nodes',[]) if n.get('project_id')==self.project['id'])
        for note in reversed(self.tree.get('notes',[])):
            if note['node_id'] in ids and note['kind']=='experiment' and not note['title'].startswith('실행 계획:'):
                plans.append(note)
        return plans

    def runs(self):
        runs=[]
        for plan in self.experiments.get('experiments',[]):
            runs.extend({**r,'title':plan['spec']['title']} for r in plan.get('runs',[]))
        return sorted(runs,key=lambda r:r['queued_at'],reverse=True)

    @staticmethod
    def update_list(widget,values):
        values=values or [('','기록 없음')]
        if widget.values==values:return
        selected=widget.current_value;widget.values=values
        widget.current_value=selected if selected in {v[0] for v in values} else values[0][0]
        widget._selected_index=next(i for i,v in enumerate(values) if v[0]==widget.current_value)

    def render(self):
        self.update_list(self.idea_list,[(n['id'],('× ' if n['status']=='discarded' else '● ' if n['status'] in {'active','expanded'} else '○ ')+short(n['title'],26)) for n in self.nodes()])
        self.update_list(self.plan_list,[(p['id'],short(p.get('spec',{}).get('title',p.get('title','계획')),26)) for p in self.plans()])
        self.update_list(self.run_list,[(r['id'],STATES.get(r['state'],r['state'])+' · '+short(r['title'],22)) for r in self.runs()])
        selected={2:self.idea_list.current_value,3:self.plan_list.current_value,4:self.run_list.current_value}.get(self.tab,'')
        key=(self.project['id'] if self.project else '',self.tab,selected)
        if key!=self.body_key:
            self.body_key=key;self.body.buffer.cursor_position=0;self.body.window.vertical_scroll=0
        if self.resource_form:self.update_resource_form()
        if self.tab==0:
            if self.welcome:
                width=self.app.output.get_size().columns
                path=LOGO_ASSETS/'terminal-logo-panel.txt'
                logo=path.read_text() if path.exists() and width>=78 else 'BrainDance\n'
                text=logo+'\n'+(conversation(self.messages[-1:]) if self.messages else '프로젝트를 선택하고 연구 방향을 입력하세요.')
            else:text=conversation(self.messages)
        elif self.tab==1:text=progress_view(self.state,self.jobs,self.job_info,self.experiments)
        elif self.tab==2:text=idea_view(self.selected_node(),self.tree)
        elif self.tab==3:text=plan_view(self.selected_plan())
        elif self.tab==4:
            selected=self.selected_run();details=self.run_info if selected and self.run_info and selected['id']==self.run_info['id'] else None
            text=run_view(selected,details)
        elif self.tab==6:text=report_view(self.reports)
        else:text=self.settings_text()
        self.update_body(text,follow=self.tab==0 and self.follow and not self.welcome and not has_focus(self.body)())

    def settings_text(self):
        lines=['연결 계정','']
        for p in self.providers.get('providers',[]):
            lines.extend([p['name']+' · '+(p.get('plan_label') or p.get('auth_label') or '플랜 미확인'),provider_line({'providers':[p]}),'최근 확인 '+clock(p.get('checked_at')),''])
        resource=resource_info(self.compute,self.project['id'] if self.project else '')
        lines.extend(['실행 환경',resource['text']])
        if resource['profile']:
            p=resource['profile']
            if p['kind']=='ssh':lines.append('SSH 대상 '+p.get('host','')+(' · '+p['user'] if p.get('user') else '')+(' · 포트 '+str(p['port']) if p.get('port') else ' · SSH 별칭 설정 사용'))
            lines.append('조회 시각 '+clock(resource['inventory'].get('checked_at'))+' · 아래 장치 조회로 갱신')
            if resource['inventory'].get('error'):lines.append(connection_error(resource['inventory']['error']))
            for d in resource.get('devices',[]):
                lines.extend(['',device_label(d),'장치 ID '+d['id']])
                if d.get('memory_total_mb') is not None:lines.append(f"최근 GPU 메모리 {d.get('memory_used_mb','?')} / {d['memory_total_mb']} MB · 사용률 {d.get('utilization_percent','?')}%")
            a=resource['assignment'];lines.extend(['','시간 예산 '+str(a['time_budget_minutes'])+'분 · 동시 실험 '+str(a['max_parallel_runs'])+'개'])
        link=self.reports.get('link');lines.extend(['','Notion · '+('연결됨' if self.reports.get('connected') and link else '설정 필요')+(' · 자동 동기화 ON' if link and link['auto_sync'] else ''),'결과 탭에서 보고서와 그래프를 확인할 수 있습니다.'])
        lines.extend(['','조작','탭 클릭 / Alt+1–7 / Ctrl+B 다음 1–7 또는 N·P','Ctrl+P 프로젝트 · Ctrl+O 입력 방식 · PageUp/Down 기록 스크롤',
            '모든 탭의 입력은 같은 프로젝트 대화에 기록됩니다.','/settings · /gpt · /claude · /ssh · /gpu · /notion · /reports · /projects · /new · /help · /exit','/delete 삭제 · /trash 휴지통 · /restore 복원 · /purge 완전 삭제 (이름 확인)'])
        return '\n'.join(lines)

    async def call(self,fn,*args):
        """Daemon I/O: quitting the view never waits for a slow SSH/status request."""
        loop=asyncio.get_running_loop();future=loop.create_future()
        def deliver(value,error):
            if future.done():return
            if error:future.set_exception(error)
            else:future.set_result(value)
        def worker():
            try:value=fn(*args);error=None
            except Exception as exc:value=None;error=exc
            with suppress(RuntimeError):loop.call_soon_threadsafe(deliver,value,error)
        threading.Thread(target=worker,daemon=True,name='braindance-ui-request').start()
        return await future

    def spawn(self,coroutine):return self.app.create_background_task(self.guard(coroutine))

    async def guard(self,coroutine):
        try:await coroutine;self.error=''
        except Exception as exc:self.error=safe_text(exc)
        finally:self.wakeup.set();self.app.invalidate()

    async def select_project(self,project):
        if self.project:self.drafts[self.project['id']]=(self.editor.text,self.mode,self.reply_to,self.scope)
        self.epoch+=1;self.project=project;self.state={};self.messages=[];self.jobs=[];self.experiments={};self.job_info=None;self.run_info=None;self.reports={}
        self.editor.text,self.mode,self.reply_to,self.scope=self.drafts.get(project['id'],('',0,None,None))
        self.welcome=not getattr(self.args,'no_banner',False);self.follow=True;self.unread=False;self.error='';self.notice='';self.wakeup.set();self.app.layout.focus(self.editor)

    async def refresh(self):
        epoch=self.epoch
        tree,compute=await asyncio.gather(self.call(self.client.request,'/api/tree'),self.call(self.client.request,'/api/compute'))
        self.tree,self.compute=tree,compute;self.projects=[p for p in tree['projects'] if not p.get('deleted_at')]
        if not self.initialized:
            self.initialized=True;selector=getattr(self.args,'project',None)
            if selector is not None:await self.select_project(await self.call(self.client.project,selector))
            elif len(self.projects)==1:await self.select_project(self.projects[0])
            else:self.project_dialog()
            epoch=self.epoch
        if self.project and not any(p['id']==self.project['id'] for p in self.projects):
            self.epoch+=1;self.project=None;self.messages=[];self.state={};self.jobs=[];self.experiments={};self.job_info=None;self.run_info=None;self.editor.text='';self.reply_to=None;self.scope=None;self.project_dialog();return
        if not self.project:return
        project=self.project;pid=project['id'];root=next((n for n in tree['nodes'] if n.get('project_id')==pid and n['parent_id'] is None),None)
        if not root:return
        query='?'+urllib.parse.urlencode(dict(project_id=pid))
        state,chat,experiments,reports=await asyncio.gather(self.call(self.client.request,'/api/control'+query),self.call(self.client.request,'/api/chat'+query),self.call(self.client.request,'/api/experiments?'+urllib.parse.urlencode(dict(node_id=root['id']))),self.call(self.client.request,'/api/reports'+query))
        if epoch!=self.epoch:return
        before={m['id']:(m['state'],m['content']) for m in self.messages}
        if before and any(m['id'] not in before or before[m['id']]!=(m['state'],m['content']) for m in chat['messages']):
            self.welcome=False
            if self.tab!=0 or not self.follow:self.unread=True
        self.state,self.messages,self.experiments=state,chat['messages'],experiments
        self.reports=reports
        self.jobs=sorted([j for j in tree.get('research_jobs',[]) if j['project_id']==pid],key=lambda j:j['created_at'],reverse=True)
        selected=self.selected_run();chosen=selected or next((r for r in self.runs() if r['state'] in {'running','queued'}),None) or next(iter(self.runs()),None)
        info_tasks=[]
        if self.jobs:info_tasks.append(self.call(self.client.request,'/api/research/job?'+urllib.parse.urlencode(dict(id=self.jobs[0]['id']))))
        if chosen:info_tasks.append(self.call(self.client.request,'/api/run?'+urllib.parse.urlencode(dict(id=chosen['id']))))
        info=await asyncio.gather(*info_tasks) if info_tasks else []
        if epoch!=self.epoch:return
        self.job_info=info.pop(0) if self.jobs else None;self.run_info=info.pop(0) if chosen else None
        self.transport_error='';self.app.invalidate()

    async def poll(self):
        while True:
            try:await self.refresh()
            except Exception as exc:self.transport_error=safe_text(exc);self.app.invalidate()
            self.wakeup.clear()
            with suppress(asyncio.TimeoutError):await asyncio.wait_for(self.wakeup.wait(),2)

    async def refresh_providers(self,force=False):
        self.providers=await self.call(self.client.request,'/api/providers/refresh' if force else '/api/providers',{} if force else None)
        self.app.invalidate()

    async def accounts(self):
        while True:
            try:await self.refresh_providers()
            except Exception:pass
            await asyncio.sleep(60)

    async def hardware(self):
        while True:
            resource=resource_info(self.compute,self.project['id'] if self.project else '')
            profile=resource['profile']
            if profile and time.monotonic()-self.last_probe.get(profile['id'],0)>60:
                with suppress(Exception):await self.probe(profile['id'])
            await asyncio.sleep(5)

    async def probe(self,profile_id):
        if profile_id in self.probing:return
        self.probing.add(profile_id);self.last_probe[profile_id]=time.monotonic();self.notice='장치 연결을 확인하는 중…';self.app.invalidate()
        try:
            receipt=await self.call(self.client.request,'/api/compute/probe',dict(profile_id=profile_id))
            self.compute=await self.call(self.client.request,'/api/compute')
            self.notice='장치 조회 완료 · '+clock(receipt.get('checked_at')) if receipt.get('connected') else '연결 실패 · '+connection_error(receipt.get('error',''))
        finally:self.probing.discard(profile_id);self.wakeup.set();self.app.invalidate()

    async def probe_selected(self):
        resource=resource_info(self.compute,self.project['id'] if self.project else '')
        if not resource['profile']:raise ClientError('먼저 서버·GPU를 선택하세요.')
        await self.probe(resource['profile']['id'])

    def accept(self):
        if self.editor.text.strip() in {'/exit','/quit'}:
            self.app.exit();return
        completion=self.editor.buffer.complete_state
        if completion and completion.current_completion:self.editor.buffer.apply_completion(completion.current_completion)
        text=self.editor.text.strip()
        if not text or self.sending:return
        if text.startswith('/'):
            self.editor.text='';self.spawn(self.slash(text));return
        if not self.project:self.project_dialog();return
        self.spawn(self.send(text))

    async def send(self,text):
        project=dict(self.project);epoch=self.epoch;mode=MODES[self.mode][0];reference=dict(self.reply_to) if self.reply_to else None
        if self.scope:text='대상 '+self.scope['kind']+': '+self.scope['title']+'\n\n'+text
        payload_key=(project['id'],text,mode,json.dumps(reference,sort_keys=True))
        request_id=self.pending.setdefault(payload_key,str(uuid.uuid4()))
        self.sending=True;self.welcome=False;original=self.editor.text;self.notice='메시지 전송 중…';self.app.invalidate()
        try:
            await self.call(self.client.send,project,text,mode,request_id,reference)
            self.pending.pop(payload_key,None)
            if epoch==self.epoch:
                if self.editor.text==original:self.editor.text=''
                self.reply_to=None;self.scope=None;self.tab=0;self.notice='같은 프로젝트 대화에 전송했습니다.'
            else:self.notice='이전 프로젝트에 메시지를 전송했습니다.'
        finally:self.sending=False;self.wakeup.set();self.app.invalidate()

    async def slash(self,text):
        words=shlex.split(text[1:]);command=words[0] if words else 'help'
        if command in {'quit','exit'}:self.app.exit();return
        if command in {'settings','설정'}:self.select_tab(5)
        elif command in {'gpt','claude'}:self.provider_dialog('GPT' if command=='gpt' else 'Claude')
        elif command=='ssh':self.ssh_dialog()
        elif command=='gpu':self.resource_dialog()
        elif command=='notion':
            if len(words)>1 and words[1]=='sync':await self.report_action(True)
            else:await self.notion_dialog()
        elif command in {'reports','report'}:self.select_tab(6)
        elif command in {'projects','project'}:self.project_dialog()
        elif command=='new':self.new_project_dialog()
        elif command in {'delete','trash','restore','purge'}:
            try:
                with redirect_stderr(io.StringIO()):args=parser().parse_args(words)
            except SystemExit as error:
                raise ClientError('/delete [--project 이름] · /trash · /restore --project 이름 · /purge --project 이름') from error
            if command=='delete':
                project=await self.call(self.client.project,args.project) if hasattr(args,'project') else self.project
                if not project:raise ClientError('삭제할 프로젝트를 선택하세요.')
                self.delete_dialog(project)
            elif command=='trash' or not hasattr(args,'project'):await self.trash_dialog()
            else:
                project=await self.call(lambda:self.client.project(args.project,deleted=True))
                if command=='restore':await self.restore_project(project)
                else:await self.purge_dialog(project,preview_only=args.preview)
        elif command=='help':self.text_dialog('도움말',self.settings_text().split('조작\n')[-1]+'\n\n입력 방식은 Ctrl+O로 바꿉니다. 질문만 / 다음 방향 / 중지 후 재준비를 구분할 수 있습니다.')
        elif command in {'history','chat'}:self.select_tab(0)
        elif command=='status':self.select_tab(1)
        elif command=='tree':self.select_tab(2)
        else:self.editor.text=text;raise ClientError('설정 명령은 /help에서 확인하세요. 연구 지시는 자연어로 입력하세요.')

    def dialog(self,title,body,buttons,focus=None):
        self.error=''
        body=HSplit([body,Window(FormattedTextControl(lambda:short(self.error,64)),height=1,style='class:notice')])
        def activate(text,callback):
            if self.modal_task and not self.modal_task.done():self.notice='저장 처리 중입니다.';return
            result=self.invoke(callback)
            if text in {'저장','등록','자동 시작','삭제','복원','완전 삭제'} and isinstance(result,asyncio.Task):self.modal_task=result
        actions=[Button(t,handler=lambda text=t,callback=f:activate(text,callback)) for t,f in buttons]
        view=Dialog(title=title,body=body,buttons=actions,with_background=True,width=Dimension(preferred=76,max=90))
        floating=Float(content=view);self.container.floats.append(floating);self.modals.append((view,floating))
        self.modal_buttons.append(actions)
        self.app.layout.focus(focus or view);self.app.invalidate()

    def close_dialog(self):
        if not self.modals:return
        if self.modal_task and not self.modal_task.done() and asyncio.current_task() is not self.modal_task:
            self.notice='저장 처리 중입니다.';return
        _,floating=self.modals.pop();self.container.floats.remove(floating)
        self.modal_buttons.pop()
        self.resource_form=None;self.error=''
        self.app.layout.focus(self.modals[-1][0] if self.modals else self.editor);self.app.invalidate()

    def text_dialog(self,title,text,verbatim=False):
        self.dialog(title,TextArea(text=safe_text(text) if verbatim else readable(text),read_only=True,scrollbar=True,height=Dimension(min=4,preferred=12,max=18)),[('닫기',self.close_dialog)])

    def project_dialog(self):
        choices=RadioList([(p['id'],safe_text(p['title'])) for p in self.projects] or [('','프로젝트가 없습니다.')],default=self.project['id'] if self.project else None)
        async def choose():
            project=next((p for p in self.projects if p['id']==choices.current_value),None)
            if not project:raise ClientError('새 프로젝트를 먼저 만드세요.')
            self.close_dialog();await self.select_project(project)
        def delete():
            project=next((p for p in self.projects if p['id']==choices.current_value),None)
            if not project:raise ClientError('삭제할 프로젝트를 선택하세요.')
            self.delete_dialog(project)
        self.dialog('프로젝트',Box(choices,height=Dimension(min=2,preferred=6,max=10),padding=0),[('열기',lambda:self.spawn(choose())),('새 프로젝트',self.new_project_dialog),('삭제',delete),('휴지통',lambda:self.spawn(self.trash_dialog())),('닫기',self.close_dialog)],choices)

    def delete_dialog(self,project):
        project=dict(project)
        async def remove():
            args=parser().parse_args(['delete','--project',project['id']])
            await self.call(dispatch,self.client,args)
            if self.project and self.project['id']==project['id']:
                self.drafts[project['id']]=(self.editor.text,self.mode,self.reply_to,self.scope)
                self.epoch+=1;self.project=None;self.messages=[];self.state={};self.jobs=[];self.experiments={};self.reports={};self.job_info=None;self.run_info=None;self.editor.text='';self.reply_to=None;self.scope=None
            self.projects=await self.call(self.client.projects)
            while self.modals:self.close_dialog()
            self.notice='휴지통으로 이동했습니다. /trash에서 복원할 수 있습니다.'
            self.project_dialog();self.wakeup.set()
        self.dialog('프로젝트 삭제',Label(safe_text(project['title'])+'\n진행 중인 연구를 중지하고 휴지통으로 이동합니다.\n휴지통에서 복원할 수 있습니다.'),[('삭제',lambda:self.spawn(remove())),('취소',self.close_dialog)])

    async def trash_dialog(self):
        rows=(await self.call(self.client.request,'/api/project/trash'))['projects']
        choices=RadioList([(p['id'],safe_text(p['title'])+(' · 정리 미완료' if p.get('cleanup_pending') else '')) for p in rows] or [('','휴지통이 비어 있습니다.')])
        def selected():
            project=next((p for p in rows if p['id']==choices.current_value),None)
            if not project:raise ClientError('휴지통에서 프로젝트를 선택하세요.')
            return project
        self.dialog('휴지통',Box(choices,height=Dimension(min=2,preferred=6,max=10),padding=0),[('복원',lambda:self.spawn(self.restore_project(selected()))),('완전 삭제',lambda:self.spawn(self.purge_dialog(selected()))),('닫기',self.close_dialog)],choices)

    async def restore_project(self,project):
        args=parser().parse_args(['restore','--project',project['id']])
        await self.call(dispatch,self.client,args)
        restored=await self.call(self.client.project,project['id'])
        while self.modals:self.close_dialog()
        await self.select_project(restored);self.notice='프로젝트를 복원했습니다. 연구는 자동으로 재개하지 않습니다.'

    async def purge_dialog(self,project,preview_only=False):
        project=dict(project)
        preview=await self.call(self.client.request,'/api/project/purge-preview?'+urllib.parse.urlencode(dict(project_id=project['id'])))
        if preview_only:self.text_dialog('완전 삭제 미리보기',purge_summary(preview),verbatim=True);return
        confirmation=TextArea(multiline=False)
        async def remove():
            if confirmation.text!=preview['title']:raise ClientError('프로젝트 이름을 정확히 입력해야 완전 삭제할 수 있습니다.')
            args=parser().parse_args(['purge','--project',project['id'],'--confirm-name',confirmation.text])
            result=await self.call(dispatch,self.client,args)
            self.drafts.pop(project['id'],None);self.pending={k:v for k,v in self.pending.items() if k[0]!=project['id']}
            while self.modals:self.close_dialog()
            await self.trash_dialog()
            self.notice=('정리 미완료 · 같은 프로젝트의 완전 삭제를 다시 시도하세요.' if result.get('cleanup_pending') else '완전 삭제했습니다. 로컬 파일 '+file_size(result.get('removed_file_bytes',0))+' 정리')
            if result.get('error'):self.error=safe_text(result['error'])
        self.dialog('프로젝트 완전 삭제',HSplit([Label(purge_summary(preview)),Label('확인: 프로젝트 이름을 그대로 입력하세요.'),confirmation]),[('완전 삭제',lambda:self.spawn(remove())),('취소',self.close_dialog)],confirmation)

    def new_project_dialog(self):
        name=TextArea(multiline=False);goal=TextArea(height=3)
        def next_step():
            if not name.text.strip():self.notice='프로젝트 이름을 입력하세요.';return
            async def create(assignment):
                record=await self.call(self.client.request,'/api/project',dict(name=name.text,goal=goal.text,compute=assignment))
                while self.modals:self.close_dialog()
                project=await self.call(self.client.project,record['project_id']);await self.select_project(project)
            self.resource_dialog(on_apply=create,title='새 프로젝트 · 실행 환경')
        self.dialog('새 프로젝트',HSplit([Label('프로젝트 이름'),name,Label('연구 목표'),goal]),[('다음 · 서버와 GPU',next_step),('취소',self.close_dialog)],name)

    def resource_dialog(self,on_apply=None,title='서버와 GPU'):
        if not self.project and on_apply is None:raise ClientError('프로젝트를 먼저 선택하세요.')
        current=resource_info(self.compute,self.project['id'] if self.project else '')['assignment'] or {}
        profiles=self.compute.get('profiles',[]) or [dict(id='local',name='로컬 CPU',kind='local')]
        profile=RadioList([(p['id'],safe_text(p['name'])+' · '+p['kind']) for p in profiles],default=current.get('profile_id','local'),select_on_focus=True)
        devices=CheckboxList([('cpu','CPU')],default_values=current.get('device_ids',['cpu']))
        minutes=TextArea(text=str(current.get('time_budget_minutes',30)),multiline=False)
        parallel=TextArea(text=str(current.get('max_parallel_runs',1)),multiline=False)
        form=dict(profile=profile,devices=devices,minutes=minutes,parallel=parallel,last=None,initial=current.get('device_ids',['cpu']))
        self.resource_form=form
        async def save():
            assignment=dict(profile_id=profile.current_value,device_ids=list(devices.current_values),time_budget_minutes=int(minutes.text),max_parallel_runs=int(parallel.text),auto_run=False)
            if on_apply:await on_apply(assignment)
            else:
                await self.call(self.client.request,'/api/compute/assignment',dict(project_id=self.project['id'],**assignment));self.close_dialog()
            self.notice='실행 환경을 저장했습니다.';self.wakeup.set()
        self.dialog(title,HSplit([Label('서버'),Box(profile,height=3,padding=0),Label('장치 · 서버 물리 GPU 번호 / UUID로 선택'),Box(devices,height=3,padding=0),VSplit([Label('시간 예산(분)'),minutes,Label('동시 실험'),parallel],padding=1,height=1),Label('장치 조회 후 선택하세요. 저장하면 기존 미실행 계획은 다시 검토합니다.')]),
            [('장치 조회',lambda:self.spawn(self.probe(profile.current_value))),('저장',lambda:self.spawn(save())),('취소',self.close_dialog)],profile)
        self.resource_form=form;self.update_resource_form()

    def update_resource_form(self):
        form=self.resource_form;pid=form['profile'].current_value
        inventory=self.compute.get('inventories',{}).get(pid,{})
        choices=[(d['id'],device_label(d)) for d in inventory.get('devices',[])]
        if pid=='local' and not choices:choices=[('cpu','CPU')]
        choices=choices or [('', '장치 조회가 필요합니다.')]
        widget=form['devices']
        if form['last']!=pid:
            widget.current_values=[d for d in form['initial'] if d in {v[0] for v in choices}] if form['last'] is None else []
            form['last']=pid
        if widget.values!=choices:
            widget.values=choices;widget.current_values=[v for v in widget.current_values if v in {c[0] for c in choices} and v]
            widget._selected_index=0

    def ssh_dialog(self):
        name=TextArea(multiline=False);host=TextArea(multiline=False);user=TextArea(multiline=False);port=TextArea(multiline=False);key=TextArea(multiline=False)
        async def save():
            await self.call(self.client.request,'/api/compute/profile',dict(name=name.text.strip() or host.text.strip(),kind='ssh',host=host.text.strip(),user=user.text.strip(),port=int(port.text) if port.text.strip() else None,identity_file=key.text.strip()))
            self.compute=await self.call(self.client.request,'/api/compute');self.close_dialog();self.notice='SSH 연결을 등록했습니다. 서버·GPU에서 장치를 선택하세요.'
        self.dialog('SSH 추가',HSplit([Label('표시 이름'),name,Label('SSH Host 별칭 또는 주소'),host,Label('사용자 · 비우면 SSH 설정 사용'),user,Label('포트 · 비우면 SSH 설정 사용'),port,Label('기존 개인키 경로 · 선택'),key]),[('등록',lambda:self.spawn(save())),('취소',self.close_dialog)],host)

    async def report_action(self,publish):
        if not self.project:raise ClientError('프로젝트를 먼저 선택하세요.')
        await self.call(self.client.request,'/api/notion/sync' if publish else '/api/reports/build',dict(project_id=self.project['id']))
        self.select_tab(6);self.notice='Notion 동기화를 시작했습니다.' if publish else '보고서와 시각화를 만듭니다.';self.wakeup.set()

    async def open_report(self):
        if not self.project or not self.reports.get('report'):raise ClientError('먼저 보고서를 만들어 주세요.')
        import webbrowser
        url=self.client.url+'/api/reports/preview?'+urllib.parse.urlencode(dict(project_id=self.project['id']))
        await self.call(webbrowser.open,url);self.notice='시각화 보고서: '+url

    async def notion_dialog(self):
        if not self.project:raise ClientError('프로젝트를 먼저 선택하세요.')
        project=dict(self.project);state=await self.call(self.client.request,'/api/notion?'+urllib.parse.urlencode(dict(project_id=project['id'])))
        link=state.get('link') or {};parent=TextArea(text=link.get('parent_id',''),multiline=False)
        token=TextArea(password=True,multiline=False);automatic=Checkbox('이 프로젝트 결과 자동 동기화',checked=bool(link.get('auto_sync')))
        async def save():
            await self.call(self.client.request,'/api/notion/configure',dict(project_id=project['id'],parent=parent.text.strip(),token=token.text.strip(),auto_sync=automatic.checked))
            token.text='';self.close_dialog();self.notice='Notion 연결을 확인하고 저장했습니다.';self.wakeup.set()
        async def disconnect():
            await self.call(self.client.request,'/api/notion/disconnect',{});token.text='';self.close_dialog();self.notice='Notion 연결을 해제했습니다.';self.wakeup.set()
        self.dialog('Notion · '+project['title'],HSplit([Label('상위 페이지 URL 또는 ID'),parent,Label('연결 토큰 · 숨김 입력 / 기존 토큰 유지 시 비우기'),token,automatic,Label('토큰은 이 Mac에만 저장합니다. 연구 대화에 전송하지 않습니다.')]),[('저장',lambda:self.spawn(save())),('연결 해제',lambda:self.spawn(disconnect())),('닫기',self.close_dialog)],parent)

    def provider_dialog(self,name):
        item=next((p for p in self.providers.get('providers',[]) if p['name']==name),{})
        text=provider_line({'providers':[item]})+'\n'+(item.get('plan_label') or '플랜 확인 중')+'\n\n기존 공식 CLI 로그인과 연결합니다. 인증 정보는 대화에 보내지 않습니다.'
        self.dialog(name+' 연결',Label(text),[('로그인',lambda:self.spawn(self.login(name))),('상태 갱신',lambda:self.spawn(self.refresh_providers(True))),('닫기',self.close_dialog)])

    async def login(self,name):
        while self.modals:self.close_dialog()
        command=['codex','login'] if name=='GPT' else ['claude','auth','login']
        result=await run_in_terminal(lambda:subprocess.call(command),in_executor=True)
        self.notice='로그인 완료' if result==0 else '로그인이 완료되지 않았습니다. 설정에서 상태를 확인하세요.'
        await self.refresh_providers(True)

    def require_project(self):
        if not self.project:raise ClientError('프로젝트를 먼저 선택하세요.')
        return self.project['id']

    def start_dialog(self):
        pid=self.require_project()
        current=self.state.get('session')
        if current and current['status'] in {'running','paused','blocked'}:self.select_tab(1);self.notice='기존 자동 연구를 재개하거나 한도를 조정하세요.';return
        cycles=TextArea(text='3',multiline=False);calls=TextArea(text='40',multiline=False);tokens=TextArea(text='1500000',multiline=False);folder=TextArea(multiline=False)
        mode=RadioList([('lite','Lite'),('balanced','Balanced'),('deep','Deep')],default='balanced')
        async def start():
            await self.call(self.client.request,'/api/control/automatic',dict(project_id=pid,action='start',max_cycles=int(cycles.text),max_model_calls=int(calls.text),token_budget=int(tokens.text),context_path=folder.text,mode=mode.current_value))
            self.close_dialog();self.select_tab(1)
        self.dialog('프로젝트 자동 연구 시작',HSplit([Label(self.resource_header()),Label('검토된 실험을 선택한 장치·시간·모델 한도 안에서 자동 실행합니다.'),Label('대상 서버의 연구 폴더'),folder,VSplit([Label('실험 횟수'),cycles,Label('모델 호출 한도'),calls],height=1),Label('토큰 예상·예약 한도'),tokens,Box(mode,height=3,padding=0)]),[('자동 시작',lambda:self.spawn(start())),('취소',self.close_dialog)],folder)

    async def automatic(self,action):
        pid=self.require_project();await self.call(self.client.request,'/api/control/automatic',dict(project_id=pid,action=action));self.notice='자동 연구 '+{'pause':'일시정지','resume':'재개','stop':'중지'}[action]

    def limits_dialog(self):
        pid=self.require_project();usage=self.state.get('usage');session=self.state.get('session')
        if not usage or not session:raise ClientError('자동 연구를 시작하면 한도를 조정할 수 있습니다.')
        calls=TextArea(text=str(usage['max_calls']),multiline=False);tokens=TextArea(text=str(usage['token_budget']),multiline=False)
        async def save():
            await self.call(self.client.request,'/api/control/automatic',dict(project_id=pid,action='limits',session_id=session['id'],max_model_calls=int(calls.text),token_budget=int(tokens.text)));self.close_dialog();self.notice='사용량과 대화를 유지한 채 한도를 늘렸습니다. 재개는 별도 선택입니다.'
        self.dialog('현재 실행 한도',HSplit([Label(f"이미 사용한 호출 {usage['calls']}회 · 토큰 예상·예약 {usage['charged_tokens']:,}"),Label('총 모델 호출 한도'),calls,Label('총 토큰 한도'),tokens]),[('저장',lambda:self.spawn(save())),('취소',self.close_dialog)],calls)

    def reply_issue(self):
        issue=self.issue()
        if not issue:self.notice='현재 답글을 연결할 문제가 없습니다.';return
        self.reply_to=dict(type=issue['type'],id=issue['id']);self.scope=None;self.mode=0;self.select_tab(0);self.notice='문제에 대한 답글을 입력하세요. 같은 대화에 연결됩니다.'

    def direct_idea(self):
        node=self.selected_node()
        if node:self.scope=dict(kind='가설',title=node['title']);self.mode=2;self.select_tab(0)

    def direct_plan(self):
        plan=self.selected_plan()
        if plan:self.scope=dict(kind='실험 계획',title=plan.get('spec',{}).get('title',plan.get('title','계획')));self.mode=2;self.select_tab(0)

    def direct_run(self):
        run=self.selected_run()
        if run:self.reply_to=dict(type='run',id=run['id']);self.scope=None;self.mode=2;self.select_tab(0)

    async def node_status(self,status):
        node=self.selected_node()
        if not node:raise ClientError('가설을 선택하세요.')
        await self.call(self.client.request,'/api/node',dict(id=node['id'],status=status));self.notice='가설을 '+STATES[status]+' 상태로 변경했습니다.'

    def code_dialog(self):
        plan=self.selected_plan();code=(plan or {}).get('spec',{}).get('code')
        self.text_dialog('실험 코드 · 읽기 전용',code or '아직 생성된 실행 코드가 없습니다.',verbatim=True)

    async def cancel_run(self):
        run=self.selected_run()
        if not run or run['state'] not in {'queued','running'}:raise ClientError('진행 중인 실험을 선택하세요.')
        await self.call(self.client.request,'/api/experiment/cancel',dict(run_id=run['id']));self.notice='선택한 실험의 중지를 요청했습니다.'

    async def run(self):
        def start():
            self.app.create_background_task(self.poll());self.app.create_background_task(self.accounts());self.app.create_background_task(self.hardware())
        await self.app.run_async(pre_run=start)
