"""Offline invariants for unpromoted package candidates; never opens sessions."""
import copy
import json

import pytest
from test_csee_smoke import CASES, opening
from arena_kit.cost import total_cost, must_haves_ok
from csee import variants
from csee.agent import CseeAgent
from csee.agents.mert import MertQualityMenuAgent, MertFixedProbeAgent, MertLeverAgent
from csee.agents.mert import MertRawJointMenuAgent


def setup(cls, case_id):
    case = next(c for c in json.loads(CASES.read_text()) if c['case_id'] == case_id)
    sid = case['suppliers'][0]
    threads = {sid: [opening(case, sid)]}
    agent = cls(params=variants.params('v14a'))
    agent.prepare(case, threads)
    return agent, case, threads, sid


def test_quality_menu_preserves_cost_and_must_haves():
    a,c,threads,sid = setup(MertQualityMenuAgent,'case:P11')
    main = dict(unit_price=45,ppm_commitment=300,chargeback_eur_per_complaint=0)
    sheets = a.sheets(c,sid,main,{},None)
    assert [t['ppm_commitment'] for t in sheets] == [300,800,1500]
    assert [t['unit_price'] for t in sheets] == [45,44.77,44.46]
    for t in sheets:
        assert set(t) == set(c['negotiable'])
        assert must_haves_ok(c,t)
        assert total_cost(c,t) <= total_cost(c,main)


def test_quality_does_not_retract_previous_alternative():
    a,c,threads,sid = setup(MertQualityMenuAgent,'case:P11')
    old = dict(unit_price=45,ppm_commitment=800,chargeback_eur_per_complaint=0)
    threads[sid].append({'from':'buyer','term_sheets':[{'terms':old}]})
    a.threads[sid].events = threads[sid]
    sheets = a.sheets(c,sid,dict(unit_price=45,ppm_commitment=300,
                              chargeback_eur_per_complaint=0),{},None)
    assert not any(t['ppm_commitment']==800 for t in sheets)


@pytest.mark.parametrize('cls,cid',[(MertQualityMenuAgent,'case:P11'),(MertFixedProbeAgent,'case:P02')])
@pytest.mark.parametrize('status',['final_offer','agreed'])
def test_candidates_do_not_push_final_or_agreed(cls,cid,status):
    a,c,threads,sid = setup(cls,cid)
    threads[sid][-1]['status'] = status
    assert a.thread_move(c,threads,sid) is None


def test_fixed_probe_one_move_only_and_no_clause():
    a,c,threads,sid = setup(MertFixedProbeAgent,'case:P02')
    msg = a.thread_move(c,threads,sid)
    assert [s['terms'] for s in msg['term_sheets']] == [dict(
        unit_price=368,payment_days=90,index_clause=None)]
    threads[sid].append(dict(msg, **{'from':'buyer'}))
    threads[sid].append(opening(c,sid))
    a.threads[sid].events = threads[sid]
    assert not a.fixed_probe(c,sid)


@pytest.mark.parametrize('cls,parent',[(MertQualityMenuAgent,CseeAgent),(MertFixedProbeAgent,MertLeverAgent)])
def test_unrelated_case_unchanged(cls,parent):
    a,c,threads,sid = setup(cls,'case:P05')
    b = parent(params=variants.params('v14a'))
    b.prepare(c,copy.deepcopy(threads))
    assert a.thread_move(c,threads,sid)['term_sheets'] == b.thread_move(c,threads,sid)['term_sheets']


def test_quality_full_message_contains_each_package():
    a,c,threads,sid = setup(MertQualityMenuAgent,'case:P11')
    msg = a.thread_move(c,threads,sid)
    assert len(msg['term_sheets'])==3
    for sheet in msg['term_sheets']:
        t=sheet['terms']
        assert f"{t['unit_price']:.2f}" in msg['body']
        assert str(t['ppm_commitment']) in msg['body']


def test_raw_joint_menu_keeps_coverage_and_cost():
    a,c,threads,sid = setup(MertRawJointMenuAgent,'case:P18')
    clause=max([t for t in c['term_options']['index_clause'] if t],key=lambda t:t['deadband_pct'])
    main=dict(unit_price=5.1,payment_days=90,contract_months=24,index_clause=clause)
    sheets=a.sheets(c,sid,main,{},None)
    assert len(sheets)==3
    assert sheets[1]['payment_days']==45
    assert sheets[1]['index_clause']['deadband_pct']==3
    for t in sheets:
        assert set(t)==set(c['negotiable'])
        assert t['contract_months']==24
        assert must_haves_ok(c,t)
        assert total_cost(c,t)<=total_cost(c,main)+1e-7


