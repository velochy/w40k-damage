import pytest
from w40k_damage.dists import (dam_dist, dd_mean, successful_atk_dist, dd_from_str, get_hit_probs, atk_success_prob,
                               find_kw, convolve, threshold_ddist)

MELEE = {'type': 'melee', 'range': 1, 'attacks': '4', 'bsws': 3, 'strength': 7,
         'AP': -1, 'damage': '2', 'kws': []}
CHAFF = {'toughness': 5, 'save': 5, 'invuln': None, 'wounds': 1,
         'kws': ['infantry'], 'abilities': []}


def atk_mean(kws, models, wep=MELEE, tgt=CHAFF):
    return dd_mean(successful_atk_dist({**wep, 'kws': kws}, {**tgt, 'models': models}))


def test_dd_from_str():
    assert dd_mean(dd_from_str('2')) == 2
    assert dd_mean(dd_from_str('D6')) == 3.5
    assert dd_mean(dd_from_str('D6+1')) == 4.5


def test_find_kw_value_vs_bare_vs_absent():
    assert find_kw('cleave', ['cleave 2']) == '2'
    assert find_kw('cleave', ['cleave']) == ''       # present but valueless
    assert find_kw('cleave', ['blast']) is None      # absent


@pytest.mark.parametrize('kws,models,expected_attacks', [
    (['cleave 1'], 10, 6),      # 4 base + 1 per full 5
    (['cleave 2'], 10, 8),      # 4 base + 2 per full 5
    (['cleave'], 10, 6),        # bare 'cleave' == cleave 1
    (['cleave 2'], 20, 12),     # scales with target size
    (['cleave 2'], 4, 4),       # fewer than 5 models -> no bonus
    (['cleave 2'], 9, 6),       # rounds down: one full 5
    (['blast'], 10, 6),         # blast unchanged by the cleave work
    ([], 10, 4),
])
def test_cleave_and_blast_scale_off_target_models(kws, models, expected_attacks):
    """Cleave X is melee Blast: +X attacks per full 5 models in the target unit."""
    base = atk_mean([], models)                       # 4 attacks' worth of successes
    assert atk_mean(kws, models) == pytest.approx(base * expected_attacks / 4)


def test_cleave_stacks_with_blast():
    assert atk_mean(['blast', 'cleave 2'], 10) == pytest.approx(atk_mean([], 10) * 10 / 4)


def test_melta_only_within_half_range():
    wep = {'type': 'ranged', 'range': 24, 'attacks': '2', 'bsws': 3, 'strength': 9,
           'AP': -4, 'damage': 'D6', 'kws': ['melta 2']}
    tgt = {'toughness': 9, 'save': 3, 'invuln': None, 'wounds': 10, 'models': 1,
           'kws': ['vehicle'], 'abilities': []}
    close = dd_mean(dam_dist(wep, tgt, {'range': 6}))
    far = dd_mean(dam_dist(wep, tgt, {'range': 18}))
    assert close > far


def test_rapid_fire_only_within_half_range():
    wep = {'type': 'ranged', 'range': 24, 'attacks': '2', 'bsws': 3, 'strength': 4,
           'AP': 0, 'damage': '1', 'kws': ['rapid fire 2']}
    tgt = {**CHAFF, 'models': 1}
    assert dd_mean(dam_dist(wep, tgt, {'range': 6})) > dd_mean(dam_dist(wep, tgt, {'range': 18}))


def test_spillover_removes_unit_wound_cap():
    """Without spillover, damage is capped at the unit's total wounds."""
    wep = {'type': 'ranged', 'range': 24, 'attacks': '20', 'bsws': 2, 'strength': 10,
           'AP': -3, 'damage': '3', 'kws': []}
    tgt = {'toughness': 3, 'save': 6, 'invuln': None, 'wounds': 1, 'models': 2,
           'kws': ['infantry'], 'abilities': []}
    assert dd_mean(dam_dist(wep, tgt, {})) <= 2
    assert dd_mean(dam_dist(wep, tgt, {}, spillover=True)) > 2


