# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/01_dists.ipynb.

# %% auto 0
__all__ = ['convolve', 'mult_ddist_vals', 'mult_ddist_probs', 'threshold_ddist', 'add_ddist', 'flatdist', 'fnp_transform',
           'dd_rep', 'dd_prune', 'dd_mean', 'dd_above', 'dd_max', 'dd_psum', 'find_kw', 'single_dam_dist',
           'atk_success_prob', 'atk_success_dist', 'successful_atk_dist', 'dam_dist']

# %% ../nbs/01_dists.ipynb 1
import numpy, re
from collections import defaultdict
from math import ceil, floor, comb, isnan
prange = range # as we use range as argument name so it helps to have alias

# %% ../nbs/01_dists.ipynb 3
# Helper functions for damage distributions

def convolve(d1,d2, n_wounds=None):
    res = defaultdict(lambda: 0)
    if n_wounds is None:
        for k1,v1 in d1.items():
            for k2,v2 in d2.items():
                res[k1+k2] += v1*v2
    else: # Limit damage to n_wounds units
        for k1,v1 in d1.items():
            for k2,v2 in d2.items():
                kv = k1+k2
                k1m, k2m = k1%n_wounds, k2%n_wounds
                if k1m + k2m > n_wounds: 
                    kv -= (k1m+k2m)%n_wounds
                res[kv] += v1*v2
    return res

def mult_ddist_vals(d, val):
    res = defaultdict(lambda: 0)
    for k1,v1 in d.items():
        res[int(ceil(k1*val))] += v1 
    return res

def mult_ddist_probs(d,p):
    return { k:v*p for k,v in d.items() }

def threshold_ddist(dd,val,lt=True):
    for k in list(dd.keys()): 
        if (lt and k<val) or (not lt and k>val): 
            dd[val]+=dd[k]
            del dd[k]

def add_ddist(d1,d2):
    res = defaultdict(lambda: 0)
    for k1,v1 in d1.items():
        res[k1] += v1  
    for k2,v2 in d2.items():
        res[k2] += v2 
    return res
    
def flatdist(n):
    return { (i+1):1/n for i in range(n) }

# q is the probability of saving the damage
def fnp_transform(d, q):
    p = 1.0-q
    res = defaultdict(lambda: 0)
    for k,v in d.items():
        for i in range(k+1): # Binomial distribution
            res[i] += v*comb(k,i)*(p**i)*(q**(k-i))
    return res

def dd_rep(d, n, **argv):
    if n == 0 : return { 0: 1 }
    res_d = d
    for _ in range(1,n):
        res_d = dd_prune(convolve(res_d,d,**argv),1e-3)
    return res_d

# Prune all values with prob below ratio * <max prob>
def dd_prune(d, ratio):
    t = ratio*max(d.values())
    return { k:v for k,v in d.items() if v>t }

def dd_mean(dd):
    val = 0.0
    for k, v in dd.items():
        val += k*v
    return val


def dd_above(d, thresh):
    p = 0.0
    for k,v in d.items():
        if k>=thresh: p+=v
    return p


def dd_max(dd):
    return max(dd.keys())

def dd_psum(dd):
    return sum(dd.values())


# %% ../nbs/01_dists.ipynb 4
def dd_from_str(dstr):
    dd = { 0: 1.0 }
    for t in dstr.lower().split('+'):
        if 'd' in t:
            d = t.split('d')
            if d[0]=='': d = [1,int(d[1])]
            else: d = list(map(int,d))
            for _ in range(d[0]):
                nd = flatdist(d[1])
                dd = convolve(dd,nd)
        else:
            d = int(t)
            dd = convolve(dd,{d:1.0})
    return dd

# %% ../nbs/01_dists.ipynb 5
# Return suffix of the kw if found, and None otherwise
def find_kw(kw,kws):
    sus = None
    for k in kws:
        if k.startswith(kw):
            sus = k[len(kw):].strip()
    return sus