def test_raw_joint_menu_does_not_change_other_case_types():
    a,c,threads,sid=setup(MertRawJointMenuAgent,'case:P11')
    from csee.agents.mert import MertSkipHedgeAgent
    b=MertSkipHedgeAgent(params=variants.params('v14a'))
    b.prepare(c,copy.deepcopy(threads))
    assert a.thread_move(c,threads,sid)['term_sheets']==b.thread_move(c,threads,sid)['term_sheets']


def test_candidate_writer_receives_fixed_scope():
    from csee.writer import LLMWriter
    from csee.agents.mert import MertScopedWriter
    seen=[]
    def complete(system,user):
        seen.append((system,user))
        return 'Thank you. Best regards, Purchasing'
    a,c,threads,sid=setup(MertQualityMenuAgent,'case:P11')
    a.scope_writer=True
    a.writer=LLMWriter(complete)
    a.prepare(c,threads)
    assert isinstance(a.writer,MertScopedWriter)
    msg=a.thread_move(c,threads,sid)
    msg['_write']()
    system,prompt=seen[-1]
    assert 'Never promise to change' in system
    assert '"payment_days":60' in prompt
    assert '"volume_per_year":15900' in prompt
    assert 'NEGOTIABLE: '+','.join(c['negotiable']) in prompt


def test_fixed_ladder_is_bounded_and_resumes_from_sent_messages():
    from csee.agents.mert import MertFixedLadderAgent
    a,c,threads,sid=setup(MertFixedLadderAgent,'case:P02')
    theirs={'unit_price':374,'payment_days':90,'index_clause':None}
    for price in [364,366,368,369]:
        t=a.next_terms(c,threads,sid,theirs,{},None,9)
        assert t['unit_price']==price
        assert a.sheets(c,sid,t,{},None)==[t]
        threads[sid].append({'from':'buyer','term_sheets':[{'terms':t}]})
        a.threads[sid].events=threads[sid]
    assert not a.fixed_probe(c,sid)
    b=MertFixedLadderAgent(params=variants.params('v14a'))
    b.prepare(c,threads)
    assert not b.fixed_probe(c,sid)


@pytest.mark.parametrize('cid',['case:P08','case:P18'])
def test_raw_focused_preserves_main_package(cid):
    from csee.agents.mert import MertConsistentAgent,MertRawFocusedAgent
    a,c,threads,sid=setup(MertRawFocusedAgent,cid)
    b=MertConsistentAgent(params=variants.params('v14a'))
    b.prepare(c,copy.deepcopy(threads))
    actual=a.thread_move(c,threads,sid)['term_sheets']
    expected=b.thread_move(c,threads,sid)['term_sheets']
    assert actual==expected[:1]
    assert must_haves_ok(c,actual[0]['terms'])


def test_rfq_anchor_lowers_first_ask_without_breaking_terms():
    from csee.agents.mert import MertRfqAnchorAgent
    a,c,threads,sid=setup(MertRfqAnchorAgent,'case:P05')
    threads={s:[opening(c,s)] for s in c['suppliers']}
    a.prepare(c,threads)
    b=CseeAgent(params=variants.params('v14a'));b.prepare(c,copy.deepcopy(threads))
    for s in c['suppliers']:
        x=a.thread_move(c,threads,s)['term_sheets']
        y=b.thread_move(c,threads,s)['term_sheets']
        assert x[0]['terms']['unit_price'] < y[0]['terms']['unit_price']
        assert all(must_haves_ok(c,t['terms']) for t in x)
    assert a.p.final_push==0


def test_sunday_router_changes_only_rfq_and_quality():
    from csee.agents.mert_sunday import MertSundayRouterAgent
    from csee.agents.router import RouterAgent
    current=RouterAgent.routes()
    candidate=MertSundayRouterAgent.routes()
    assert {k for k in current if current[k]!=candidate[k]}=={'rfq','quality'}
    assert MertSundayRouterAgent.fallback()==RouterAgent.fallback()
    from csee.agents.mert_sunday import MertQualityRouterAgent
    assert {k for k,v in current.items() if MertQualityRouterAgent.routes()[k]!=v}=={'quality'}


def test_rfq_delivery_menu_prices_delay_and_excludes_infeasible_56_days():
    from csee.agents.mert_sunday import MertRfqLeadMenuAgent
    a,c,threads,sid=setup(MertRfqLeadMenuAgent,'case:P05')
    ours={'unit_price':28,'payment_days':90,'lead_time_days':35}
    sheets=a.sheets(c,sid,ours,{},None)
    assert len(sheets)==3
    assert sheets[-1]['lead_time_days']==42
    assert all(must_haves_ok(c,t) for t in sheets)
    assert total_cost(c,sheets[-1]) <= total_cost(c,sheets[-2])*(1-a.p.trade_gain)+.01