def test_defensive_abilities_reduce_damage():
    wep = {'type': 'ranged', 'range': 48, 'attacks': '10', 'bsws': 3, 'strength': 12,
           'AP': -3, 'damage': 'D6+1', 'kws': []}
    base = {'toughness': 11, 'save': 3, 'invuln': None, 'wounds': 16, 'models': 1,
            'kws': ['monster'], 'abilities': []}
    plain = dd_mean(dam_dist(wep, base, {}, spillover=True))
    for extra in (['feel no pain 5+'], ['damage reduction 1'], ['halve damage']):
        assert dd_mean(dam_dist(wep, {**base, 'abilities': extra}, {}, spillover=True)) < plain
    assert dd_mean(dam_dist(wep, {**base, 'invuln': 4}, {}, spillover=True)) < plain


def test_readme_example_runs():
    wep = {'type': 'ranged', 'range': 24, 'attacks': '3', 'bsws': 3, 'strength': 5,
           'AP': -2, 'damage': '2',
           'kws': ['lethal hits', 'devastating wounds', 'melta d3+2', 'anti-infantry 3+', 'indirect fire']}
    tgt = {'toughness': 7, 'save': 2, 'invuln': None, 'wounds': 10,
           'kws': ['infantry'], 'abilities': ['feel no pain 5+']}
    sit = {'cover': True, 'range': 10, 'overwatch': False, 'indirect': False}
    assert dd_mean(dam_dist(wep, tgt, sit)) == pytest.approx(4.506550, abs=1e-5)  # 11th ed cover: -1 to hit


def test_anti_keyword_applies_only_to_matching_target():
    wep = {'type': 'melee', 'range': 1, 'attacks': '4', 'bsws': 3, 'strength': 7,
           'AP': -1, 'damage': '2', 'kws': ['anti-monster 4+']}
    plain = {**wep, 'kws': []}
    monster = {'toughness': 11, 'save': 3, 'invuln': 4, 'wounds': 16, 'models': 1,
               'kws': ['monster'], 'abilities': []}
    infantry = {'toughness': 4, 'save': 3, 'invuln': None, 'wounds': 2, 'models': 5,
                'kws': ['infantry'], 'abilities': []}
    assert dd_mean(dam_dist(wep, monster, {}, spillover=True)) > dd_mean(dam_dist(plain, monster, {}, spillover=True))
    assert dd_mean(dam_dist(wep, infantry, {}, spillover=True)) == pytest.approx(
        dd_mean(dam_dist(plain, infantry, {}, spillover=True)))


RANGED = {**MELEE, 'type': 'ranged', 'range': 24}
ELITE = {'toughness': 4, 'save': 3, 'invuln': None, 'wounds': 1, 'kws': ['infantry'], 'abilities': []}
hit = lambda kws=(), abilities=(), wep=RANGED, **sit: get_hit_probs(
    {**wep, 'kws': list(kws)}, {**ELITE, 'abilities': list(abilities)}, sit)[0]
save_fail = lambda wep, **sit: atk_success_prob(wep, ELITE, sit, crit_hit=False) / atk_success_prob(wep, {**ELITE, 'save': 7}, sit, crit_hit=False)


def test_cover_is_minus_one_to_hit():  # 11th ed
    assert hit(cover=True) == pytest.approx(3 / 6) and hit() == pytest.approx(4 / 6)
    assert save_fail(RANGED, cover=True) == pytest.approx(save_fail(RANGED))


def test_cover_exemptions():
    assert hit(wep=MELEE, cover=True) == hit(wep=MELEE)
    assert hit(['ignores cover'], cover=True) == hit()


def test_cover_and_stealth_capped_at_minus_one():
    assert hit(abilities=['stealth']) == hit(cover=True) == hit(abilities=['stealth'], cover=True)
    assert hit(['mod hits 1'], cover=True) == hit()
