"""Run one 40kdc datasheet against another.

Bridges the `wh40kdc` (40kdc-data) JSON schema to the weapon/target dicts that
`dists.dam_dist` consumes, so callers can hand in two datasheets rather than
hand-rolling stat conversion:

    from w40k_damage import attack
    res = attack(attacker_json, defender_json)                  # every weapon
    res = attack(attacker_json, defender_json, weapon='Bolt rifle')

`weapons`/`abilities` may be passed explicitly as {id: json}; if omitted they are
resolved from the installed `wh40kdc` bundle (optional dependency).

Conversion notes, all verified against the 40kdc bundle rather than assumed:

* Keyword VALUES live under ``parameters.value`` -- the top-level ``value`` key is
  absent, so reading it silently drops every rapid-fire/melta/sustained/anti-X.
* Anti-X names its target in ``parameters.target_keyword`` (``'Monster'``), not
  ``target``; the threshold is ``parameters.threshold``.
* A weapon's ``type`` is per WEAPON but profiles are mixed: a melee profile on a
  ranged weapon carries ``range: 'Melee'``. Type is therefore derived per profile.
* Defensive abilities (FNP / invuln / damage reduction / T,W,Sv modifiers) are read
  from the effect tree. ``is-attached`` and ``model-is-leader`` conditions are
  treated as active (the normal state for the units that have them); other
  conditional effects are skipped.

`spillover=True` (the default here) drops `dam_dist`'s cap at the defender's total
wounds, giving damage-per-activation independent of squad size; per-model overkill
is still modelled. Do NOT inflate `models` to emulate this -- Blast and Cleave scale
off `models` and would explode.
"""
import json
import re
from .dists import dam_dist, dd_mean

__all__ = ['Datasheet', 'weapon_profiles', 'defender_profile', 'attack', 'unit_for',
           'variants_of', 'KEYWORD_MAP']

#: 40kdc weapon keyword id -> the string `dists` expects. Keywords absent here are
#: not modelled by the damage engine and are dropped (e.g. `psychic`, which is a
#: targeting restriction rather than damage maths).
KEYWORD_MAP = {
    'lethal-hits': 'lethal hits', 'devastating-wounds': 'devastating wounds',
    'sustained-hits': 'sustained hits', 'rapid-fire': 'rapid fire',
    'ignores-cover': 'ignores cover', 'indirect-fire': 'indirect fire',
    'twin-linked': 'reroll wounds', 'blast': 'blast', 'cleave': 'cleave',
    'torrent': 'torrent', 'melta': 'melta', 'lance': 'lance', 'heavy': 'heavy',
    'assault': 'assault', 'pistol': 'pistol', 'anti': 'anti',
}
_VALUED = ('melta', 'sustained-hits', 'rapid-fire', 'cleave')


def _bundle():
    import wh40kdc
    with open(wh40kdc.__path__[0] + '/_bundle.json') as f:
        return json.load(f)


_CACHE = {}


def _lookup(kind):
    if kind not in _CACHE:
        b = _bundle()
        _CACHE['weapons'] = {w['id']: w for w in b['weapons']}
        _CACHE['abilities'] = {a['ability_id']: a for a in b['abilities']}
        # ~31 datasheets ship one variant PER FACTION (the Defiler has four, with
        # different abilities and keywords). An id-keyed dict keeps whichever came
        # last, so every faction's copy would be built from one arbitrary army's
        # rules -- keep them all and let the caller pick.
        variants = {}
        for u in b['units']:
            variants.setdefault(u['id'], {})[u.get('faction_id')] = u
        _CACHE['variants'] = variants
        _CACHE['units'] = {uid: next(iter(v.values())) for uid, v in variants.items()}
    return _CACHE[kind]


def unit_for(unit_id, faction=None):
    """Datasheet json for `unit_id`, picking the faction's variant where several exist."""
    v = _lookup('variants').get(unit_id) or {}
    if not v:
        raise KeyError(unit_id)
    return v.get(faction) or next(iter(v.values()))


def variants_of(unit_id):
    """{faction_id: datasheet} for a unit id -- >1 entry means faction-specific rules."""
    return dict(_lookup('variants').get(unit_id) or {})


def _kws(profile):
    out = []
    for k in profile.get('keywords', []):
        kid = k.get('keyword_id')
        par = k.get('parameters') or {}
        name = KEYWORD_MAP.get(kid)
        if not name:
            continue
        val = k.get('value') or par.get('value')
        if kid == 'anti':
            tgt = str(par.get('target_keyword') or par.get('target') or 'infantry').lower().replace(' ', '')
            out.append(f"anti-{tgt} {par.get('threshold') or val or 4}+")
        elif kid in _VALUED:
            out.append(f"{name} {val or 1}")
        else:
            out.append(name)
    return out


