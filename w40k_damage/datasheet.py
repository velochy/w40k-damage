"""Run 40kdc datasheets against each other.

Everything is plain 40kdc (`wh40kdc`) json: a unit dict plus lists of its weapon and
ability dicts. Model loadouts and buffs by editing those dicts rather than through
side channels -- set ``count`` on a weapon profile, or append ability dicts whose
effect tree says what they do (e.g. a ``roll-modifier`` of +1 to hit):

    from w40k_damage import Datasheet
    atk = Datasheet(unit, weapons=[...], abilities=[...], models=10)
    atk.attack(Datasheet(other_unit), situation={'cover': True})

Conversion notes, all verified against the 40kdc bundle rather than assumed:

* Keyword VALUES live under ``parameters.value``; Anti-X names its target in
  ``parameters.target_keyword``.
* A weapon's ``type`` is per WEAPON but profiles are mixed: a melee profile on a
  ranged weapon carries ``range: 'Melee'``. Type is therefore derived per profile.
* Ability effects are read from the effect tree: defensive ones (FNP, invuln, damage
  reduction, T/W/Sv) apply to the unit, offensive ones (hit/wound modifiers, re-rolls,
  crit thresholds, A/S/AP, keyword grants) to its weapons, and ``target: attacker``
  ones to weapons attacking it. ``is-attached`` / ``model-is-leader`` conditions
  count as active; other conditional or non-``permanent`` effects are skipped.

`spillover=True` (the default) drops the cap at the defender's total wounds, giving
damage-per-activation; per-model overkill is still modelled. Do NOT inflate `models`
to emulate this -- Blast and Cleave scale off `models`.
"""
import json
import re
from .dists import dam_dist, dd_mean, dd_cap, fulldist_convolve

__all__ = ['Datasheet', 'attack', 'weapon_profiles', 'KEYWORD_MAP']

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
_OWN = (None, 'unit', 'self', 'bearer', 'attached-unit')     # effect targets that buff the ability's owner
_REROLL = {('hit', 'all-failures'): 'reroll hits', ('hit', 'ones'): 'reroll 1s to hit',
           ('wound', 'all-failures'): 'reroll wounds', ('wound', 'ones'): 'reroll 1s to wound'}
_STAT = {'A': 'attacks', 'S': 'strength', 'AP': 'ap'}

_CACHE = {}


def _resolve(kind, ids, faction):
    """Bundle dicts for `ids`, preferring `faction`'s copy of ids shipped once per faction."""
    if not _CACHE:
        import wh40kdc
        with open(wh40kdc.__path__[0] + '/_bundle.json') as f:
            b = json.load(f)
        for k, key in (('weapons', 'id'), ('abilities', 'ability_id')):
            _CACHE[k] = {}
            for x in b[k]:
                _CACHE[k].setdefault(x[key], {})[x.get('faction_id')] = x
    lut = _CACHE[kind]
    return [(lut[i].get(faction) or next(iter(lut[i].values()))) for i in ids or [] if i in lut]


def _kws(profile):
    out = []
    for k in profile.get('keywords', []):
        kid, par = k.get('keyword_id'), k.get('parameters') or {}
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


def _granted_kw(s):
    """Keyword-grant text ('Sustained Hits 1', 'Anti-Infantry 4+') -> 40kdc keyword dict."""
    s = s.strip().lower()
    m = re.fullmatch(r'anti-(.+) (\d)\+', s)
    if m:
        return {'keyword_id': 'anti', 'parameters': {'target_keyword': m[1], 'threshold': int(m[2])}}
    m = re.fullmatch(r'(.+?) (\d+|d\d(?:\+\d+)?)', s)
    base, val = (m[1], m[2].upper()) if m else (s, None)
    return {'keyword_id': base.replace(' ', '-'), 'parameters': {'value': val} if val else {}}


def weapon_profiles(weapon):
    """40kdc weapon json -> list of `dists` weapon dicts (one per profile)."""
    out = []
    for p in weapon.get('profiles', []):
        s = p.get('stats', {})
        rng = p.get('range')
        melee = rng in (None, 'Melee', 'melee') or (s.get('WS') is not None and s.get('BS') is None)
        skill = (s.get('WS') if melee else s.get('BS')) or s.get('BS') or s.get('WS') or 4
        out.append({
            'name': p.get('name') or weapon.get('name'), 'weapon_id': weapon.get('id'),
            'type': 'melee' if melee else 'ranged', 'range': 1 if melee else rng,
            'attacks': str(s.get('A', '1')), 'bsws': skill, 'strength': s.get('S', 4),
            'AP': -abs(s.get('AP', 0)), 'damage': str(s.get('D', '1')), 'kws': _kws(p),
            'count': p.get('count'),
        })
    return out


