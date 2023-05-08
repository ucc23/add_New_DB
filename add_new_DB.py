
import datetime
import json
import csv
import numpy as np
import pandas as pd
from string import ascii_lowercase
from astropy.coordinates import SkyCoord
from astropy.coordinates import angular_separation
import astropy.units as u
from scipy.spatial.distance import cdist
from modules import fastMP_process


# Name of the DB to add
new_DB = "PERREN22"

# Date of the latest version of the UCC catalogue
UCC_cat_date_old = "20230508"


def main(
    dbs_folder='databases/', DBs_json='all_dbs.json', sep=',', N_dups=10
):
    """
    """

    # Load column data for the new catalogue
    with open(dbs_folder + DBs_json) as f:
        dbs_used = json.load(f)
    json_pars = dbs_used[new_DB]

    # Load the latest version of the combined catalogue: 'UCC_cat_20XXYYZZ.csv'
    df_comb = pd.read_csv("UCC_cat_" + UCC_cat_date_old + ".csv")
    print(f"N={len(df_comb)} clusters in combined DB")

    # Load the new DB
    df_new = pd.read_csv(dbs_folder + new_DB + '.csv')
    print(f"N={len(df_new)} clusters in new DB")

    DBs_fnames = get_fnames(df_new, json_pars, sep)

    db_matches = get_matches(df_comb, DBs_fnames)

    new_db_dict, idx_rm_comb_db = combine_new_old(
        new_DB, df_comb, df_new, json_pars, DBs_fnames, db_matches, sep)
    print(f"N={len(df_new) - len(idx_rm_comb_db)} new clusters in new DB")

    ucc_ids_old = list(df_comb['UCC_ID'].values)
    for i, UCC_ID in enumerate(new_db_dict['UCC_ID']):
        if str(UCC_ID) != 'nan':
            # This cluster already has a UCC_ID assigned
            continue
        lon_i, lat_i = new_db_dict['GLON'][i], new_db_dict['GLAT'][i]
        new_db_dict['UCC_ID'][i] = assign_UCC_ids(
            lon_i, lat_i, ucc_ids_old)
        ucc_ids_old += [new_db_dict['UCC_ID'][i]]

    # Remove clusters in the new DB that were already in the old combined DB
    df_comb_no_new = df_comb.drop(df_comb.index[idx_rm_comb_db])
    df_comb_no_new.reset_index(drop=True, inplace=True)
    df_all = pd.concat([df_comb_no_new, pd.DataFrame(new_db_dict)],
                       ignore_index=True)

    print(f"Finding possible duplicates (max={N_dups})...")
    df_all['dups_fnames'] = dups_identify(df_all, N_dups)

    # Save new version of the UCC catalogue to file
    d = datetime.datetime.now()
    date = d.strftime('%Y%m%d')
    UCC_cat = 'UCC_cat_' + date + '.csv'
    df_all.to_csv(
        UCC_cat, na_rep='nan', index=False, quoting=csv.QUOTE_NONNUMERIC)
    print(f"File {UCC_cat} updated")

    # Update cluster's JSON file (used by 'ucc.ar' seach)
    df = pd.DataFrame(df_all[[
        'ID', 'fnames', 'UCC_ID', 'RA_ICRS', 'DE_ICRS', 'GLON', 'GLAT']])
    df['ID'] = [_.split(';')[0] for _ in df['ID']]
    df.to_json('../ucc/_clusters/clusters.json', orient="records", indent=1)
    print("File 'clusters.json' updated")

    # Process each cluster in the new DB with fastMP and store the result in
    # the output folder
    fastMP_process.run(new_DB, df_all)


def get_fnames(df_new, json_pars, sep) -> list:
    """
    Extract and standardize all names in new catalogue
    """
    names_all = df_new[json_pars['names']]
    DBs_fnames = []
    for i, names in enumerate(names_all):
        names_l = []
        names_s = names.split(sep)
        for name in names_s:
            name = name.strip()
            name = FSR_ESO_rename(name)
            names_l.append(rm_chars_from_name(name))
        DBs_fnames.append(names_l)

    return DBs_fnames