def weapon_profiles(weapon):
    """40kdc weapon json -> list of `dists` weapon dicts (one per profile)."""
    out = []
    for p in weapon.get('profiles', []):
        s = p.get('stats', {})
        rng = p.get('range')
        melee = rng in (None, 'Melee', 'melee') or (s.get('WS') is not None and s.get('BS') is None)
        skill = (s.get('WS') if melee else s.get('BS')) or s.get('BS') or s.get('WS') or 4
        out.append({
            'name': p.get('name') or weapon.get('name'),
            'weapon_id': weapon.get('id'),
            'type': 'melee' if melee else 'ranged',
            'range': 1 if melee else rng,
            'attacks': str(s.get('A', '1')),
            'bsws': skill,
            'strength': s.get('S', 4),
            'AP': -abs(s.get('AP', 0)),
            'damage': str(s.get('D', '1')),
            'kws': _kws(p),
        })
    return out


def _defensive_effects(effect, out, conditional=False):
    """Collect (kind, value) defensive effects; is-attached/model-is-leader count as active."""
    if isinstance(effect, list):
        for e in effect:
            _defensive_effects(e, out, conditional)
        return
    if not isinstance(effect, dict):
        return
    t = effect.get('type')
    if t == 'conditional':
        ctype = (effect.get('condition') or {}).get('type')
        active = conditional if ctype in ('is-attached', 'model-is-leader') else True
        _defensive_effects(effect.get('effect'), out, active)
        return
    m = effect.get('modifier') or {}
    if m.get('against_attack_type'):
        return                                   # e.g. FNP only vs Psychic attacks
    if not conditional:
        if t == 'feel-no-pain' and m.get('threshold'):
            out.append(('fnp', m['threshold']))
        elif t == 'invulnerable-save' and m.get('invuln_sv'):
            out.append(('invuln', m['invuln_sv']))
        elif t == 'damage-reduction':
            out.append(('damage-reduction', m.get('reduction', 1)))
        elif t == 'stat-modifier' and m.get('stat') in ('T', 'W', 'Sv'):
            val = m.get('value', 0) * (-1 if m.get('operation') == 'subtract' else 1)
            out.append((('set:' if m.get('operation') == 'set' else 'mod:') + m['stat'], val))
    for k, v in effect.items():
        if k in ('effect', 'effects', 'steps', 'sequence', 'then', 'otherwise', 'options'):
            _defensive_effects(v, out, conditional)


def defender_profile(unit, models=None, abilities=None, profile_index=0,
                     ability_filter=None, durations=('permanent',)):
    """40kdc unit json -> a `dists` target dict, with defensive abilities applied.

    durations       -- ability scope durations counted as always-on. The bundle also
                       carries 'phase'/'battle'/'one-use' effects, which are situational
                       and off by default. Pass None to accept every duration.
    ability_filter  -- optional f(ability_id, ability) -> ability | None, applied before
                       the effect tree is read. Use it to inject corrections (e.g. an
                       audit that re-gates abilities the bundle encodes unconditionally)
                       without the library hardcoding them.
    """
    profs = unit.get('profiles') or []
    if not profs:
        return None
    p = profs[profile_index]
    T, Sv, W, inv = p.get('T'), p.get('Sv'), p.get('W'), p.get('invuln_sv')
    if not all((T, Sv, W)):
        return None
    if models is None:
        models = (unit.get('model_count') or {}).get('min', 1)
    abil = abilities if abilities is not None else (_lookup('abilities') if unit.get('ability_ids') else {})
    eff = []
    for aid in unit.get('ability_ids', []):
        a = abil.get(aid) or {}
        if ability_filter is not None:
            a = ability_filter(aid, a)
            if not a:
                continue
        if durations and (a.get('scope') or {}).get('duration') not in durations:
            continue
        _defensive_effects(a.get('effect') or {}, eff)
    extras = []
    for kind, val in eff:
        if kind == 'fnp':
            extras.append(f"feel no pain {val}+")
        elif kind == 'invuln':
            inv = val if not inv or val < inv else inv
        elif kind == 'damage-reduction':
            extras.append('halve damage' if val == 'half' else 'damage reduction 1')
        elif kind == 'mod:T':
            T += val
        elif kind == 'mod:W':
            W += val
        elif kind == 'mod:Sv':
            Sv -= val
        elif kind == 'set:Sv':
            Sv = min(Sv, val)
    if 'stealth' in (unit.get('ability_ids') or []):
        extras.append('stealth')
    return {
        'name': unit.get('name'), 'unit_id': unit.get('id'),
        'toughness': T, 'save': Sv, 'invuln': inv, 'wounds': W, 'models': models,
        'kws': [k.lower().replace(' ', '') for k in unit.get('keywords', [])],  # Spaceless, as in anti-X
        'abilities': sorted(set(extras)),
    }