# %% ../nbs/01_dists.ipynb 6
def single_dam_dist(wep, target, range=False):

    # Create dmgstr distribution
    dd = dd_from_str(wep['damage'])

    # Apply div/mult modifiers 
    div,mult,add = 1,1,0 #TODO: process advanced abilities
    if div!=1: dd = mult_ddist_vals(dd,1.0/div)
    if mult!=1: dd = mult_ddist_probs(dd,mult)

    # Melta - after div and mult
    melta = find_kw('melta',wep['kws'])
    if melta and range: 
        #print("MELTA",melta)
        dd = convolve(dd,dd_from_str(melta))

    if add!=0: dd = convolve(dd,{add:1.0})

    # Threshold to 1
    threshold_ddist(dd,1,True)

    # Apply FNP
    fnp = find_kw('feel no pain',target['abilities'])
    if fnp: 
        #print("FNP",fnp)
        fnp = int(fnp.strip('+'))
        dd = fnp_transform(dd,(7-fnp)/6)

    # Threshold to n_wounds
    threshold_ddist(dd,target['wounds'],False)

    #print(dd_mean(dd))

    return dd
    

# %% ../nbs/01_dists.ipynb 7
def get_hit_probs(wep,target):

    # Prob to hit
    if 'torrent' in wep['kws']:
        p_hcrit, p_hit = 0, 1
    else:
        hit_crit = 6 # Normally crit on 6+ but can be something else
        p_hcrit = (7-hit_crit)/6.0

        hit_t = wep['bsws']

        # Stealth
        if wep['type']=='ranged' and 'stealth' in target['abilities']: 
            #print("stealth")
            hit_t +=1

        p_hit = max((6*p_hcrit),min(5, # hit_crit always hits, 1 always misses
                    (7-hit_t)))/6.0
    return p_hit,p_hcrit

# %% ../nbs/01_dists.ipynb 8
def atk_success_prob(wep, target, crit_hit=None, cover=False, verbose=False):

    # TODO:
    # Rerolls (1 and all)
    # Fish-for-sixes if better.

    # Probs to hit
    
        
    # Check if fn parameter already tells us if it was a crit or not
    # This behavior is needed for Sustained hits as they also affect hit counts
    if crit_hit: p_hcrit,p_hit = 1,1
    elif crit_hit==False: p_hcrit,p_hit = 0, 1
    else: p_hit, p_hcrit = get_hit_probs(wep, target)

    if verbose: print("Hit",p_hit,p_hcrit)

    # Prob to wound

    # Get crit wound threshold (ANTI keywords)
    wound_crit = 6
    for k in wep['kws']:
        if k.startswith('anti-'):
            kw,val = k[5:].split(' ')
            if kw in target['kws']: 
                #print("Anti",kw,val)
                wound_crit = min(wound_crit,int(val.strip('+')))

    p_wcrit = (7-wound_crit)/6.0

    if wep['strength']>target['toughness']:
        if wep['strength']>=2*target['toughness']:
            p_wound = 5/6.0
        else: p_wound = 4/6.0
    elif wep['strength']<target['toughness']:
        if 2*wep['strength']<=target['toughness']:
            p_wound = 1/6.0
        else: p_wound = 2/6.0
    else: p_wound = 3/6.0

    p_wound = max(p_wcrit,p_wound)

    if 'twin-linked' in wep['kws']:
        #print("Twinlinked")
        p_wound += (1-p_wound)*p_wound
        p_wcrit += (1-p_wound)*p_wcrit
    
    if verbose: print("Wound",p_wound,p_wcrit)

    # Prob to not save

    # Cover effect
    c_eff = 0 if (not cover or wep['type']!='ranged' or 
                'ignores cover' in wep['kws'] or 
                (wep['AP']==0 and target['save']<=3)) else 1
    
    
    save = min(target['invuln'] or 10,target['save']-c_eff-wep['AP'])
    p_nsave = 1.0 - max(0,min(6,7-save))/6.0

    if 'devastating wounds' in wep['kws']: # Devastating wounds
        #print("devwounds")
        p_nsave = ((p_wound-p_wcrit)*p_nsave + p_wcrit)/p_wound

    if verbose: print("Save",p_nsave)

    # Total probability
    if 'lethal hits' in wep['kws']:
        #print("lethal hits")
        p_dam = p_hcrit*p_nsave + (p_hit-p_hcrit)*p_wound*p_nsave
    else:
        p_dam = p_hit*p_wound*p_nsave

    if verbose: print("Total prob", p_dam)

    return p_dam