def FSR_ESO_rename(name):
    """
    Standardize the naming of these clusters watching for 

    FSR XXX w leading zeros
    FSR XXX w/o leading zeros
    FSR_XXX w leading zeros
    FSR_XXX w/o leading zeros

    --> FSR_XXXX (w leading zeroes)

    ESO XXX-YY w leading zeros
    ESO XXX-YY w/o leading zeros
    ESO_XXX_YY w leading zeros
    ESO_XXX_YY w/o leading zeros
    ESO_XXX-YY w leading zeros
    ESO_XXX-YY w/o leading zeros
    ESOXXX_YY w leading zeros (LOKTIN17)

    --> ESO_XXX_YY (w leading zeroes)
    """
    if name.startswith("FSR"):
        if ' ' in name or '_' in name:
            if '_' in name:
                n2 = name.split('_')[1]
            else:
                n2 = name.split(' ')[1]
            n2 = int(n2)
            if n2 < 10:
                n2 = '000' + str(n2)
            elif n2 < 100:
                n2 = '00' + str(n2)
            elif n2 < 1000:
                n2 = '0' + str(n2)
            else:
                n2 = str(n2)
            name = "FSR_" + n2

    if name.startswith("ESO"):
        if name[:4] not in ('ESO_', 'ESO '):
            # This is a LOKTIN17 ESO cluster
            name = 'ESO_' + name[3:]

        if ' ' in name[4:]:
            n1, n2 = name[4:].split(' ')
        elif '_' in name[4:]:
            n1, n2 = name[4:].split('_')
        elif '' in name[4:]:
            n1, n2 = name[4:].split('-')

        n1 = int(n1)
        if n1 < 10:
            n1 = '00' + str(n1)
        elif n1 < 100:
            n1 = '0' + str(n1)
        else:
            n1 = str(n1)
        n2 = int(n2)
        if n2 < 10:
            n2 = '0' + str(n2)
        else:
            n2 = str(n2)
        name = "ESO_" + n1 + '_' + n2

    return name


def rm_chars_from_name(name):
    """
    """
    # We replace '+' with 'p' to avoid duplicating names for clusters
    # like 'Juchert J0644.8-0925' and 'Juchert_J0644.8+0925'
    name = name.lower().replace('_', '').replace(' ', '').replace(
        '-', '').replace('.', '').replace("'", '').replace('+', 'p')
    return name


def get_matches(df_comb, DBs_fnames):
    """
    """
    def match_fname(new_cl):
        for name_new in new_cl:
            for j, old_cl in enumerate(df_comb['fnames']):
                for name_old in old_cl.split(';'):
                    if name_new == name_old:
                        return j
        return None

    db_matches = []
    for i, new_cl in enumerate(DBs_fnames):
        # Check if this new fname is already in the old DBs list of fnames
        db_matches.append(match_fname(new_cl))

    return db_matches