def _weapons_for(unit, weapons):
    lut = weapons if weapons is not None else _lookup('weapons')
    return [lut[w] for w in unit.get('weapon_ids', []) if w in lut]


def attack(attacker, defender, weapon=None, counts=None, models=None,
           defender_models=None, situation=None, spillover=True,
           weapons=None, abilities=None):
    """Damage `attacker` deals to `defender` in one activation.

    weapon   -- weapon or profile name; None runs every weapon on the datasheet
    counts   -- {weapon_id: n}; default is one of each weapon per attacking model
    models   -- attacker model count (default: datasheet minimum)
    situation-- passed to dam_dist; 'range' may be inches (melta/rapid-fire gate on
                half range) or a bool. Given inches, ranged profiles that cannot reach
                that far are dropped. Melee profiles are always resolved in range.

    -> {'profiles': [{name, type, count, mean, dist}], 'ranged', 'melee', 'total'}
    """
    tgt = defender_profile(defender, models=defender_models, abilities=abilities)
    if tgt is None:
        raise ValueError(f"defender {defender.get('id')} has no usable statline")
    if models is None:
        models = (attacker.get('model_count') or {}).get('min', 1)
    sit = {'cover': False, 'range': False, 'overwatch': False, 'indirect': False}
    sit.update(situation or {})

    rows = []
    for w in _weapons_for(attacker, weapons):
        for p in weapon_profiles(w):
            if weapon and weapon.lower() not in (str(p['name']).lower(), str(w.get('name', '')).lower()):
                continue
            n = (counts or {}).get(w['id'], models)
            if not n:
                continue
            s = dict(sit)
            if p['type'] == 'melee':
                s['range'] = True
            elif isinstance(s['range'], (int, float)) and not isinstance(s['range'], bool):
                if isinstance(p['range'], (int, float)) and p['range'] < s['range']:
                    continue                      # weapon cannot reach the target
            d = dam_dist(p, dict(tgt), s, spillover=spillover)
            if isinstance(d, list):
                d = d[0]
            rows.append({'name': p['name'], 'weapon_id': w['id'], 'type': p['type'],
                         'count': n, 'mean': dd_mean(d) * n, 'dist': d})
    if weapon and not rows:
        raise ValueError(f"no weapon matching {weapon!r} on {attacker.get('id')}")
    return {
        'attacker': attacker.get('id'), 'defender': defender.get('id'),
        'profiles': rows,
        'ranged': sum(r['mean'] for r in rows if r['type'] == 'ranged'),
        'melee': sum(r['mean'] for r in rows if r['type'] == 'melee'),
        'total': sum(r['mean'] for r in rows),
    }


class Datasheet:
    """Thin convenience wrapper: `Datasheet(json).attack(other)`."""

    def __init__(self, unit, weapons=None, abilities=None, models=None, faction=None):
        if isinstance(unit, str):                       # unit id -> look it up
            unit = unit_for(unit, faction)
        self.unit, self.weapons, self.abilities = unit, weapons, abilities
        self.models = models if models is not None else (unit.get('model_count') or {}).get('min', 1)

    @property
    def id(self):
        return self.unit.get('id')

    def target(self, models=None, profile_index=0):
        return defender_profile(self.unit, models=models if models is not None else self.models,
                                abilities=self.abilities, profile_index=profile_index)

    def profiles(self):
        return [p for w in _weapons_for(self.unit, self.weapons) for p in weapon_profiles(w)]

    def attack(self, other, weapon=None, **kw):
        o = other.unit if isinstance(other, Datasheet) else other
        kw.setdefault('models', self.models)
        kw.setdefault('defender_models', other.models if isinstance(other, Datasheet) else None)
        kw.setdefault('weapons', self.weapons)
        kw.setdefault('abilities', self.abilities)
        return attack(self.unit, o, weapon=weapon, **kw)

    def __repr__(self):
        return f"<Datasheet {self.id} x{self.models}>"
