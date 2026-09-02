"""Adapter tests. Skipped unless the optional `wh40kdc` dataset is installed."""
import pytest

wh40kdc = pytest.importorskip('wh40kdc')
from w40k_damage import Datasheet, attack, weapon_profiles, defender_profile, KEYWORD_MAP
from w40k_damage.datasheet import _lookup


@pytest.fixture(scope='module')
def units():
    return _lookup('units')


@pytest.fixture(scope='module')
def weapons():
    return _lookup('weapons')


def test_defender_profile_reads_statline(units):
    t = defender_profile(units['terminator-squad'], models=5)
    assert (t['toughness'], t['save'], t['invuln'], t['wounds'], t['models']) == (5, 2, 4, 3, 5)
    assert 'infantry' in t['kws']


def test_defender_profile_applies_defensive_abilities(units):
    """The Nightbringer's Necrodermis + FNP come from its ability tree, not its statline."""
    t = defender_profile(units['ctan-shard-of-the-nightbringer'], models=1)
    assert t['invuln'] == 4
    assert any('feel no pain' in a for a in t['abilities'])
    assert any('damage reduction' in a for a in t['abilities'])


def test_weapon_keyword_values_are_read(weapons):
    """Values live under parameters.value; a bare mapping silently drops them."""
    melta = [p for p in weapon_profiles(weapons['meltagun'])][0]
    assert 'melta 2' in melta['kws']
    lasgun = weapon_profiles(weapons['lasgun'])[0]
    assert 'rapid fire 1' in lasgun['kws']


def test_anti_keyword_uses_target_keyword(weapons):
    """Anti-X names its target in parameters.target_keyword, not parameters.target."""
    kws = weapon_profiles(weapons['big-choppa-squighog-boyz'])[0]['kws']
    assert 'anti-monster 4+' in kws and 'anti-vehicle 4+' in kws
    assert 'cleave 2' in kws


def test_profile_type_derived_per_profile(weapons):
    """A melee profile can sit on a ranged weapon; type must not come from the weapon."""
    profs = weapon_profiles(weapons['zealots-vindictor'])
    assert {p['type'] for p in profs} == {'ranged', 'melee'}
    for p in profs:
        assert p['range'] == 1 if p['type'] == 'melee' else p['range'] > 1


def test_attack_runs_every_weapon_by_default(units):
    r = attack(units['intercessor-squad'], units['terminator-squad'], models=10, defender_models=5)
    assert len(r['profiles']) > 1
    assert r['total'] == pytest.approx(r['ranged'] + r['melee'])
    assert all(p['count'] == 10 for p in r['profiles'])


def test_attack_can_select_one_weapon(units):
    r = attack(units['intercessor-squad'], units['terminator-squad'],
               weapon='Bolt rifle', models=10, defender_models=5, situation={'range': 6})
    assert [p['name'] for p in r['profiles']] == ['Bolt rifle']
    assert r['melee'] == 0 and r['ranged'] > 0


def test_unknown_weapon_raises(units):
    with pytest.raises(ValueError):
        attack(units['intercessor-squad'], units['terminator-squad'], weapon='no such gun')


def test_out_of_range_weapons_are_dropped(units):
    """A numeric situation range excludes weapons that cannot reach."""
    close = attack(units['intercessor-squad'], units['rhino'], models=10, situation={'range': 6})
    far = attack(units['intercessor-squad'], units['rhino'], models=10, situation={'range': 30})
    fired = lambda r: {p['name'] for p in r['profiles'] if p['type'] == 'ranged'}
    assert fired(far) < fired(close)          # 12" pistols drop out at 30"


def test_range_gates_melta(units, weapons):
    """Melta only adds damage inside half range; dam_dist normalises the gate."""
    # need a melta weapon reaching >=18" so 6" is inside half range and 18" is not
    melta = {w for w, j in weapons.items()
             if any('melta' in k and isinstance(p['range'], (int, float)) and p['range'] >= 18
                    for p in weapon_profiles(j) for k in p['kws'])}
    uid = next(u for u, j in units.items()
               if melta & set(j.get('weapon_ids') or ()) and j.get('profiles'))
    a, d = Datasheet(uid), Datasheet('rhino')
    close = a.attack(d, situation={'range': 6})['ranged']
    far = a.attack(d, situation={'range': 18})['ranged']
    assert close > far


def test_cleave_scales_with_defender_size(units):
    """End-to-end: a cleave weapon does more to a big unit than a small one."""
    a = Datasheet('kommandos', models=10)
    small = a.attack(Datasheet('intercessor-squad', models=5))['melee']
    big = a.attack(Datasheet('intercessor-squad', models=10))['melee']
    assert big > small


def test_datasheet_wrapper_matches_functional_api(units):
    a, d = Datasheet('intercessor-squad', models=10), Datasheet('terminator-squad', models=5)
    assert a.attack(d)['total'] == pytest.approx(
        attack(units['intercessor-squad'], units['terminator-squad'],
               models=10, defender_models=5)['total'])


def test_keyword_map_only_contains_modelled_keywords():
    assert 'psychic' not in KEYWORD_MAP        # targeting restriction, not damage maths
    assert KEYWORD_MAP['cleave'] == 'cleave'


def test_ability_filter_hook_can_regate_abilities(units):
    """Callers inject their own corrections; the library hardcodes none."""
    uid = 'celestian-insidiants'
    assert any('feel no pain' in a for a in defender_profile(units[uid])['abilities'])
    drop_all = lambda aid, a: None
    assert defender_profile(units[uid], ability_filter=drop_all)['abilities'] == []


def test_attack_type_gated_defence_is_not_blanket(units):
    """Ezekiel's psychic hood is FNP only vs psychic attacks -> not a general FNP."""
    assert not any('feel no pain' in a for a in defender_profile(units['ezekiel'])['abilities'])


def test_situational_durations_off_by_default(units):
    """Non-permanent scopes are situational; opt in explicitly."""
    uid = next(u for u, j in units.items()
               if any((_lookup('abilities').get(a) or {}).get('scope', {}).get('duration') == 'phase'
                      and 'feel-no-pain' in str((_lookup('abilities').get(a) or {}).get('effect'))
                      for a in j.get('ability_ids', [])))
    off = defender_profile(units[uid])['abilities']
    on = defender_profile(units[uid], durations=None)['abilities']
    assert len(on) >= len(off)


def test_faction_variants_are_not_collapsed():
    """~31 ids ship one datasheet per faction; an id-keyed dict would lose all but one."""
    from w40k_damage import unit_for, variants_of
    multi = {u for u in _lookup('variants') if len(_lookup('variants')[u]) > 1}
    assert multi, 'expected some faction-specific datasheets'
    uid = sorted(multi)[0]
    facs = list(variants_of(uid))
    assert len(facs) > 1
    assert unit_for(uid, facs[0]) is not unit_for(uid, facs[1])
    assert unit_for(uid, 'no-such-faction')['id'] == uid        # falls back