def combine_new_old(
    DB_new_ID, df_comb, df_new, json_pars, DBs_fnames, db_matches, sep
):
    """
    """
    cols = []
    for v in json_pars['pos'].split(','):
        if str(v) == 'None':
            v = None
        cols.append(v)
    # Remove Rv column
    ra_c, dec_c, plx_c, pmra_c, pmde_c = cols[:-1]

    new_db_dict = {
        'DB': [], 'DB_i': [], 'ID': [], 'RA_ICRS': [], 'DE_ICRS': [],
        'GLON': [], 'GLAT': [], 'plx': [], 'pmRA': [], 'pmDE': [],
        'UCC_ID': [], 'fnames': [], 'dups_fnames': []}
    idx_rm_comb_db = []
    for i, new_cl in enumerate(DBs_fnames):

        row_n = df_new.iloc[i]

        new_names = row_n[json_pars['names']].split(sep)
        new_names = [_.strip() for _ in new_names]
        new_names = ';'.join(new_names)

        plx_m, pmra_m, pmde_m = np.nan, np.nan, np.nan
        ra_m, dec_m = row_n[ra_c], row_n[dec_c]
        if plx_c is not None:
            plx_m = row_n[plx_c]
        if pmra_c is not None:
            pmra_m = row_n[pmra_c]
        if pmde_c is not None:
            pmde_m = row_n[pmde_c]

        # Index of the match for this new cluster in the old DB (if any)
        db_match_j = db_matches[i]

        # If the cluster is already present in the combined DB
        if db_match_j is not None:
            # Store indexes in old DB of clusters present in new DB
            idx_rm_comb_db.append(db_match_j)

            # Identify row in old DB where this match is
            row = df_comb.iloc[db_match_j]

            # Combine old data with that of the new matched cluster
            ra_m = np.nanmedian([row['RA_ICRS'], ra_m])
            dec_m = np.nanmedian([row['DE_ICRS'], dec_m])
            if not np.isnan([row['plx'], plx_m]).all():
                plx_m = np.nanmedian([row['plx'], plx_m])
            if not np.isnan([row['pmRA'], pmra_m]).all():
                pmra_m = np.nanmedian([row['pmRA'], pmra_m])
            if not np.isnan([row['pmDE'], pmde_m]).all():
                pmde_m = np.nanmedian([row['pmDE'], pmde_m])

            DB_ID = row['DB'] + ';' + DB_new_ID
            DB_i = row['DB_i'] + ';' + str(i)

            ID = row['ID'] + ';' + new_names
            UCC_ID = row['UCC_ID']
            fnames = row['fnames'] + ';' + ';'.join(new_cl)
            dups_fnames = row['dups_fnames']
        else:
            DB_ID = DB_new_ID
            DB_i = str(i)
            ID = new_names
            fnames = ';'.join(new_cl)
            # These values will be assigned later on for these new clusters
            UCC_ID = np.nan
            dups_fnames = np.nan

        new_db_dict['DB'].append(DB_ID)
        new_db_dict['DB_i'].append(DB_i)
        # Remove duplicates
        if ';' in ID:
            ID = ';'.join(list(dict.fromkeys(ID.split(';'))))
        new_db_dict['ID'].append(ID)
        lon, lat = radec2lonlat(ra_m, dec_m)
        new_db_dict['RA_ICRS'].append(round(ra_m, 4))
        new_db_dict['DE_ICRS'].append(round(dec_m, 4))
        new_db_dict['GLON'].append(lon)
        new_db_dict['GLAT'].append(lat)
        new_db_dict['plx'].append(plx_m)
        new_db_dict['pmRA'].append(pmra_m)
        new_db_dict['pmDE'].append(pmde_m)
        new_db_dict['UCC_ID'].append(UCC_ID)
        # Remove duplicates
        if ';' in fnames:
            fnames = ';'.join(list(dict.fromkeys(fnames.split(';'))))
        new_db_dict['fnames'].append(fnames)
        new_db_dict['dups_fnames'].append(dups_fnames)

    # Remove duplicates of the kind: Berkeley 102, Berkeley102,
    # Berkeley_102; keeping only the name with the space
    for q, names in enumerate(new_db_dict['ID']):
        names_l = names.split(';')
        for i, n in enumerate(names_l):
            n2 = n.replace(' ', '')
            if n2 in names_l:
                j = names_l.index(n2)
                names_l[j] = n
            n2 = n.replace(' ', '_')
            if n2 in names_l:
                j = names_l.index(n2)
                names_l[j] = n
        names = ';'.join(list(dict.fromkeys(names_l)))

    return new_db_dict, idx_rm_comb_db


def radec2lonlat(ra, dec):
    gc = SkyCoord(ra=ra * u.degree, dec=dec * u.degree)
    lb = gc.transform_to('galactic')
    lon, lat = lb.l.value, lb.b.value
    return np.round(lon, 4), np.round(lat, 4)