def _active(effect, conditional=False):
    """Leaf effects that are always on; is-attached / model-is-leader conditions count as met."""
    if isinstance(effect, list):
        for e in effect:
            yield from _active(e, conditional)
        return
    if not isinstance(effect, dict):
        return
    if effect.get('type') == 'conditional':
        ctype = (effect.get('condition') or {}).get('type')
        yield from _active(effect.get('effect'), conditional if ctype in ('is-attached', 'model-is-leader') else True)
        return
    if not conditional and not (effect.get('modifier') or {}).get('against_attack_type'):  # e.g. FNP vs Psychic only
        yield effect
    for k in ('effect', 'effects', 'steps', 'sequence', 'then', 'otherwise', 'options'):
        if k in effect:
            yield from _active(effect[k], conditional)


def _offense_kws(e):
    """Leaf effect -> (engine weapon keywords, weapon type it is limited to or None)."""
    t, m = e.get('type'), e.get('modifier') or {}
    v, sign = m.get('value'), -1 if m.get('operation') == 'subtract' else 1
    wtype = m.get('weapon_type') or m.get('attack_type')
    if t in ('roll-modifier', 'stat-modifier') and not isinstance(v, int):
        return [], None                       # dice-valued or malformed; not modelled
    if t == 'roll-modifier' and m.get('roll') in ('hit', 'wound') and not m.get('context'):
        if m.get('operation') in ('add', 'subtract'):
            return [f"mod {m['roll']}s {sign * v}"], wtype
        if m.get('operation') == 'crit-on':
            return [f"{m['roll']} crit {v}+"], wtype
    elif t == 're-roll' and (m.get('roll'), m.get('subset')) in _REROLL and not m.get('uses'):
        return [_REROLL[m['roll'], m['subset']]], wtype
    elif t == 'stat-modifier' and m.get('stat') in _STAT and m.get('operation') in ('add', 'subtract'):
        return [f"mod {_STAT[m['stat']]} {sign * v}"], wtype
    elif t == 'keyword-grant':
        return _kws({'keywords': [_granted_kw(k) for k in m.get('keywords') or []]}), wtype
    return [], None


