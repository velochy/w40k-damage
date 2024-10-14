# AUTOGENERATED! DO NOT EDIT! File to edit: ../nbs/02_parsing.ipynb.

# %% auto 0
__all__ = ['csv_files_to_dict']

# %% ../nbs/02_parsing.ipynb 2
import pandas as pd
import re

# %% ../nbs/02_parsing.ipynb 3
def wargear_to_weapon(wg):
    return {
        'name': wg['name'],
        'type': wg['type'].lower(),
        'range': wg['range'],
        'attacks': wg['A'], 
        'bsws': int(str(wg['BS_WS']).strip('+')) if str(wg['BS_WS'])!='nan' else 0,
        'strength': int(wg['S']) if 'D' not in wg['S'] else 7, # TODO: Hack for now as it is 2D6 twice and 6+D6 once
        'AP': int(wg['AP']), 
        'damage': wg['D'],
        'kws': [ kw.strip() for kw in re.split(r',|\.',str(wg['description']))],
        'simplified': 'D' in str(wg['S']) # Warn if something here was simplified 
    }

def model_to_target(m):
    return { 'name': m['name'], 'toughness': int(m['T'].strip('*')), 
            'save': int(m['Sv'].strip('+')), 
            'invuln': int(m['inv_sv'].strip('*')) if str(m['inv_sv'])!='-' else None, 
            'wounds': int(m['W']),
            'simplified': '*' in m['inv_sv'] or '*' in m['T'] # Warn if something here was simplified 
    }

# %% ../nbs/02_parsing.ipynb 4
def csv_files_to_dict(csv_dir):
    files = ['Factions','Datasheets','Datasheets_abilities','Datasheets_keywords','Datasheets_models','Datasheets_wargear','Datasheets_unit_composition','Datasheets_models_cost','Abilities','Last_update']
    dfs = {}
    for f in files:
        dfs[f] = pd.read_csv(csv_dir+'/'+f+'.csv',sep='|')

    # Remove link tags from wargear and ability descriptions
    dfs['Datasheets_wargear']['description'] = dfs['Datasheets_wargear']['description'].str.replace('<[^>]*>','',regex=True).str.lower()
    dfs['Datasheets_abilities']['description'] = dfs['Datasheets_abilities']['description'].str.replace('<[^>]*>','',regex=True)

    # Take some more popular abilities and map them to names
    dmap = {
        'Each time an attack is allocated to this model, subtract 1 from the Damage characteristic of that attack.': 'damage reduction 1',
        'The bearer’s unit has the Feel No Pain 6+ ability.': 'feel no pain 6+',
        'While this model is leading a unit, models in that unit have the Feel No Pain 5+ ability.': 'feel no pain 5+',
        'Each time an attack is allocated to this model, halve the Damage characteristic of that attack.': 'halve damage',
            
        'Each time this model makes an attack that targets an enemy unit, re-roll a Hit roll of 1 and, if that unit is within range of an objective marker you do not control, you can re-roll the Hit roll instead.': 'reroll 1s to hit',
        'While this model is leading a unit, each time a model in that unit makes an attack, add 1 to the Hit roll.': 'improved hits 1',
        'While this model is leading a unit, weapons equipped by models in that unit have the [LETHAL HITS] ability.': 'lethal hits',
        'Ranged weapons equipped by models in the bearer’s unit have the [IGNORES COVER] ability.': 'ignores cover',
        'While this model is leading a unit, weapons equipped by models in that unit have the [SUSTAINED HITS 1] ability.': 'sustained hits 1'
    }
    df = dfs['Datasheets_abilities']
    df.loc[df['description'].isin(dmap),'name'] = df.loc[df['description'].isin(dmap),'description'].replace(dmap)

    # Add model counts to datasheets 
    # This is very rough but is a lot better than nothing
    df = dfs['Datasheets_models_cost']
    splitcol = df['description'].str.split(' |-',expand=True,regex=True)
    df.loc[~splitcol[2].isna() | ~splitcol[1].isin(['model','models','-']),'description'] = '1 model'
    df['count']=df['description'].str.split(' ',expand=True)[0].astype('int')
    dfs['Datasheets'] = dfs['Datasheets'].merge(df.groupby('datasheet_id')['count'].min(),left_on='id',right_on='datasheet_id')

    # Simplify abilities down to a dict of lists
    ability_dict = pd.Series(dfs['Abilities']['name'].values,index=dfs['Abilities']['id']).to_dict()
    df = dfs['Datasheets_abilities']
    df.loc[~df['ability_id'].isna(),'name'] = df.loc[~df['ability_id'].isna(),'ability_id'].replace(ability_dict)
    df.loc[~df['parameter'].isna(),'name'] += ' ' + df.loc[~df['parameter'].isna(),'parameter']
    df['name'] = df['name'].str.lower()
    abilities = df.groupby('datasheet_id')['name'].apply(list)

    df = dfs['Datasheets_keywords']
    df['keyword'] = df['keyword'].str.lower()
    keywords = df.groupby('datasheet_id')['keyword'].apply(list)

    rd = {}

    dsgb = dfs['Datasheets'].groupby('faction_id')
    dsmgb = dfs['Datasheets_models'].groupby('datasheet_id')
    dswggb = dfs['Datasheets_wargear'].groupby('datasheet_id')
    for i, f in dfs['Factions'].iterrows():

        dsl = { ds['name']:{ 'name': ds['name'], 'id': ds['id'], 'model_count':ds['count'] } for _,ds in dsgb.get_group(f['id']).iterrows() }
        rd[f['name']] = dsl

        for ds in dsl.values():
            if ds['id'] not in dswggb.groups: continue
            ds['weapons'] = list(dswggb.get_group(ds['id']).apply(wargear_to_weapon,axis=1))

            if ds['id'] not in dsmgb.groups: continue
            ds['models'] = list(dsmgb.get_group(ds['id']).apply(model_to_target,axis=1))

            ds['abilities'] = abilities[ds['id']]
            ds['kws'] = keywords[ds['id']]

    return rd
            