def assign_UCC_ids(glon, glat, ucc_ids_old):
    """
    Format: UCC GXXX.X+YY.Y
    """
    lonlat = np.array([glon, glat]).T
    lonlat = [trunc(lonlat)]

    for idx, ll in enumerate(lonlat):
        lon, lat = str(ll[0]), str(ll[1])

        if ll[0] < 10:
            lon = '00' + lon
        elif ll[0] < 100:
            lon = '0' + lon

        if ll[1] >= 10:
            lat = '+' + lat
        elif ll[1] < 10 and ll[1] > 0:
            lat = '+0' + lat
        elif ll[1] == 0:
            lat = '+0' + lat.replace('-', '')
        elif ll[1] < 0 and ll[1] >= -10:
            lat = '-0' + lat[1:]
        elif ll[1] < -10:
            pass

        ucc_id = 'UCC G' + lon + lat

        i = 0
        while True:
            if i > 25:
                ucc_id += "ERROR"
                print("ERROR NAMING")
                break
            if ucc_id in ucc_ids_old:
                if i == 0:
                    # Add a letter to the end
                    ucc_id += ascii_lowercase[i]
                else:
                    # Replace last letter
                    ucc_id = ucc_id[:-1] + ascii_lowercase[i]
                i += 1
            else:
                break

    return ucc_id


def trunc(values, decs=1):
    return np.trunc(values*10**decs)/(10**decs)


def dups_identify(df, N_dups):
    """
    Find the closest clusters to all clusters
    """
    x, y = df['GLON'], df['GLAT']
    pmRA, pmDE, plx = df['pmRA'], df['pmDE'], df['plx']
    coords = np.array([x, y]).T
    # Find the distances to all clusters, for all clusters
    dist = cdist(coords, coords)
    # Change distance to itself from 0 to inf
    msk = dist == 0.
    dist[msk] = np.inf

    dups_fnames = []
    for i, cl in enumerate(dist):
        idx = np.argsort(cl)[:N_dups]

        dups_fname = []
        for j in idx:
            # Angular distance in arcmin (rounded)
            d = round(angular_separation(x[i], y[i], x[j], y[j]) * 60, 2)
            # PMs distance
            pm_d = np.sqrt((pmRA[i]-pmRA[j])**2 + (pmDE[i]-pmDE[j])**2)
            # Parallax distance
            plx_d = abs(plx[i] - plx[j])

            dup_flag = duplicate_find(d, pm_d, plx_d, plx[i])

            if dup_flag:
                fname = df['fnames'][j].split(';')[0]
                dups_fname.append(fname)

        if dups_fname:
            # print(i, df['fnames'][i], len(dups_fname), dups_fname)
            dups_fname = ";".join(dups_fname)
        else:
            dups_fname = 'nan'

        dups_fnames.append(dups_fname)

    return dups_fnames


def duplicate_find(d, pm_d, plx_d, plx):
    """
    Identify a cluster as a duplicate following an arbitrary definition
    that depends on the parallax
    """
    if plx >= 4:
        rad, plx_r, pm_r = 15, 0.5, 1
    elif 3 <= plx and plx < 4:
        rad, plx_r, pm_r = 10, 0.25, 0.5
    elif 2 <= plx and plx < 3:
        rad, plx_r, pm_r = 5, 0.15, 0.25
    elif 1 <= plx and plx < 2:
        rad, plx_r, pm_r = 2.5, 0.1, 0.15
    else:
        rad, plx_r, pm_r = 1, 0.05, 0.1

    if not np.isnan(plx_d) and not np.isnan(pm_d):
        if pm_d < pm_r and plx_d < plx_r and d < rad:
            return True
    elif not np.isnan(plx_d) and np.isnan(pm_d):
        if plx_d < plx_r and d < rad:
            return True
    elif np.isnan(plx_d):
        rad, pm_r = 5, 0.5
        if not np.isnan(pm_d):
            if pm_d < pm_r and d < rad:
                return True
        else:
            if d < rad:
                return True

    return False


if __name__ == '__main__':
    main()
