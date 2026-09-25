# w40k-damage

This is a simple python package for deterministically computing damage for W40k 10th ed

## Installation

``` sh
$ pip install git+https://github.com/velochy/w40k-damage.git
$ pip install "w40k-damage[datasheet] @ git+https://github.com/velochy/w40k-damage.git"  # + 40kdc data
```
## Usage

The main function is dam_dist, which takes three parameters: weapon profile, defender profile, and situation description, and returns a damage distribution

``` python
from w40k_damage import dam_dist
wep = { 'type':'ranged', 'range': 24, 'attacks': '3', 'bsws': 3, 'strength': 5, 'AP': -2, 'damage': '2', 'kws': ['lethal hits', 'devastating wounds', 'melta d3+2', 'anti-infantry 3+', 'indirect fire'] }
target = { 'toughness': 7, 'save': 2, 'invuln': None, 'wounds': 10, 'kws':['infantry'], 'abilities': ['feel no pain 5+'] }
situation = { 'cover':True, 'range': 10, 'overwatch': False, 'indirect': False }
dam_dist(wep,target,situation)
```

Uses 11th ed cover (-1 to hit for ranged attacks, not +1 save; 'stealth' = always in cover). Handles all 10th ed weapon keywords, plus 11th ed 'cleave X' (blast for melee: +X attacks per 5 target models), as well as unit keywords: 'stealth', 'feel no pain x+', 'damage reduction x', 'halve damage'
Also introduces extra weapon keywords: 'reroll hits', 'reroll 1s to hit, 'hit crit x+', 'reroll wounds', 'reroll 1s to wound', 'wound crit x+'

## Datasheets

With the optional `wh40kdc` (40kdc-data) dependency you can run 40kdc datasheets
against each other. `Datasheet` takes the 40kdc dicts themselves -- the unit, and
lists of its weapon and ability dicts (resolved from the bundle by id if omitted):

``` python
from wh40kdc import Dataset
from w40k_damage import Datasheet, attack

ds = Dataset.embedded()
unit = lambda name: ds.units.find(name)
atk = Datasheet(unit('Intercessor Squad').raw, models=10)
dfn = Datasheet(unit('Terminator Squad').raw, models=5, damage_taken=2)
atk.attack(dfn, situation={'range': 6, 'cover': True})
attack([atk, other_atk], dfn, spillover=False)   # several attackers, capped at wounds left
```

Model loadouts and buffs by editing the dicts: set `count` on a weapon profile
(default: one per model), or append ability dicts whose effect tree says what they
do, e.g. `{'scope': {'duration': 'permanent'}, 'effect': {'type': 'roll-modifier',
'target': 'unit', 'modifier': {'roll': 'hit', 'operation': 'add', 'value': 1}}}`.
Defensive effects (Feel No Pain, invulnerable saves, damage reduction, T/W/Sv),
offensive ones (hit/wound modifiers, re-rolls, crit thresholds, A/S/AP, keyword
grants) and `target: attacker` debuffs are all read from the effect tree.

Returns per-profile means (`each` for one copy, `mean` for `count` copies), `ranged` /
`melee` / `total`, and `dist`: every counted profile combined with per-model wound
tracking. Given a numeric `range`, weapons that cannot reach are dropped and
melta/rapid-fire gate on half range.

Two conventions worth knowing:

* `spillover=True` (the default) reports damage per activation without capping at
  the defender's total wounds. Do **not** emulate this by inflating `models` --
  Blast and Cleave scale off `models`.
* Only unconditional `permanent`-scope effects count by default (`is-attached` /
  `model-is-leader` conditions count as met), and ones gated on an attack type (e.g.
  Feel No Pain vs Psychic only) are skipped. Pass `durations=None` to include
  situational ones, or edit the ability list to regate them.

## Development

Plain Python -- no notebooks. `pip install -e ".[dev]"` then `pytest`.
