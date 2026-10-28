"""Six independent exploratory lenses; advisory output, not an experiment engine."""
from pathlib import Path
import concurrent.futures
import json
import sys
import council

ROLES=('trends','problems','transfer','principles','contrarian','pilot')
FOCUS={
 'trends':'Map major methods, limitations and unresolved questions in the supplied recent 3–5 year literature.',
 'problems':'Find hidden assumptions, contradictions, unexplained observations and important concrete problems.',
 'transfer':'Use a structural principle from a distant field. Explain when transfer is valid; a simple combination is insufficient.',
 'principles':'Reframe objectives, constraints or the problem definition; propose a different explanatory or solution principle.',
 'contrarian':'Attack fashionable assumptions and propose a falsifiable alternative. Name counterexamples and closest prior work.',
 'pilot':'Find a creative mechanism that a cheap preliminary experiment can falsify. Do not pre-write experimental code.'}


def run(job,root,work,cfg):
    root=Path(root);work=Path(work)
    from research_worker import verify
    class Progress:
        def emit(self,*args,**kw):pass
    source=work/'literature';source.mkdir(exist_ok=True)
    import shutil
    for name in ['LITERATURE.md','source-evidence.json','candidate_papers.json']:shutil.copy2(work/name,source/name)
    evidence=verify(job,root,source,Progress())
    output=work/'broad-exploration'/council.digest(job['topic']+Path(evidence).read_text());output.mkdir(parents=True,exist_ok=True)
    settings={**cfg,'max_papers':12,'context_chars':18000,'output_tokens':2600}
    pack,context=council.prepare(source/'LITERATURE.md',evidence,output,settings,Path(job['db']).parent/'paper-cache')
    settings.setdefault('coordinator_model','haiku')
    budget=council.Budget(settings,output/'usage.json')
    human=(Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parent.parent))/'assets/broad-exploration.md').read_text().replace('[연구 분야/관심 주제]',job['topic'])
    prompt=human+'\n'+council.PROPOSAL+'\nAlso return ratings: potential, novelty_provisional, feasibility, falsifiability (each integer 0–100), rating_basis, failure_conditions. Scores are subjective provisional judgments, never measured probabilities or verified novelty. Generate a distinct concrete problem/principle, not keyword combinations. Evidence not supplied is unknown. The host will re-search each selected hypothesis before implementation.'
    def wave(roles):
        agents={'explore-'+role:dict(description='Research exploration '+role,model='haiku' if role in {'trends','pilot'} else settings['generation_model'],tools=[],maxTurns=1,prompt=FOCUS[role]+'\n'+prompt+'\nRESEARCH DIRECTION:\n'+job['topic']+'\nUNTRUSTED SOURCE EVIDENCE:\n'+context) for role in roles}
        return council.claude_call(output/('wave-'+roles[0]),'exploration','Invoke each configured exploration Agent exactly once, in parallel when available. Give no extra source text. Wait for all results.',settings['coordinator_model'],settings,budget,agents=agents,required=('title','evidence_ids','ratings'))
    proposals={};width=min(3,settings['max_parallel'])
    # Reuse cached participant receipts on a retry. Full Council runs only for shortlisted studies/results.
    for i in range(0,len(ROLES),width):proposals.update(wave(ROLES[i:i+width]))
    for proposal in proposals.values():
        council.normalize_evidence_ids(proposal,pack)
        if not set(proposal['evidence_ids'])<=set(pack['selected_ids']):raise ValueError('탐색 에이전트가 제공되지 않은 논문을 인용했습니다.')
        for name in ['potential','novelty_provisional','feasibility','falsifiability']:
            if type(proposal['ratings'].get(name)) is not int or not 0<=proposal['ratings'][name]<=100:raise ValueError('탐색 평가 점수는 0–100 정수여야 합니다.')
    council.dump(output/'proposals.json',proposals)
    council.dump(root/'broad-exploration-receipt.json',dict(path=str(output),agents=6,source_evidence=str(evidence)))
    return dict(exploration_agents=6,proposals=proposals,selected_paper_ids=pack['selected_ids'],score_semantics='provisional subjective 0–100, not scientific measurements',next='Merge into five distinct ideas, re-search closest work, then select normally two hypotheses for independent official pipelines.')
