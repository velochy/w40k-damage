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

Uses 11th ed cover (-1 to hit for ranged attacks, not +1 save). Handles all 10th ed weapon keywords, plus 11th ed 'cleave X' (blast for melee: +X attacks per 5 target models), as well as unit keywords: 'stealth', 'feel no pain x+', 'damage reduction x', 'halve damage'
Also introduces extra weapon keywords: 'reroll hits', 'reroll 1s to hit, 'hit crit x+', 'reroll wounds', 'reroll 1s to wound', 'wound crit x+'

## Datasheets

With the optional `wh40kdc` (40kdc-data) dependency you can run one datasheet
against another instead of hand-writing stat dicts:

``` python
from w40k_damage import Datasheet, attack

atk, dfn = Datasheet('intercessor-squad', models=10), Datasheet('terminator-squad', models=5)
atk.attack(dfn, situation={'range': 6})          # every weapon on the sheet
atk.attack(dfn, weapon='Bolt rifle')             # one weapon or profile by name
attack(attacker_json, defender_json)             # or pass raw 40kdc json
```

Returns per-profile means plus `ranged` / `melee` / `total`. Weapon stats, keywords
(including values such as `melta 2` / `rapid fire 1` / `anti-monster 4+`) and the
defender's defensive abilities (Feel No Pain, invulnerable saves, damage reduction,
T/W/Sv modifiers) are read from the bundle. Given a numeric `range`, weapons that
cannot reach are dropped and melta/rapid-fire gate on half range.

Two conventions worth knowing:

* `spillover=True` (the adapter's default) reports damage per activation without
  capping at the defender's total wounds. Do **not** emulate this by inflating
  `models` -- Blast and Cleave scale off `models`.
* Only `permanent`-scope defensive abilities count by default, and ones gated on an
  attack type (e.g. Feel No Pain vs Psychic only) are skipped. Pass `durations=None`
  to include situational ones, or an `ability_filter` to inject your own corrections.

## Development

Plain Python -- no notebooks. `pip install -e ".[dev]"` then `pytest`.
