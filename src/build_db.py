from __future__ import print_function

import os
import re
import sys
from subprocess import check_call

import pandas as pd

path = '../chunks/'

chunk_files = os.listdir(path)

required_columns = ['complex.id',
                    'cdr3', 'v.segm', 'j.segm', 'gene', 'species',
                    'mhc.a', 'mhc.b', 'mhc.type',
                    'antigen', 'antigen.gene', 'antigen.species',
                    'method', 'reference', 'reference.id']

index_column = 'record.id'


def error(*objs):
    print("[ERROR]", *objs, file=sys.stderr)
    exit(1)


# Make one big table of data

df = pd.DataFrame(columns=[index_column] + required_columns)
df.set_index(index_column, inplace=True)

for file in chunk_files:
    chunk = pd.read_table(path + file, sep='\t', index_col=[0],
                          na_values=[], keep_default_na=False)  # default NA's will break regex checking

    missing_cols = [x for x in required_columns if x not in chunk.columns.values]

    if missing_cols:
        error("The following required columns are missing in", file, ":", missing_cols)

    if chunk.index.name != index_column:
        error("Index column named", index_column, "should go first in", file)

    df = df.append(chunk, verify_integrity=True)  # verify record id integrity

# Check for duplicates

duplicates = df.set_index(required_columns).index.get_duplicates()

if duplicates:
    error("The following duplicates are present in database:\n", duplicates)

# Check correctness of certain columns

record_id_pattern = r'^VDJDBR\d{8}$'
complex_id_pattern = r'^VDJDBC\d{8}$'
aa_pattern = r'^[ARNDCEQGHILKMFPSTWYV]+$'
allowed_mhcs = ['MHCI', 'MHCII']
allowed_genes = ['TRA', 'TRB']
allowed_species = ['HomoSapiens', 'MusMusculus', 'RattusNorvegicus', 'MacacaMulatta']

bad_records = dict()

for index, row in df.iterrows():
    messages = []

    if not re.match(record_id_pattern, index):
        messages.append('Bad record identifier')

    if not re.match(complex_id_pattern, row['complex.id']):
        messages.append('Bad complex identifier')

    if not re.match(aa_pattern, row['cdr3']):
        messages.append('Bad CDR3 sequence')

    if row['antigen'] and not re.match(aa_pattern, row['antigen']):
        messages.append('Bad antigen sequence')

    if not row['mhc.type'] in allowed_mhcs:
        messages.append('MHC type should be in ' + str(allowed_mhcs))

    if not row['gene'] in allowed_genes:
        messages.append('TCR gene type should be in ' + str(allowed_genes))

    if not row['species'] in allowed_species:
        messages.append('Species should be in ' + str(allowed_species))

    if messages:
        bad_records[index] = messages

if bad_records:
    error("Database contains bad records:\n" + str(bad_records))

# Check that all records except CDR3 are same

bad_complexes = dict()

complex_match_cols = ['species',
                      'mhc.a', 'mhc.b', 'mhc.type',
                      'antigen', 'antigen.gene', 'antigen.species',
                      'method', 'reference', 'reference.id']

for index, group in df.groupby('complex.id'):
    if index != 'VDJDBC00000000':  # reserved for unpaired entries
        messages = []

        if len(group) != 2:
            messages.append('Number of entries in complex should be 2')

        rows = [r[1] for r in group.iterrows()]

        unmatched_cols = [col_name for col_name in complex_match_cols if rows[0][col_name] != rows[1][col_name]]

        if unmatched_cols:
            messages.append('The following columns are not matching within complex entries' + str(unmatched_cols))

        if messages:
            bad_complexes[index] = messages

if bad_complexes:
    error("Database contains bad complex records:\n" + str(bad_records))

# Fix

bin_path = '../bin/'
out_path = '../database/'

df[required_columns].to_csv(out_path + 'vdjdb_raw.txt', sep='\t', na_rep='NA')

check_call('java -jar {0}fixcdr3-1.0.0.jar {1}vdjdb_raw.txt {1}vdjdb_fixed.txt'.format(bin_path, out_path), shell=True)

df = pd.read_table(out_path + 'vdjdb_fixed.txt', sep='\t', index_col=[0])

unfixed_cdr3 = []

for index, row in df.iterrows():
    if not (row['good'] or (row['v.canonical'] and row['j.canonical'])):
        unfixed_cdr3.append(row[['fixed.cdr3', 'closest.v.id', 'closest.j.id', 'v.canonical', 'j.canonical',
                                 'v.fix.type', 'j.fix.type']])
    else:
        df.loc[index, 'cdr3'] = row['fixed.cdr3']
        df.loc[index, 'v.segm'] = row['closest.v.id']
        df.loc[index, 'j.segm'] = row['closest.j.id']

if unfixed_cdr3:
    error("There were ambiguous CDR3 sequences that weren't fixed\n" + str(unfixed_cdr3))

df[required_columns].to_csv(out_path + 'vdjdb.txt', sep='\t', na_rep='NA')