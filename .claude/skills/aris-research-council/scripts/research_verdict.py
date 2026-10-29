"""Conservative scientific verdicts, distinct from process exit and review readiness."""
import json
import re


def extract(text):
    candidates=[text]+re.findall(r'```(?:json)?\s*(.*?)```',text,re.S)
    for candidate in candidates:
        try:value=json.loads(candidate)
        except (ValueError,TypeError):continue
        if isinstance(value,dict) and isinstance(value.get('research_assessment'),dict):return value['research_assessment']
    return None


def supported(assessment,measured_ids):
    if not isinstance(assessment,dict) or assessment.get('outcome')!='supported':return False
    if not assessment.get('primary_goal') or not assessment.get('scope'):return False
    criteria=assessment.get('criteria')
    if not isinstance(criteria,list) or not criteria:return False
    return all(isinstance(c,dict) and c.get('status')=='pass' and c.get('reason') and
        isinstance(c.get('run_ids'),list) and bool(c['run_ids']) and set(c['run_ids'])<=set(measured_ids)
        for c in criteria)
