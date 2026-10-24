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