@pytest.mark.parametrize('cid',['case:P08','case:P18'])
def test_raw_long_keeps_clause_and_coverage_without_extra_buyer_cost(cid,monkeypatch):
    from csee.agents.mert_sunday import MertRawLongAgent
    from csee.agents.mert_dossier import PlanMesoRawDossierClaims
    a,c,threads,sid=setup(MertRawLongAgent,cid)
    y={'unit_price':4.71,'payment_days':90,'contract_months':24,
       'index_clause':c['term_options']['index_clause'][-1]}
    monkeypatch.setattr(PlanMesoRawDossierClaims,'next_terms',lambda *args:copy.deepcopy(y))
    x=a.next_terms(c,threads,sid,y,{},None,9)
    assert x['contract_months']==36
    assert x['index_clause']==y['index_clause']
    assert x['unit_price']==y['unit_price']
    assert must_haves_ok(c,x)
    assert total_cost(c,x)<=total_cost(c,y)+.01
    monkeypatch.setattr(PlanMesoRawDossierClaims,'sheets',lambda *args:[copy.deepcopy(y)])
    actual=a.sheets(c,sid,y,{},None)[0]
    assert actual['contract_months']==36
    assert actual['index_clause']==y['index_clause']


@pytest.mark.parametrize('cid',['case:P18','case:P05'])
def test_cash_first_preserves_clause_cost_and_recorded_main(cid):
    from csee.agents.mert_sunday import MertRawCashFirstAgent,MertRfqCashFirstAgent
    cls=MertRawCashFirstAgent if cid.endswith('18') else MertRfqCashFirstAgent
    a,c,threads,sid=setup(cls,cid)
    main={'unit_price':5.2,'payment_days':90,'contract_months':24,
          'index_clause':c['term_options']['index_clause'][-1]} if cid.endswith('18') else {
              'unit_price':28,'payment_days':90,'lead_time_days':35}
    before=copy.deepcopy(main)
    sheets=a.sheets(c,sid,main,{},None)
    assert sheets[0]['payment_days']==14
    assert sheets[0].get('index_clause')==before.get('index_clause')
    assert total_cost(c,sheets[0])<=total_cost(c,before)+.01
    assert all(must_haves_ok(c,t) for t in sheets)
    assert main==sheets[0]


def test_cash_first_does_not_retract_prior_quote():
    from csee.agents.mert_sunday import MertRfqCashFirstAgent
    a,c,threads,sid=setup(MertRfqCashFirstAgent,'case:P05')
    prior={'unit_price':29,'payment_days':14,'lead_time_days':35}
    a.threads[sid].events.append({'from':'buyer','term_sheets':[{'terms':prior}]})
    sheets=a.sheets(c,sid,{'unit_price':28,'payment_days':90,'lead_time_days':35},{},None)
    assert not any(t['payment_days']==14 and t['unit_price']<29 for t in sheets)


def test_quality_reciprocity_uses_observed_steps_and_stays_below_ask(monkeypatch):
    from csee.agents.mert_sunday import MertQualityReciprocalAgent
    a,c,threads,sid=setup(MertQualityReciprocalAgent,'case:P11')
    a.threads[sid].their_prices=[47,46,45.5]
    a.threads[sid].our_prices=[39.24,40.34]
    main={'unit_price':40.89,'ppm_commitment':300,'chargeback_eur_per_complaint':0}
    monkeypatch.setattr(MertQualityMenuAgent,'next_terms',lambda *args:copy.deepcopy(main))
    t=a.next_terms(c,threads,sid,{'unit_price':45.5},{},None,6)
    assert t['unit_price']==41.34
    assert t['unit_price']<45.5
    assert must_haves_ok(c,t)
    assert a.p.final_push==0


@pytest.mark.parametrize('prices,expected',[
    ([47,46.5,46],41.34),
    ([47,46,45.5],40.89),
    ([47,46.9,46.8],40.89),
])
def test_measured_quality_requires_repeated_coarse_steps(monkeypatch,prices,expected):
    from csee.agents.mert_sunday import MertQualityMeasuredAgent
    a,c,threads,sid=setup(MertQualityMeasuredAgent,'case:P11')
    a.threads[sid].their_prices=prices
    a.threads[sid].our_prices=[40.34]
    main={'unit_price':40.89,'ppm_commitment':300,'chargeback_eur_per_complaint':0}
    monkeypatch.setattr(MertQualityMenuAgent,'next_terms',lambda *args:copy.deepcopy(main))
    result=a.next_terms(c,threads,sid,{'unit_price':prices[-1]},{},None,6)
    assert result['unit_price']==expected
