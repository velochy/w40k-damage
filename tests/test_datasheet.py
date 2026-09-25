"""Adapter tests. Skipped unless the optional `wh40kdc` dataset is installed."""
import copy
import pytest

wh40kdc = pytest.importorskip('wh40kdc')
from w40k_damage import Datasheet, attack, weapon_profiles, KEYWORD_MAP, dd_mean
from w40k_damage.datasheet import _resolve


@pytest.fixture(scope='module')
def units():
    return {u.id: u.raw for u in wh40kdc.Dataset.embedded().units.all}


@pytest.fixture(scope='module')
def weapons(units):
    return {w['id']: w for u in units.values() for w in _resolve('weapons', u.get('weapon_ids'), u.get('faction_id'))}


def ability(effect, name='ui'):
    """A permanent 40kdc ability dict, as a UI would build one."""
    return {'ability_id': name, 'name': name, 'scope': {'duration': 'permanent'}, 'effect': effect}


def only(ds, name, count):
    """Copy of `ds` firing `count` of the named weapon and nothing else (edits the weapon dicts)."""
    ws = copy.deepcopy(ds.weapons)
    for w in ws:
        for p in w['profiles']:
            p['count'] = count if name in (w['name'], p['name']) else 0
    return Datasheet(ds.unit, weapons=ws, abilities=ds.abilities, models=ds.models)


def test_target_reads_statline(units):
    t = Datasheet(units['terminator-squad'], models=5).target()
    assert (t['toughness'], t['save'], t['invuln'], t['wounds'], t['models']) == (6, 2, 4, 3, 5)
    assert 'infantry' in t['kws']


def test_target_applies_defensive_abilities(units):
    """The Nightbringer's Necrodermis + FNP come from its ability tree, not its statline."""
    t = Datasheet(units['ctan-shard-of-the-nightbringer']).target()
    assert t['invuln'] == 4
    assert any('feel no pain' in a for a in t['abilities'])
    assert any('damage reduction' in a for a in t['abilities'])


def test_target_picks_model_profile_and_damage_taken(units):
    boyz = units['boyz']
    assert (Datasheet(boyz).target()['wounds'], Datasheet(boyz, profile_index=1).target()['wounds']) == (1, 3)
    t = Datasheet(units['terminator-squad'], models=5, damage_taken=7).target()
    assert (t['models'], t['damage_taken']) == (3, 1)


def test_weapon_keyword_values_are_read(weapons):
    """Values live under parameters.value; a bare mapping silently drops them."""
    assert 'melta 2' in weapon_profiles(weapons['meltagun'])[0]['kws']
    assert 'rapid fire 1' in weapon_profiles(weapons['lasgun'])[0]['kws']


def test_anti_keyword_uses_target_keyword(weapons):
    kws = weapon_profiles(weapons['big-choppa-squighog-boyz'])[0]['kws']
    assert 'anti-monster 4+' in kws and 'anti-vehicle 4+' in kws and 'cleave 2' in kws


def test_multiword_anti_matches_defender_keyword():
    wep = {'profiles': [{'range': 12, 'stats': {'A': 1, 'S': 4, 'AP': 0, 'D': 1, 'BS': 3},
                         'keywords': [{'keyword_id': 'anti', 'parameters': {'target_keyword': 'Epic Hero', 'threshold': 4}}]}]}
    kw = weapon_profiles(wep)[0]['kws'][0]
    dfn = Datasheet({'profiles': [{'T': 4, 'Sv': 3, 'W': 5}], 'keywords': ['Character', 'Epic Hero']}, abilities=[]).target()
    assert kw.split(' ')[0][5:] in dfn['kws']


def test_profile_type_derived_per_profile(weapons):
    """A melee profile can sit on a ranged weapon; type must not come from the weapon."""
    profs = weapon_profiles(weapons['zealots-vindictor'])
    assert {p['type'] for p in profs} == {'ranged', 'melee'}


def test_attack_runs_every_weapon_by_default(units):
    r = Datasheet(units['intercessor-squad'], models=10).attack(Datasheet(units['terminator-squad'], models=5))
    assert len(r['profiles']) > 1 and all(p['count'] == 10 for p in r['profiles'])
    assert r['total'] == pytest.approx(r['ranged'] + r['melee'])


def test_profile_count_selects_weapons(units):
    a, d = only(Datasheet(units['intercessor-squad']), 'Bolt Rifle', 5), Datasheet(units['terminator-squad'])
    r = a.attack(d, situation={'range': 6})
    counted = {p['name'] for p in r['profiles'] if p['count']}
    assert counted == {'Focused Fire', 'Saturation'} and r['melee'] == 0
    assert all(p['each'] > 0 for p in r['profiles'] if p['type'] == 'ranged')   # uncounted profiles still get a per-copy mean