# %% ../nbs/01_dists.ipynb 9
# Create res as weighted sum of repeated convolutions with weights given by b_dd and repeated self-convolutons of r_dd
def dd_over_dd(b_dd,r_dd,base=0,**argv):
    cur_d,res_d = {base: 1.0}, {0: b_dd.get(0,0.0)}
    for i in range(1,dd_max(b_dd)+1):
        cur_d = convolve(cur_d,r_dd,**argv)
        if i in b_dd:
            res_d = add_ddist(res_d,mult_ddist_probs(cur_d,b_dd[i]))
    return res_d

# %% ../nbs/01_dists.ipynb 10
# Wrapper around atk_success_prob that handles sustained hits
def atk_success_dist(wep,target,cover=False):
   
    # Find number of sustained hits
    sus = find_kw('sustained hits',wep['kws'])
   
    # Handle the easy case (no sustained hits)
    if not sus:
        p = atk_success_prob(wep,target,cover=cover)
        return { 1: p, 0: (1-p) }
    
    # Sustained hits:
    #print("Sustained",sus)
    sus_d = dd_from_str(sus)
    
    p_hit, p_hcrit = get_hit_probs(wep,target)
    pc = atk_success_prob(wep,target,True,cover=cover)
    pn = atk_success_prob(wep,target,False,cover=cover)

    #p = pn*(1-p_hcrit)
    normal = { 1: pn, 0: (1-pn) }
    crit = { 1: pc, 0: (1-pc) }
    crit = convolve(crit,dd_over_dd(sus_d,normal))
    
    normal = mult_ddist_probs(normal,p_hit-p_hcrit)
    crit = mult_ddist_probs(crit,p_hcrit)

    total =  add_ddist(normal, crit)
    total[0] += 1.0-p_hit

    return total


# %% ../nbs/01_dists.ipynb 11
def successful_atk_dist(wep,target, range=False, cover=False):
    if range not in [True,False]: range = (range<=wep['range']/2)

    # Base attack number dist
    an_d = dd_from_str(wep['attacks'])

    # Rapid fire
    rfire = find_kw('rapid fire',wep['kws'])
    if rfire and range: 
        #print("Rapidfire",rfire)
        an_d = convolve(an_d,dd_from_str(rfire))

    # Other added attacks, incl Blast
    added_attacks = 0
    if 'blast' in wep['kws'] and target.get('models',0)>=5:
        #print("Blast")
        added_attacks += target['models']//5
    if added_attacks!=0:
        an_d = convolve(an_d,{added_attacks:1})

    # Attack successes dist for an individual attack
    as_d = atk_success_dist(wep,target,cover)

    # Create res as weighted sum of repeated convolutions
    res_d = dd_over_dd(an_d,as_d)

    return res_d

# %% ../nbs/01_dists.ipynb 12
# Final end-to-end calculation for a weapon
# Range can be True (is in half distance), False (is not) or number of inches
def dam_dist(wep,target, n=1, range=False, cover=False):
    if range not in [True,False]: range = (range<=wep['range']/2)

    # Successful attack dist
    sa_d = successful_atk_dist(wep,target, range, cover)

    # Single damage dist
    sd_d = single_dam_dist(wep,target,range=range)

    # Create res as weighted sum of repeated convolutions
    unit_d = dd_over_dd(sa_d,sd_d,n_wounds=target['wounds'])

    res_d = dd_rep(unit_d,n)
    return res_d
