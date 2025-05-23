# w40k-damage

This is a simple python package for deterministically computing damage for W40k 10th ed

## Installation

Install latest from the GitHub
[repository](https://github.com/velochy/w40k-damage):

``` sh
$ pip install git+https://github.com/velochy/w40k-damage.git
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

Handles all 10th ed weapon keywords as well as unit keywords: 'stealth', 'feel no pain x+', 'damage reduction x', 'halve damage'
Also introduces extra weapon keywords: 'reroll hits', 'reroll 1s to hit, 'hit crit x+', 'reroll wounds', 'reroll 1s to wound', 'wound crit x+'