def test_combined_dist(units):
    """dist convolves all counted profiles; spillover off caps it at the wounds left."""
    a, boyz = only(Datasheet(units['intercessor-squad']), 'Bolt Pistol', 10), Datasheet(units['boyz'], models=10)
    r = a.attack(boyz)
    assert dd_mean(r['dist']) == pytest.approx(r['total'], rel=1e-2)  # 1-wound models: no overkill; dd_rep prunes ~0.4%
    capped = a.attack(Datasheet(units['boyz'], models=2), spillover=False)['dist']
    assert max(capped) == 2
    assert dd_mean(attack([a, a], boyz)['dist']) == pytest.approx(2 * r['total'], rel=1e-2)


def test_out_of_range_weapons_are_dropped(units):
    a, rhino = Datasheet(units['intercessor-squad'], models=10), Datasheet(units['rhino'])
    fired = lambda r: {p['name'] for p in r['profiles'] if p['type'] == 'ranged'}
    assert fired(a.attack(rhino, situation={'range': 30})) < fired(a.attack(rhino, situation={'range': 6}))


def test_cleave_scales_with_defender_size(units):
    a = Datasheet(units['kommandos'], models=10)
    small = a.attack(Datasheet(units['intercessor-squad'], models=5))['melee']
    assert a.attack(Datasheet(units['intercessor-squad'], models=10))['melee'] > small


def test_ability_dicts_modify_weapons(units):
    """Buffs are ability dicts; +1 to hit is the same as the engine's 'mod hits 1'."""
    a, d = only(Datasheet(units['intercessor-squad']), 'Bolt Pistol', 5), Datasheet(units['terminator-squad'])
    plus1 = ability({'type': 'roll-modifier', 'target': 'unit', 'modifier': {'roll': 'hit', 'operation': 'add', 'value': 1}})
    buffed = Datasheet(a.unit, weapons=a.weapons, abilities=a.abilities + [plus1], models=5)
    assert all('mod hits 1' in p['kws'] for p in buffed.profiles())
    assert buffed.attack(d)['total'] > a.attack(d)['total']


def test_keyword_grant_respects_weapon_type(units):
    grant = ability({'type': 'keyword-grant', 'target': 'unit',
                     'modifier': {'keywords': ['Sustained Hits 1'], 'weapon_type': 'melee'}})
    ps = Datasheet(units['intercessor-squad'], abilities=[grant]).profiles()
    assert all(('sustained hits 1' in p['kws']) == (p['type'] == 'melee') for p in ps)


def test_incoming_debuff_applies_to_attackers(units):
    """A defender's 'target: attacker' -1 to hit lowers damage against it."""
    a, d = only(Datasheet(units['intercessor-squad']), 'Bolt Pistol', 5), Datasheet(units['terminator-squad'])
    minus1 = ability({'type': 'roll-modifier', 'target': 'attacker', 'modifier': {'roll': 'hit', 'operation': 'subtract', 'value': 1}})
    shielded = Datasheet(d.unit, abilities=d.abilities + [minus1], models=d.models)
    assert shielded.target() == d.target()
    assert a.attack(shielded)['total'] < a.attack(d)['total']


def test_editing_abilities_regates_defence(units):
    """Callers regate abilities by editing the list; the library hardcodes no corrections."""
    u = units['celestian-insidiants']
    assert any('feel no pain' in a for a in Datasheet(u).target()['abilities'])
    assert Datasheet(u, abilities=[]).target()['abilities'] == []


def test_attack_type_gated_defence_is_not_blanket(units):
    """FNP only vs psychic attacks is not a general FNP; leader-gated effects count as active."""
    fnp = lambda **m: {'type': 'feel-no-pain', 'target': 'unit', 'modifier': {'threshold': 4, **m}}
    gated = ability(fnp(against_attack_type='psychic'))
    led = ability({'type': 'conditional', 'condition': {'type': 'is-attached'}, 'effect': fnp()})
    t = lambda a: Datasheet(units['terminator-squad'], abilities=[a]).target()['abilities']
    assert t(gated) == [] and t(led) == ['feel no pain 4+']


def test_situational_durations_off_by_default(units):
    uid = next(u for u, j in units.items()
               if any((a.get('scope') or {}).get('duration') == 'phase' and 'feel-no-pain' in str(a.get('effect'))
                      for a in _resolve('abilities', j.get('ability_ids'), j.get('faction_id'))))
    assert len(Datasheet(units[uid], durations=None).target()['abilities']) >= len(Datasheet(units[uid]).target()['abilities'])


def test_keyword_map_only_contains_modelled_keywords():
    assert 'psychic' not in KEYWORD_MAP and KEYWORD_MAP['cleave'] == 'cleave'
