"""Research success is not a successful process or a win against a bad baseline."""
import unittest
from research_reports import result_status,editorial_sections,validate_brief
from research_verdict import extract


class ScientificReportingTests(unittest.TestCase):
    def data(self):
        return dict(title='OFFLINE research report',nodes=[],runs=[dict(id='real-receipt',title='ridge vs Adam',state='succeeded',metric='mse_reduction',direction='maximize',analysis=dict(status='compared',baseline=-.3119,candidate=-.2231),duration_seconds=5)])

    def test_less_bad_than_weak_baseline_is_not_scientific_success(self):
        data=self.data();self.assertEqual(result_status(data),'탐색중')
        data['brief']=dict(research_outcome='not_supported')
        self.assertEqual(result_status(data),'실패')
        data['brief']['research_outcome']='supported'
        self.assertNotEqual(result_status(data),'성공')

    def test_all_primary_criteria_need_reviewed_measured_evidence(self):
        data=self.data();a=dict(outcome='supported',primary_goal='Primary goal',scope='Measured setting',criteria=[dict(criterion='Primary criterion',status='pass',run_ids=['real-receipt'],reason='OFFLINE reviewer assessment fixture')])
        data['study_reports']=[dict(research_assessment=a)]
        self.assertEqual(result_status(data),'성공')
        a['criteria'].append(dict(criterion='Success rate',status='unmeasured',run_ids=[],reason='Not tested'))
        self.assertNotEqual(result_status(data),'성공')
        a['criteria']=a['criteria'][:1];a['criteria'][0]['run_ids']=['invented-run']
        self.assertNotEqual(result_status(data),'성공')

    def test_explanatory_narrative_is_retained_instead_of_metric_dump(self):
        data=self.data();data['brief']=validate_brief(dict(problem='왜 동시 실행이 느려지는가',approach='원인 분리',findings='현재 목표 미달',research_outcome='not_supported',background='제어 루프가 오래된 관측을 사용한다',mechanism='호출 순서와 자원 경합의 구별',experimental_design='동일 관측을 짝지어 대조',interpretation='연산량 감소가 지연 감소를 보장하지 않는다',review_history='Reviewer 지적 후 새로운 대조 실험',next_experiment='실제 KV 공유 대조'))
        data['study_reports']=[dict(title='가설 A',narrative='# 질문\n\n핵심 원인은 무엇인가.\n\n## 반증\n\n독자의 이해를 위한 근거 설명.',review=dict(round=2,max_rounds=4))]
        sections=editorial_sections(data);body='\n'.join(b for _,b in sections)
        self.assertIn('독자의 이해를 위한 근거 설명',body);self.assertIn('2라운드 / 최대 4라운드',body)
        self.assertIn('실패',sections[0][1]);self.assertNotIn('**성공**',body)
        self.assertIn('실제 KV 공유 대조',body)

    def test_scientific_annotation_does_not_replace_original_review_text(self):
        text='Score: 7/10\nVerdict: almost\n```json\n{"research_assessment":{"outcome":"inconclusive"}}\n```'
        self.assertEqual(extract(text)['outcome'],'inconclusive')


if __name__=='__main__':unittest.main()