class Datasheet:
    """A 40kdc unit with its weapon and ability dicts (resolved from the bundle by id if omitted)."""

    def __init__(self, unit, weapons=None, abilities=None, models=None, profile_index=0,
                 damage_taken=0, durations=('permanent',)):
        fac = unit.get('faction_id')
        self.unit = unit
        self.weapons = weapons if weapons is not None else _resolve('weapons', unit.get('weapon_ids'), fac)
        self.abilities = abilities if abilities is not None else _resolve('abilities', unit.get('ability_ids'), fac)
        self.models = models if models is not None else (unit.get('model_count') or {}).get('min', 1)
        self.profile_index, self.damage_taken, self.durations = profile_index, damage_taken, durations

    def effects(self):
        """Active leaf effects of this unit's abilities."""
        return [e for a in self.abilities
                if not self.durations or (a.get('scope') or {}).get('duration') in self.durations
                for e in _active(a.get('effect') or {})]

    def _offense(self, targets):
        return [kt for e in self.effects() if e.get('target') in targets for kt in [_offense_kws(e)] if kt[0]]

    def profiles(self):
        """`dists` weapon dicts with this unit's own offensive effects applied; count defaults to models."""
        mods = self._offense(_OWN)
        return [p | {'count': self.models if p['count'] is None else p['count'],
                     'kws': p['kws'] + [k for kws, t in mods if t in (None, p['type']) for k in kws]}
                for w in self.weapons for p in weapon_profiles(w)]

    def incoming(self):
        """(keywords, weapon type) modifiers this unit imposes on attacks against it."""
        return self._offense(('attacker',))

    def target(self):
        """`dists` target dict: statline, defensive effects, models and damage already taken."""
        p = (self.unit.get('profiles') or [])[self.profile_index]
        st, inv, extras = {k: p.get(k) for k in ('T', 'W', 'Sv')}, p.get('invuln_sv'), []
        for e in self.effects():
            t, m = e.get('type'), e.get('modifier') or {}
            if t == 'feel-no-pain' and m.get('threshold'):
                extras.append(f"feel no pain {m['threshold']}+")
            elif t == 'invulnerable-save' and m.get('invuln_sv'):
                inv = min(inv or 7, m['invuln_sv'])
            elif t == 'damage-reduction':
                extras.append('halve damage' if m.get('reduction') == 'half' else 'damage reduction 1')
            elif t == 'ability-grant' and m.get('ability_id') == 'benefit-of-cover' and e.get('target') in _OWN:
                extras.append('stealth')
            elif t == 'stat-modifier' and m.get('stat') in st and e.get('target') in _OWN and isinstance(m.get('value'), int):
                val = m['value'] * (-1 if m.get('operation') == 'subtract' else 1)
                if m.get('operation') == 'set':
                    st['Sv'] = min(st['Sv'], val) if m['stat'] == 'Sv' else st['Sv']
                else:
                    st[m['stat']] += -val if m['stat'] == 'Sv' else val   # +1 to a save lowers Sv
        if any(a.get('ability_id') == 'stealth' for a in self.abilities):
            extras.append('stealth')
        W = st['W']
        return {
            'name': self.unit.get('name'), 'unit_id': self.unit.get('id'),
            'toughness': st['T'], 'save': st['Sv'], 'invuln': inv, 'wounds': W,
            'models': self.models - self.damage_taken // W, 'damage_taken': self.damage_taken % W,
            'kws': [k.lower().replace(' ', '') for k in self.unit.get('keywords', [])],  # Spaceless, as in anti-X
            'abilities': sorted(set(extras)),
        }

    def attack(self, other, **kw):
        return attack(self, other, **kw)

    def __repr__(self):
        return f"<Datasheet {self.unit.get('id')} x{self.models}>"


def attack(attackers, defender, situation=None, spillover=True):
    """Damage one or more attacking Datasheets deal to `defender` in one activation.

    situation -- passed to dam_dist; 'range' may be inches (melta/rapid-fire gate on half
                 range, ranged profiles that cannot reach are dropped) or a bool.
    -> {'profiles': [{name, weapon_id, type, count, each, mean}], 'ranged', 'melee', 'total',
        'dist'}: `each` is the mean for one copy of the profile; `dist` combines every counted
        profile with per-model wound tracking, from the defender's damage already taken.
    """
    attackers = [attackers] if isinstance(attackers, Datasheet) else attackers
    tgt, inc = defender.target(), defender.incoming()
    sit = {'cover': False, 'range': False, 'overwatch': False, 'indirect': False, **(situation or {})}
    rows, cum = [], None
    for p in (p for a in attackers for p in a.profiles()):
        s = dict(sit)
        if p['type'] == 'melee':
            s['range'] = True
        elif isinstance(s['range'], (int, float)) and not isinstance(s['range'], bool):
            if isinstance(p['range'], (int, float)) and p['range'] < s['range']:
                continue                      # weapon cannot reach the target
        p = p | {'kws': p['kws'] + [k for kws, t in inc if t in (None, p['type']) for k in kws]}
        each = dd_mean(dam_dist(p, dict(tgt), s, spillover=spillover))
        rows.append({'name': p['name'], 'weapon_id': p['weapon_id'], 'type': p['type'],
                     'count': p['count'], 'each': each, 'mean': each * p['count']})
        if p['count']:
            fd = dam_dist(p, dict(tgt), s, n=p['count'], spillover=spillover, fulldist=True)
            cum = fd if cum is None else fulldist_convolve(cum, fd, tgt['wounds'])
    dist = cum[tgt['damage_taken']] if cum else {0: 1.0}
    if not spillover:
        dist = dd_cap(dist, tgt['models'] * tgt['wounds'] - tgt['damage_taken'])
    return {'profiles': rows, 'dist': dist,
            'ranged': sum(r['mean'] for r in rows if r['type'] == 'ranged'),
            'melee': sum(r['mean'] for r in rows if r['type'] == 'melee'),
            'total': sum(r['mean'] for r in rows)}
