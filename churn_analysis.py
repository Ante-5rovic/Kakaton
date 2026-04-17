# %% [markdown]
# # HPB Hackathon 2026 — AI Sustav za Predviđanje Odlaska Klijenata

# %%
try:
    get_ipython().run_line_magic('matplotlib', 'inline')
except:
    pass

"""
HPB Hackathon 2026 — Zadatak 1
AI Sustav za Predviđanje Odlaska Klijenata i Retencijske Mjere

Scoring Framework:
  1. CLV Score         — trenutna vrijednost klijenta
  2. Churn Risk Score  — rizik odlaska
  3. Future Potential  — budući potencijal
  4. Priority Score    — kombinacija za poslovnu odluku + akciju
"""

import matplotlib
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import seaborn as sns
import warnings
warnings.filterwarnings('ignore')

plt.rcParams['figure.figsize'] = (14, 7)
plt.rcParams['font.size'] = 11
sns.set_style("whitegrid")

import os
_win  = r"C:\Users\Lovre Marković\Documents\Kakaton\OneDrive_2026-04-16" + "\\"
_wsl  = "/mnt/c/Users/Lovre Marković/Documents/Kakaton/OneDrive_2026-04-16/"
DATA_PATH = _win if os.path.exists(_win) else _wsl

# Težine Priority Score
W_CHURN     = 0.40
W_CLV       = 0.35
W_POTENTIAL = 0.25

# Pragovi za segmentaciju
CHURN_THRESHOLD = 60   # iznad = visoki rizik


# ════════════════════════════════════════════════════════════
# POMOĆNE FUNKCIJE
# ════════════════════════════════════════════════════════════

def parse_hr_date(series):
    """Parsira hrvatski format datuma: D/M/YYYY/ ili D/M/YYYY/ H:MM:SS"""
    cleaned = (series.astype(str)
               .str.strip()
               .str.replace(r'/\s*$', '', regex=True)
               .str.strip())
    return pd.to_datetime(cleaned, dayfirst=True, errors='coerce')

def load_numeric(series):
    """Pretvara broj s decimalnom zarezom u float: '195,17' → 195.17"""
    return pd.to_numeric(
        series.astype(str).str.replace(',', '.', regex=False),
        errors='coerce'
    )

def normalize(series, cap_pct=95):
    """Normalizira seriju na [0, 1], cap na određeni percentil."""
    cap = series.quantile(cap_pct / 100)
    if cap == 0:
        return pd.Series(0, index=series.index)
    return (series.clip(0, cap) / cap).clip(0, 1)


# ════════════════════════════════════════════════════════════
# 1. UČITAVANJE PODATAKA
# ════════════════════════════════════════════════════════════

print("=" * 62)
print("  HPB HACKATHON — Churn Prevention System")
print("=" * 62)
print("\n[1/9] Učitavanje podataka...")

klijenti = pd.read_csv(
    DATA_PATH + "HACKATHON ZICER 202604 KLIJENTI.csv",
    sep=';', encoding='cp1250', on_bad_lines='skip', low_memory=False)

proizvodi = pd.read_csv(
    DATA_PATH + "HACKATHON ZICER 202604 PROIZVODI.csv",
    sep=';', encoding='cp1250', on_bad_lines='skip', low_memory=False)

stanja = pd.read_csv(
    DATA_PATH + "HACKATHON ZICER 202604 STANJA PROIZVODA.csv",
    sep=';', encoding='cp1250', on_bad_lines='skip', low_memory=False)

transakcije = pd.read_csv(
    DATA_PATH + "HACKATHON ZICER 202604 TRANSAKCIJE.csv",
    sep=';', encoding='cp1250', on_bad_lines='skip', low_memory=False,
    index_col=False)

cc = pd.read_csv(
    DATA_PATH + "HACKATHON ZICER 202604 KONTAKT CENTAR.csv",
    sep=';', encoding='cp1250', on_bad_lines='skip', low_memory=False)

print(f"  ✓ Klijenti:        {len(klijenti):>8,}")
print(f"  ✓ Proizvodi:       {len(proizvodi):>8,}")
print(f"  ✓ Stanja:          {len(stanja):>8,}")
print(f"  ✓ Transakcije:     {len(transakcije):>8,}")
print(f"  ✓ Kontakt centar:  {len(cc):>8,}")


# ════════════════════════════════════════════════════════════
# 2. PARSIRANJE TIPOVA I DATUMA
# ════════════════════════════════════════════════════════════

print("\n[2/9] Parsiranje tipova i datuma...")

# Datumi
proizvodi['DATUM_OTVARANJA']  = parse_hr_date(proizvodi['DATUM_OTVARANJA'])
proizvodi['DATUM_ZATVARANJA'] = parse_hr_date(proizvodi['DATUM_ZATVARANJA'])

transakcije['DATUM']  = parse_hr_date(transakcije['DATUM_I_VRIJEME_TRANSAKCIJE'])
transakcije['IZNOS']  = load_numeric(transakcije['IZNOS_TRANSAKCIJE_U_DOMICILNOJ_VALUTI'])

stanja['VRIJEDI_OD']  = parse_hr_date(stanja['VRIJEDI_OD'])
stanja['STANJE']      = load_numeric(stanja['STANJE_U_DOMICILNOJ_VALUTI'])

cc['DATUM_CC']        = parse_hr_date(cc['VRIJEME_KREIRANJA'])

klijenti['DATUM_ODNOSA'] = parse_hr_date(klijenti['DATUM_PRVOG_POCETKA_POSLOVNOG_ODNOSA'])

# Referentni datum = zadnja realna transakcija (filtriraj outliere)
valid_dates = transakcije['DATUM'][transakcije['DATUM'] < pd.Timestamp('2030-01-01')]
REF_DATE = valid_dates.max() if len(valid_dates) > 0 else pd.Timestamp('2025-09-30')
print(f"  ✓ Referentni datum: {REF_DATE.date()}")

# Mapiraj proizvod → klijent (za join s transakcijama i stanjima)
prod_to_client = (proizvodi[['IDENTIFIKATOR_PROIZVODA', 'IDENTIFIKATOR_KLIJENTA']]
                  .drop_duplicates('IDENTIFIKATOR_PROIZVODA'))

transakcije = transakcije.merge(prod_to_client, on='IDENTIFIKATOR_PROIZVODA', how='left')
stanja      = stanja.merge(prod_to_client, on='IDENTIFIKATOR_PROIZVODA', how='left')

print("  ✓ Joinovi postavljeni")


# ════════════════════════════════════════════════════════════
# 3. CLV SCORE  (max 100 bodova)
# ════════════════════════════════════════════════════════════
# Komponente:
#   Aktivnih proizvoda   → 25 bod  (više = veća vezanost)
#   Ima kredit           → 20 bod  (najvrjedniji proizvod)
#   Prima plaću u HPB    → 20 bod  (strateški ključno)
#   Avg monthly volume   → 15 bod  (transakcijska vrijednost)
#   Avg balance 90d      → 10 bod  (depozitna baza)
#   Tenure               → 10 bod  (lojalnost)
# ════════════════════════════════════════════════════════════

print("\n[3/9] Računanje CLV Score...")

# Aktivni proizvodi = nisu zatvoreni, ili su zatvoreni unutar zadnjih 6 mj.
aktivni = proizvodi[
    (proizvodi['DATUM_ZATVARANJA'].isna()) |
    (proizvodi['DATUM_ZATVARANJA'] >= REF_DATE - pd.Timedelta(days=180))
].copy()

clv = (aktivni.groupby('IDENTIFIKATOR_KLIJENTA')
       .agg(aktivnih_proizvoda=('IDENTIFIKATOR_PROIZVODA', 'nunique'))
       .reset_index())

# Boolean flagovi po domeni
for domain, col in [
    ('KREDITI',  'has_kredit'),
    ('DEPOZITI', 'has_depozit'),
    ('KARTICE',  'has_kartica'),
    ('KANALI',   'has_digitalni'),
]:
    ids_s_domenom = set(aktivni[aktivni['NAZIV_DOMENE_PROIZVODA'] == domain]['IDENTIFIKATOR_KLIJENTA'])
    clv[col] = clv['IDENTIFIKATOR_KLIJENTA'].isin(ids_s_domenom).astype(int)

# Prosječni mjesečni transakcijski volumen (zadnjih 12 mj.)
t12 = transakcije[transakcije['DATUM'] >= REF_DATE - pd.Timedelta(days=365)]
txn_vol = (t12.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS']
           .sum()
           .div(12)
           .rename('avg_monthly_vol')
           .reset_index())
clv = clv.merge(txn_vol, on='IDENTIFIKATOR_KLIJENTA', how='left')

# Prosječno stanje zadnjih 90 dana
s90 = stanja[stanja['VRIJEDI_OD'] >= REF_DATE - pd.Timedelta(days=90)]
avg_bal = (s90.groupby('IDENTIFIKATOR_KLIJENTA')['STANJE']
           .mean()
           .rename('avg_balance_90d')
           .reset_index())
clv = clv.merge(avg_bal, on='IDENTIFIKATOR_KLIJENTA', how='left')

# Tenure
klijenti['tenure_years'] = (REF_DATE - klijenti['DATUM_ODNOSA']).dt.days / 365
clv = clv.merge(
    klijenti[['IDENTIFIKATOR_KLIJENTA', 'tenure_years',
              'KLIJENT_PRIMA_OSNOVNO_PRIMANJE_U_BANCI']],
    on='IDENTIFIKATOR_KLIJENTA', how='left')
clv = clv.fillna(0)
clv['prima_placu'] = (clv['KLIJENT_PRIMA_OSNOVNO_PRIMANJE_U_BANCI'] == 'DA').astype(int)

# CLV Score
clv['CLV_SCORE'] = (
    normalize(clv['aktivnih_proizvoda']) * 25 +
    clv['has_kredit']    * 20 +
    clv['prima_placu']   * 20 +
    normalize(clv['avg_monthly_vol'])  * 15 +
    normalize(clv['avg_balance_90d'])  * 10 +
    normalize(clv['tenure_years'])     * 10
).clip(0, 100)

print(f"  ✓ CLV Score — prosjek: {clv['CLV_SCORE'].mean():.1f}  "
      f"medijan: {clv['CLV_SCORE'].median():.1f}")


# ════════════════════════════════════════════════════════════
# 4. CHURN RISK SCORE  (max 100 bodova)
# ════════════════════════════════════════════════════════════
# Komponente:
#   Pad frekvencije txn (30d vs prev 30d)  → 25 bod
#   Neaktivnost (dani od zadnje txn)       → 20 bod
#   Pad stanja računa (trend)              → 20 bod
#   Pad volumena txn                       → 15 bod
#   Prigovori u CC (zadnjih 6 mj.)         → 10 bod
#   Niska digitalna aktivnost              → 10 bod
#
# BINDING FAKTOR: klijenti s aktivnim kreditom  → cap 45
# (ne mogu otići, ali mogu funkcionalno churnat)
# ════════════════════════════════════════════════════════════

print("\n[4/9] Računanje Churn Risk Score...")

# Vremenski prozori transakcija
t30   = transakcije[transakcije['DATUM'] >= REF_DATE - pd.Timedelta(days=30)]
t_pre = transakcije[
    (transakcije['DATUM'] >= REF_DATE - pd.Timedelta(days=60)) &
    (transakcije['DATUM'] <  REF_DATE - pd.Timedelta(days=30))
]
t90   = transakcije[transakcije['DATUM'] >= REF_DATE - pd.Timedelta(days=90)]

txn_30   = t30.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].count().rename('cnt_30')
txn_pre  = t_pre.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].count().rename('cnt_pre')
vol_30   = t30.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].sum().rename('vol_30')
vol_pre  = t_pre.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].sum().rename('vol_pre')
last_txn = (transakcije.groupby('IDENTIFIKATOR_KLIJENTA')['DATUM']
            .max().rename('last_txn'))

# Digitalni omjer (KANAL: D = Digital, C = Counter/šalter)
cnt_total   = t90.groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].count().rename('cnt_total_90')
cnt_digital = (t90[t90['KANAL'] == 'D']
               .groupby('IDENTIFIKATOR_KLIJENTA')['IZNOS'].count()
               .rename('cnt_digital_90'))

# Stanje trend
s_rec = stanja[stanja['VRIJEDI_OD'] >= REF_DATE - pd.Timedelta(days=30)]
s_old = stanja[
    (stanja['VRIJEDI_OD'] >= REF_DATE - pd.Timedelta(days=90)) &
    (stanja['VRIJEDI_OD'] <  REF_DATE - pd.Timedelta(days=30))
]
bal_rec = s_rec.groupby('IDENTIFIKATOR_KLIJENTA')['STANJE'].mean().rename('bal_rec')
bal_old = s_old.groupby('IDENTIFIKATOR_KLIJENTA')['STANJE'].mean().rename('bal_old')

# Prigovori (zadnjih 6 mj.)
prigovori = (cc[
    (cc['DATUM_CC'] >= REF_DATE - pd.Timedelta(days=180)) &
    (cc['TIP_PREDMETA'] == 'Prigovor')
].groupby('IDENTIFIKATOR_KLIJENTA').size().rename('prigovori_6m'))

# Skupi sve u jedan DataFrame
churn = klijenti[['IDENTIFIKATOR_KLIJENTA']].copy()
for s in [txn_30, txn_pre, vol_30, vol_pre, last_txn,
          cnt_total, cnt_digital, bal_rec, bal_old, prigovori]:
    churn = churn.join(s, on='IDENTIFIKATOR_KLIJENTA')
# Izvedeni signali — izračunaj PRIJE fillna jer last_txn mora biti datetime
churn['days_since_txn'] = (REF_DATE - churn['last_txn']).dt.days.fillna(180)

churn = churn.fillna(0)
churn['freq_drop'] = np.where(
    churn['cnt_pre'] > 0,
    (1 - churn['cnt_30'] / churn['cnt_pre']).clip(0, 1), 0)
churn['vol_drop'] = np.where(
    churn['vol_pre'] > 0,
    (1 - churn['vol_30'] / churn['vol_pre']).clip(0, 1), 0)
churn['bal_drop'] = np.where(
    churn['bal_old'] > 0,
    (1 - churn['bal_rec'] / churn['bal_old']).clip(0, 1), 0)
churn['digital_ratio'] = np.where(
    churn['cnt_total_90'] > 0,
    churn['cnt_digital_90'] / churn['cnt_total_90'], 0.5)

# Churn Risk Score
churn['CHURN_RISK'] = (
    churn['freq_drop']                         * 25 +
    (churn['days_since_txn'].clip(0, 90) / 90) * 20 +
    churn['bal_drop']                          * 20 +
    churn['vol_drop']                          * 15 +
    (churn['prigovori_6m'].clip(0, 3) / 3)     * 10 +
    (1 - churn['digital_ratio'])               * 10
).clip(0, 100)

# Binding faktor — klijenti s kreditom ne mogu zaista otići (cap 45)
has_kredit_ids = set(clv[clv['has_kredit'] == 1]['IDENTIFIKATOR_KLIJENTA'])
churn['ima_kredit'] = churn['IDENTIFIKATOR_KLIJENTA'].isin(has_kredit_ids).astype(int)
churn['CHURN_RISK'] = np.where(
    churn['ima_kredit'] == 1,
    churn['CHURN_RISK'].clip(0, 45),
    churn['CHURN_RISK'])

print(f"  ✓ Churn Risk Score — prosjek: {churn['CHURN_RISK'].mean():.1f}  "
      f"medijan: {churn['CHURN_RISK'].median():.1f}")
print(f"  ✓ Klijenata s kreditom (binding cap): "
      f"{churn['ima_kredit'].sum():,} "
      f"({100*churn['ima_kredit'].mean():.1f}%)")


# ════════════════════════════════════════════════════════════
# 5. FUTURE POTENTIAL SCORE  (max 100 bodova)
# ════════════════════════════════════════════════════════════
# Komponente:
#   Dob (mlađi = veći potencijal)              → 25 bod
#   Vrsta posla / zanimanje                    → 25 bod  ← NOVO
#   Stručna sprema                             → 20 bod
#   Cross-sell gap (nema kredit, ima prihode)  → 20 bod
#   Obiteljski status                          → 10 bod
#
# Umirovljenici: sve × 0.5 (niži ali ne nulti potencijal)
# ════════════════════════════════════════════════════════════

print("\n[5/9] Računanje Future Potential Score...")

potential = klijenti[[
    'IDENTIFIKATOR_KLIJENTA', 'DOB', 'VRSTA_ZAPOSLENJA',
    'ZANIMANJE', 'KATEGORIJA_POSLODAVCA', 'TIP_POSLODAVCA',
    'STRUCNA_SPREMA', 'BRACNI_STATUS',
    'BROJ_UZDRZAVANIH_CLANOVA_KUCANSTVA'
]].copy()

# ── Dob score (max 25) ───────────────────────────────────────────────────────
potential['age_score'] = np.where(potential['DOB'] <= 30, 25,
                          np.where(potential['DOB'] <= 40, 20,
                          np.where(potential['DOB'] <= 50, 12,
                          np.where(potential['DOB'] <= 60, 6, 2))))

# ── Job score (max 25) — vrsta posla kao prediktor budućih prihoda ──────────
def job_score(row):
    vrsta      = str(row.get('VRSTA_ZAPOSLENJA',    '')).upper()
    zanimanje  = str(row.get('ZANIMANJE',           '')).upper()
    kategorija = str(row.get('KATEGORIJA_POSLODAVCA','')).upper()
    tip        = str(row.get('TIP_POSLODAVCA',      '')).upper()

    # Tier 1 — iznimno visoki prihodi (25 bod)
    if 'POMORAC' in vrsta:
        return 25   # pomorci: inozemna primanja, bez troška života na brodu
    if any(x in zanimanje for x in ['MENADŽER', 'DOKTOR', 'ZUBAR', 'ODVJETNIK']):
        return 25   # slobodne profesije i menadžment
    if 'SLOBODNO ZANIMANJE' in kategorija or 'LIJEČNIK' in kategorija or 'ODVJETNIK' in kategorija:
        return 25

    # Tier 2 — visoki prihodi s rastom (22 bod)
    if vrsta in ('PODUZETNIK', 'SAMOZAPOSLEN'):
        return 22   # prihodi rastu s biznisom
    if 'STRANI BROD' in kategorija:
        return 22   # offshore/inozemna primanja

    # Tier 3 — privatni sektor, rast plaće moguć (18 bod)
    if 'PRIVATNO PODUZEĆE - VELIKO' in tip:
        return 18   # velike firme → napredovanje, bonusi
    if any(x in kategorija for x in ['D.D. PRIVATNO', 'BANKA', 'OSIGURANJE']):
        return 18

    # Tier 4 — privatni sektor, srednji rast (14 bod)
    if any(x in tip for x in ['PRIVATNO PODUZEĆE - SREDNJE', 'PRIVATNO PODUZEĆE - MALO']):
        return 14
    if any(x in kategorija for x in ['D.O.O. PRIVATNO', 'J.D.O.O.', 'K.D. PRIVATNO']):
        return 14
    if 'OBRTNIK' in vrsta or 'OBRT' in tip or 'OBRT' in kategorija:
        return 12   # obrtnici: varijabilno, ali samostalno

    # Tier 5 — javni sektor / stabilno (10 bod)
    if 'JAVNO PODUZEĆE' in tip:
        return 10
    if any(x in zanimanje for x in ['JAVNO PODUZEĆ', 'NASTAVNIK', 'PROFESOR', 'ODGOJITELJ']):
        return 10

    # Tier 6 — državna uprava (7 bod)
    if any(x in zanimanje for x in ['DRŽAVNI SLUŽBENIK', 'JAVNA USTANOVA']):
        return 7
    if 'DRŽAVNO' in kategorija or 'DRŽAVNA UPRAVA' in kategorija or 'MINISTARSTVO' in kategorija:
        return 7

    # Tier 7 — honorarac / varijabilno (8 bod)
    if 'HONORARAC' in vrsta or 'HONORARAC' in tip:
        return 8

    # Tier 8 — nezaposlen / student / ostalo (4 bod)
    if vrsta in ('NEZAPOSLEN', 'STUDENT'):
        return 4

    return 10   # default — zaposlen ali bez detaljnijih podataka

potential['job_score'] = potential.apply(job_score, axis=1)

# ── Edukacija score (max 20) ─────────────────────────────────────────────────
def edu_score(sprema):
    sprema = str(sprema).upper()
    if any(x in sprema for x in ['VSS', 'VŠS', 'MAGISTAR', 'DOKTOR', 'SVEUČILIŠNI']):
        return 20
    if 'STRUČNI' in sprema:
        return 14
    if 'SSS' in sprema:
        return 9
    return 5

potential['edu_score'] = potential['STRUCNA_SPREMA'].apply(edu_score)

# ── Obiteljski status (max 10) ───────────────────────────────────────────────
potential['family_score'] = np.where(
    potential['BRACNI_STATUS'].astype(str).str.upper().str.contains('ŽENJEN|UDANA|BRAKU', na=False),
    10, 5)

# ── Cross-sell gap (max 20) ─────────────────────────────────────────────────
# Klijent s prihodima ali bez kredita = potencijalni kandidat za hipoteku/kredit
clv_mini = clv[['IDENTIFIKATOR_KLIJENTA', 'has_kredit', 'has_depozit', 'aktivnih_proizvoda']]
potential = potential.merge(clv_mini, on='IDENTIFIKATOR_KLIJENTA', how='left')
potential['crossell_score'] = np.where(
    (potential['has_kredit'] == 0) & (potential['job_score'] >= 14), 20,
    np.where((potential['has_depozit'] == 0) & (potential['age_score'] >= 12), 10, 5))

# ── Ukupni Future Potential ──────────────────────────────────────────────────
potential['FUTURE_POTENTIAL'] = (
    potential['age_score']    +   # max 25
    potential['job_score']    +   # max 25
    potential['edu_score']    +   # max 20
    potential['family_score'] +   # max 10
    potential['crossell_score']   # max 20
).clip(0, 100)

# Umirovljenici: skaliraj dolje (stabilni, ali ograničen budući potencijal)
umir_mask = potential['VRSTA_ZAPOSLENJA'].astype(str).str.upper().str.contains('UMIROVLJENIK', na=False)
potential.loc[umir_mask, 'FUTURE_POTENTIAL'] *= 0.5

print(f"  ✓ Future Potential Score — prosjek: {potential['FUTURE_POTENTIAL'].mean():.1f}  "
      f"medijan: {potential['FUTURE_POTENTIAL'].median():.1f}")

# Provjera: job_score distribucija
print(f"  ✓ Job score distribucija:")
job_dist = potential.groupby('job_score')['IDENTIFIKATOR_KLIJENTA'].count().sort_index(ascending=False)
for score, cnt in job_dist.items():
    print(f"     {score:>3} bod — {cnt:>5} klijenata")


# ════════════════════════════════════════════════════════════
# 6. SIMULACIJA APP ENGAGEMENT
# ════════════════════════════════════════════════════════════
# Pretpostavljamo da banka bilježi:
#   - broj app loginova u zadnjih 30 dana
#   - push open rate (% push obavijesti koje je klijent otvorio)
#   - dana od zadnjeg logina
#
# Simuliramo konzistentno s churn rizikom:
#   visoki churn risk → opadajući engagement
# ════════════════════════════════════════════════════════════

print("\n[6/9] Simulacija App Engagement (sintetički podatak)...")

np.random.seed(42)

has_digital_ids = set(clv[clv['has_digitalni'] == 1]['IDENTIFIKATOR_KLIJENTA'])
churn_map = churn.set_index('IDENTIFIKATOR_KLIJENTA')['CHURN_RISK']

app_rows = []
for _, row in klijenti.iterrows():
    kid = row['IDENTIFIKATOR_KLIJENTA']
    dob = row.get('DOB', 40)
    ima_digital = 1 if kid in has_digital_ids else 0
    risk = churn_map.get(kid, 50) / 100   # 0-1

    base_logins = 9 if ima_digital else 2
    if dob > 60:
        base_logins = max(1, base_logins - 3)

    decay = risk * 0.85
    logins = max(0, int(np.random.poisson(base_logins * (1 - decay))))
    push_open = float(np.clip(np.random.beta(max(0.1, 2*(1-decay)), max(0.1, 3+decay*6)), 0, 1))
    days_no_login = min(int(np.random.exponential(4 + decay * 45)), 180)

    app_rows.append({
        'IDENTIFIKATOR_KLIJENTA': kid,
        'app_logins_30d':         logins,
        'push_open_rate':         round(push_open, 3),
        'days_since_app_login':   days_no_login,
    })

app_df = pd.DataFrame(app_rows)

# Ugradi u churn score (app signal = ±15% utjecaj)
churn = churn.merge(app_df, on='IDENTIFIKATOR_KLIJENTA', how='left')
cr_app = (1 - (churn['app_logins_30d'].clip(0, 10) / 10)) * 15
churn['CHURN_RISK'] = (churn['CHURN_RISK'] * 0.85 + cr_app * 1.0).clip(0, 100)
# Ponovi binding cap
churn['CHURN_RISK'] = np.where(
    churn['ima_kredit'] == 1,
    churn['CHURN_RISK'].clip(0, 45),
    churn['CHURN_RISK'])

print(f"  ✓ App engagement simuliran za {len(app_df):,} klijenata")
print(f"  ✓ Prosječni logins/mj: {app_df['app_logins_30d'].mean():.1f}  "
      f"  Prosječni push open rate: {app_df['push_open_rate'].mean():.1%}")


# ════════════════════════════════════════════════════════════
# 7. PRIORITY SCORE & SEGMENTACIJA
# ════════════════════════════════════════════════════════════

print("\n[7/9] Izračun Priority Score i segmentacija...")

final = klijenti[['IDENTIFIKATOR_KLIJENTA', 'DOB', 'SPOL',
                   'VRSTA_ZAPOSLENJA', 'KLIJENT_PRIMA_OSNOVNO_PRIMANJE_U_BANCI']].copy()

final = (final
    .merge(clv[['IDENTIFIKATOR_KLIJENTA', 'CLV_SCORE', 'aktivnih_proizvoda',
                'has_kredit', 'has_depozit', 'prima_placu', 'tenure_years',
                'avg_monthly_vol', 'avg_balance_90d']],
           on='IDENTIFIKATOR_KLIJENTA', how='left')
    .merge(churn[['IDENTIFIKATOR_KLIJENTA', 'CHURN_RISK', 'days_since_txn',
                  'app_logins_30d', 'push_open_rate', 'prigovori_6m',
                  'freq_drop', 'bal_drop', 'vol_drop', 'digital_ratio', 'ima_kredit']],
           on='IDENTIFIKATOR_KLIJENTA', how='left')
    .merge(potential[['IDENTIFIKATOR_KLIJENTA', 'FUTURE_POTENTIAL',
                      'age_score', 'job_score', 'crossell_score']],
           on='IDENTIFIKATOR_KLIJENTA', how='left')
)
final = final.fillna(0)

# Priority Score s modifikatorima
final['PRIORITY_SCORE'] = (
    W_CHURN     * final['CHURN_RISK'] +
    W_CLV       * final['CLV_SCORE'] +
    W_POTENTIAL * final['FUTURE_POTENTIAL']
)
# Bonus modifikatori
final['PRIORITY_SCORE'] += np.where(final['prigovori_6m'] > 0, 10, 0)    # neriješeni prigovor
final['PRIORITY_SCORE'] += np.where(final['prima_placu'] == 1, 5, 0)      # prima plaću
final['PRIORITY_SCORE'] = final['PRIORITY_SCORE'].clip(0, 100)

# ════════════════════════════════════════════════════════════
# 3D SEGMENTACIJA: Churn Risk × CLV × Future Potential
# ════════════════════════════════════════════════════════════
#
#  8 segmenata (2 × 2 × 2):
#
#  Churn  CLV   Potential   Segment            Logika
#  ─────────────────────────────────────────────────────────
#  V      V     V           SPASI PRIORITET    zlatni klijent koji odlazi — sve resurse
#  V      V     N           SPASI              vrijedan klijent, rizik odlaska
#  V      N     V           INVESTIRAJ         mlad/potencijalan, još nizak CLV — gradi odnos
#  V      N     N           UPOZORI            odlazi, ali nije isplativo investirati mnogo
#  N      V     V           RAZVIJAJ PREMIUM   siguran + vrijedan + potencijal → cross-sell
#  N      V     N           ODRŽAVAJ           siguran, vrijedan → loyalty
#  N      N     V           RAZVIJAJ           nizak CLV, ali potencijal za rast
#  N      N     N           PRATI              monitoring, bez aktivne akcije
# ════════════════════════════════════════════════════════════

clv_med = final['CLV_SCORE'].median()
pot_med = final['FUTURE_POTENTIAL'].median()

def segmentiraj_3d(row):
    high_churn = row['CHURN_RISK']       > CHURN_THRESHOLD   # >60
    high_clv   = row['CLV_SCORE']        > clv_med
    high_pot   = row['FUTURE_POTENTIAL'] > pot_med

    if   high_churn and high_clv  and high_pot:  return 'SPASI PRIORITET'
    elif high_churn and high_clv  and not high_pot: return 'SPASI'
    elif high_churn and not high_clv and high_pot:  return 'INVESTIRAJ'
    elif high_churn and not high_clv and not high_pot: return 'UPOZORI'
    elif not high_churn and high_clv and high_pot:  return 'RAZVIJAJ PREMIUM'
    elif not high_churn and high_clv and not high_pot: return 'ODRŽAVAJ'
    elif not high_churn and not high_clv and high_pot: return 'RAZVIJAJ'
    else: return 'PRATI'

final['SEGMENT'] = final.apply(segmentiraj_3d, axis=1)

# Preporučene akcije po segmentu
AKCIJE = {
    'SPASI PRIORITET': '🚨  Hitan osobni poziv + premium ponuda (hipoteka/invest. fond)',
    'SPASI':           '📞  Osobni poziv savjetnika + konkretna retencijska ponuda',
    'INVESTIRAJ':      '📱  Personalizirana digitalna ponuda + relationship building',
    'UPOZORI':         '📧  Automatska jeftina ponuda, niska investicija',
    'RAZVIJAJ PREMIUM':'💼  Proaktivni cross-sell: kredit, hipoteka, investicije',
    'ODRŽAVAJ':        '🎁  Loyalty program / proaktivni check-in',
    'RAZVIJAJ':        '📧  Nurture kampanja / onboarding novih proizvoda',
    'PRATI':           '👁️   Automatizirani monitoring, bez aktivne akcije',
}
BUDGET = {
    'SPASI PRIORITET': 'Neograničen',
    'SPASI':           'Visok',
    'INVESTIRAJ':      'Srednji',
    'UPOZORI':         'Minimalan',
    'RAZVIJAJ PREMIUM':'Visok',
    'ODRŽAVAJ':        'Nizak',
    'RAZVIJAJ':        'Minimalan',
    'PRATI':           'Nula',
}
final['PREPORUCENA_AKCIJA'] = final['SEGMENT'].map(AKCIJE)

# Ispis pregleda segmenata
SEG_ORDER = ['SPASI PRIORITET','SPASI','INVESTIRAJ','UPOZORI',
             'RAZVIJAJ PREMIUM','ODRŽAVAJ','RAZVIJAJ','PRATI']
print(f"\n  {'SEGMENT':<18} {'BROJ':>6}   {'AVG PRIORITY':>12}   {'BUDGET':<14} AKCIJA")
print("  " + "─" * 95)
for seg in SEG_ORDER:
    sub = final[final['SEGMENT'] == seg]
    if len(sub) == 0:
        continue
    print(f"  {seg:<18} {len(sub):>6}   {sub['PRIORITY_SCORE'].mean():>12.1f}"
          f"   {BUDGET[seg]:<14} {AKCIJE[seg]}")


# ════════════════════════════════════════════════════════════
# 8. VIZUALIZACIJE — DASHBOARD
# ════════════════════════════════════════════════════════════

print("\n[8/9] Generiranje vizualizacija...")

SEG_COLORS = {
    'SPASI PRIORITET': '#B71C1C',   # tamno crvena
    'SPASI':           '#E53935',   # crvena
    'INVESTIRAJ':      '#FB8C00',   # narančasta
    'UPOZORI':         '#FDD835',   # žuta
    'RAZVIJAJ PREMIUM':'#1565C0',   # tamno plava
    'ODRŽAVAJ':        '#1E88E5',   # plava
    'RAZVIJAJ':        '#43A047',   # zelena
    'PRATI':           '#9E9E9E',   # siva
}
final['boja'] = final['SEGMENT'].map(SEG_COLORS)

fig = plt.figure(figsize=(20, 13))
fig.suptitle('HPB Hackathon — Churn Prevention Dashboard', fontsize=17,
             fontweight='bold', y=0.98)

# ── 1. Distribucija scoreva ──────────────────────────────
ax1 = fig.add_subplot(2, 3, 1)
for score, color, label in [
    ('CLV_SCORE',       '#1E88E5', 'CLV Score'),
    ('CHURN_RISK',      '#E53935', 'Churn Risk'),
    ('FUTURE_POTENTIAL','#43A047', 'Future Potential'),
]:
    ax1.hist(final[score], bins=30, alpha=0.55, color=color, label=label, density=True)
ax1.set_title('Distribucija scoreva', fontweight='bold')
ax1.set_xlabel('Score (0–100)')
ax1.set_ylabel('Gustoća')
ax1.legend(fontsize=9)

# ── 2. Segmentacija — pie ────────────────────────────────
ax2 = fig.add_subplot(2, 3, 2)
seg_counts = final['SEGMENT'].value_counts().reindex(SEG_ORDER, fill_value=0)
seg_counts = seg_counts[seg_counts > 0]
wedges, texts, autotexts = ax2.pie(
    seg_counts.values,
    labels=seg_counts.index,
    autopct='%1.0f%%',
    colors=[SEG_COLORS[s] for s in seg_counts.index],
    startangle=90,
    pctdistance=0.78,
)
for at in autotexts:
    at.set_fontsize(9)
ax2.set_title('Segmentacija klijenata', fontweight='bold')

# ── 3. CLV vs Churn Risk scatter ─────────────────────────
ax3 = fig.add_subplot(2, 3, 3)
ax3.scatter(final['CLV_SCORE'], final['CHURN_RISK'],
            c=final['boja'], alpha=0.35, s=12, linewidths=0)
ax3.axhline(CHURN_THRESHOLD, color='red', ls='--', alpha=0.6, lw=1.2,
            label=f'Churn prag ({CHURN_THRESHOLD})')
ax3.axvline(clv_med, color='blue', ls='--', alpha=0.6, lw=1.2,
            label=f'CLV medijan ({clv_med:.0f})')
patches = [mpatches.Patch(color=v, label=k) for k, v in SEG_COLORS.items()]
ax3.legend(handles=patches, fontsize=7, loc='upper right')
ax3.set_xlabel('CLV Score')
ax3.set_ylabel('Churn Risk Score')
ax3.set_title('CLV × Churn Risk', fontweight='bold')

# ── 4. Future Potential vs Churn Risk ────────────────────
ax4 = fig.add_subplot(2, 3, 4)
ax4.scatter(final['FUTURE_POTENTIAL'], final['CHURN_RISK'],
            c=final['boja'], alpha=0.35, s=12, linewidths=0)
ax4.axhline(CHURN_THRESHOLD, color='red', ls='--', alpha=0.6, lw=1.2)
ax4.axvline(pot_med, color='green', ls='--', alpha=0.6, lw=1.2,
            label=f'Potential medijan ({pot_med:.0f})')
ax4.legend(handles=patches, fontsize=7, loc='upper right')
ax4.set_xlabel('Future Potential Score')
ax4.set_ylabel('Churn Risk Score')
ax4.set_title('Future Potential × Churn Risk', fontweight='bold')

# ── 5. Top 20 klijenata za akciju ────────────────────────
ax5 = fig.add_subplot(2, 3, 5)
top20 = (final.nlargest(20, 'PRIORITY_SCORE')
         [['IDENTIFIKATOR_KLIJENTA', 'PRIORITY_SCORE', 'SEGMENT']]
         .reset_index(drop=True))
bar_colors = [SEG_COLORS[s] for s in top20['SEGMENT']]
ax5.barh(range(20), top20['PRIORITY_SCORE'], color=bar_colors, edgecolor='white', lw=0.5)
ax5.set_yticks(range(20))
ax5.set_yticklabels(
    [f"{i+1:>2}. {k[:10]}..." for i, k in enumerate(top20['IDENTIFIKATOR_KLIJENTA'])],
    fontsize=7)
ax5.set_xlabel('Priority Score')
ax5.set_title('Top 20 klijenata za akciju', fontweight='bold')
ax5.invert_yaxis()
ax5.set_xlim(0, 100)

# ── 6. CLV × Potential matrica (heatmap) ─────────────────
ax6 = fig.add_subplot(2, 3, 6)
matrix = pd.crosstab(
    pd.cut(final['CLV_SCORE'],
           bins=[0, 33, 66, 100],
           labels=['Nizak\nCLV', 'Srednji\nCLV', 'Visoki\nCLV']),
    pd.cut(final['FUTURE_POTENTIAL'],
           bins=[0, 33, 66, 100],
           labels=['Nizak\nPotencijal', 'Srednji\nPotencijal', 'Visoki\nPotencijal'])
)
sns.heatmap(matrix, annot=True, fmt='d', cmap='YlOrRd', ax=ax6,
            linewidths=0.8, cbar_kws={'shrink': 0.75}, annot_kws={'size': 10})
ax6.set_title('CLV × Future Potential matrica\n(broj klijenata)', fontweight='bold')
ax6.set_ylabel('')

plt.tight_layout(rect=[0, 0, 1, 0.96])
out_dashboard = DATA_PATH.replace('OneDrive_2026-04-16\\', '') + 'churn_dashboard.png'
plt.savefig(out_dashboard, dpi=150, bbox_inches='tight')
plt.show()
print(f"  ✓ Dashboard: churn_dashboard.png")


# ════════════════════════════════════════════════════════════
# 9. PRIČA JEDNOG KLIJENTA  (demonstracija)
# ════════════════════════════════════════════════════════════

print("\n[9/9] Priča jednog klijenta — Demo")
print("─" * 62)

# Odabir: klijent iz SPASI segmenta s najvišim Priority Scoreom
spasi = final[final['SEGMENT'] == 'SPASI']
demo_row = (spasi if len(spasi) > 0 else final).nlargest(1, 'PRIORITY_SCORE').iloc[0]
demo_id  = demo_row['IDENTIFIKATOR_KLIJENTA']

demo_kl  = klijenti[klijenti['IDENTIFIKATOR_KLIJENTA'] == demo_id].iloc[0]
demo_txn = (transakcije[transakcije['IDENTIFIKATOR_KLIJENTA'] == demo_id]
            .dropna(subset=['DATUM']).copy())

print(f"\n👤  Klijent:           {demo_id}")
print(f"    Dob:               {int(demo_kl.get('DOB', '?'))} godina")
print(f"    Zaposlenje:        {demo_kl.get('VRSTA_ZAPOSLENJA', '?')}")
print(f"    Tenure:            {demo_row['tenure_years']:.1f} godina u HPB-u")
print(f"    Prima plaću u HPB: {demo_kl.get('KLIJENT_PRIMA_OSNOVNO_PRIMANJE_U_BANCI', '?')}")
print(f"    Aktivnih proizvoda:{int(demo_row['aktivnih_proizvoda'])}")
print(f"    Ima kredit:        {'DA' if demo_row['has_kredit'] else 'NE'}")
print()
print(f"📊  SCOREVI:")
print(f"    CLV Score:          {demo_row['CLV_SCORE']:>5.1f} / 100")
print(f"    Churn Risk:         {demo_row['CHURN_RISK']:>5.1f} / 100  ⚠️")
print(f"    Future Potential:   {demo_row['FUTURE_POTENTIAL']:>5.1f} / 100")
print(f"    {'─'*28}")
print(f"    PRIORITY SCORE:     {demo_row['PRIORITY_SCORE']:>5.1f} / 100")
print()
print(f"🎯  SEGMENT:  {demo_row['SEGMENT']}")
print(f"💡  AKCIJA:   {demo_row['PREPORUCENA_AKCIJA']}")

# Vizualizacija transakcijskog trenda za demo klijenta
if len(demo_txn) >= 3:
    demo_txn['MJESEC'] = demo_txn['DATUM'].dt.to_period('M')
    monthly = (demo_txn.groupby('MJESEC')
               .agg(count=('IZNOS', 'count'), volume=('IZNOS', 'sum'))
               .reset_index())
    monthly['MJ_DT'] = monthly['MJESEC'].dt.to_timestamp()

    fig2, (ax_a, ax_b) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    fig2.suptitle(
        f"Priča klijenta  {demo_id[:14]}…  |  "
        f"Segment: {demo_row['SEGMENT']}  |  "
        f"Priority Score: {demo_row['PRIORITY_SCORE']:.0f}",
        fontsize=13, fontweight='bold')

    # Frekvencija
    bar_cols = ['#F44336' if d >= REF_DATE - pd.Timedelta(days=90) else '#90CAF9'
                for d in monthly['MJ_DT']]
    ax_a.bar(monthly['MJ_DT'], monthly['count'], color=bar_cols, width=25, alpha=0.85)
    ax_a.axvline(REF_DATE - pd.Timedelta(days=90), color='red', ls='--',
                 alpha=0.7, label='Zadnjih 90 dana')
    ax_a.set_ylabel('Broj transakcija / mj.')
    ax_a.set_title('Frekvencija transakcija — vidljivi pad!', loc='left')
    ax_a.legend()

    # Volumen
    ax_b.fill_between(monthly['MJ_DT'], monthly['volume'], alpha=0.3, color='#E53935')
    ax_b.plot(monthly['MJ_DT'], monthly['volume'], color='#E53935', lw=2)
    ax_b.axvline(REF_DATE - pd.Timedelta(days=90), color='red', ls='--', alpha=0.7)
    ax_b.set_ylabel('Transakcijski volumen (EUR)')
    ax_b.set_title('Ukupni volumen — trend prema dolje!', loc='left')

    plt.tight_layout()
    out_story = DATA_PATH.replace('OneDrive_2026-04-16\\', '') + 'client_story.png'
    plt.savefig(out_story, dpi=150, bbox_inches='tight')
    plt.show()
    print(f"\n  ✓ Client story: client_story.png")
else:
    print("\n  (Nema dovoljno transakcija za ovog klijenta — odaberi drugi)")

# ════════════════════════════════════════════════════════════
# EXPORT REZULTATA
# ════════════════════════════════════════════════════════════

output_cols = [
    'IDENTIFIKATOR_KLIJENTA', 'DOB', 'VRSTA_ZAPOSLENJA',
    'CLV_SCORE', 'CHURN_RISK', 'FUTURE_POTENTIAL', 'PRIORITY_SCORE',
    'SEGMENT', 'PREPORUCENA_AKCIJA',
    'aktivnih_proizvoda', 'has_kredit', 'tenure_years',
    'days_since_txn', 'app_logins_30d', 'push_open_rate', 'prigovori_6m',
]
out_csv = DATA_PATH.replace('OneDrive_2026-04-16\\', '') + 'churn_results.csv'
(final[output_cols]
 .sort_values('PRIORITY_SCORE', ascending=False)
 .to_csv(out_csv, index=False, encoding='utf-8-sig'))

print(f"\n  ✓ Rezultati: churn_results.csv  ({len(final):,} klijenata)")
print("\n" + "=" * 62)
print("  ZAVRŠENO!")
print("=" * 62)


# ════════════════════════════════════════════════════════════
# DETALJNA ANALIZA FAKTORA PO KLIJENTU
# ════════════════════════════════════════════════════════════

pd.set_option('display.max_columns', None)
pd.set_option('display.width', 160)
pd.set_option('display.float_format', '{:.1f}'.format)

print("\n\n" + "═" * 80)
print("  DETALJNA ANALIZA FAKTORA — TOP 20 KLIJENATA")
print("═" * 80)

top20 = final.nlargest(20, 'PRIORITY_SCORE').reset_index(drop=True)

# ── CLV FAKTORI ──────────────────────────────────────────────────────────────
print("\n📊 CLV FAKTORI (trenutna vrijednost)")
print("─" * 80)
clv_faktori = top20[[
    'IDENTIFIKATOR_KLIJENTA', 'SEGMENT', 'CLV_SCORE',
    'aktivnih_proizvoda', 'has_kredit', 'prima_placu',
    'avg_monthly_vol', 'avg_balance_90d', 'tenure_years'
]].copy()
clv_faktori.columns = [
    'Klijent', 'Segment', 'CLV Score',
    'Br. proizvoda', 'Ima kredit', 'Prima plaću',
    'Avg vol/mj (€)', 'Avg stanje (€)', 'Tenure (god)'
]
clv_faktori['Klijent'] = clv_faktori['Klijent'].str[:12]
print(clv_faktori.to_string(index=False))

# ── CHURN RISK FAKTORI ───────────────────────────────────────────────────────
print("\n\n⚠️  CHURN RISK FAKTORI (signali odlaska)")
print("─" * 80)
churn_faktori = top20[[
    'IDENTIFIKATOR_KLIJENTA', 'SEGMENT', 'CHURN_RISK',
    'freq_drop', 'days_since_txn', 'bal_drop',
    'vol_drop', 'prigovori_6m', 'digital_ratio',
    'app_logins_30d', 'push_open_rate', 'ima_kredit'
]].copy()
churn_faktori['freq_drop']   = (churn_faktori['freq_drop']   * 100).round(0).astype(int).astype(str) + '%'
churn_faktori['bal_drop']    = (churn_faktori['bal_drop']    * 100).round(0).astype(int).astype(str) + '%'
churn_faktori['vol_drop']    = (churn_faktori['vol_drop']    * 100).round(0).astype(int).astype(str) + '%'
churn_faktori['digital_ratio'] = (churn_faktori['digital_ratio'] * 100).round(0).astype(int).astype(str) + '%'
churn_faktori['push_open_rate'] = (churn_faktori['push_open_rate'] * 100).round(0).astype(int).astype(str) + '%'
churn_faktori.columns = [
    'Klijent', 'Segment', 'Churn Risk',
    'Pad txn freq', 'Dana bez txn', 'Pad stanja',
    'Pad volumena', 'Prigovori 6mj', 'Digital %',
    'App logins/mj', 'Push open %', 'Ima kredit'
]
churn_faktori['Klijent'] = churn_faktori['Klijent'].str[:12]
print(churn_faktori.to_string(index=False))

# ── FUTURE POTENTIAL FAKTORI ─────────────────────────────────────────────────
print("\n\n🚀 FUTURE POTENTIAL FAKTORI (budući potencijal)")
print("─" * 80)
pot_faktori = top20[[
    'IDENTIFIKATOR_KLIJENTA', 'SEGMENT', 'FUTURE_POTENTIAL',
    'DOB', 'VRSTA_ZAPOSLENJA', 'job_score', 'has_kredit', 'has_depozit',
    'aktivnih_proizvoda', 'crossell_score', 'age_score'
]].copy()
pot_faktori.columns = [
    'Klijent', 'Segment', 'Potential',
    'Dob', 'Zaposlenje', 'Job score', 'Ima kredit', 'Ima depozit',
    'Br. proizvoda', 'Cross-sell score', 'Age score'
]
pot_faktori['Klijent'] = pot_faktori['Klijent'].str[:12]
pot_faktori['Zaposlenje'] = pot_faktori['Zaposlenje'].str[:12]
print(pot_faktori.to_string(index=False))

# ── SUMMARY ─────────────────────────────────────────────────────────────────
print("\n\n📋 SUMMARY — SVI 3 FAKTORA ZAJEDNO")
print("─" * 80)
summary = top20[[
    'IDENTIFIKATOR_KLIJENTA', 'DOB', 'CLV_SCORE', 'CHURN_RISK',
    'FUTURE_POTENTIAL', 'PRIORITY_SCORE', 'SEGMENT'
]].copy()
summary.columns = ['Klijent', 'Dob', 'CLV', 'Churn Risk', 'Potential', 'Priority', 'Segment']
summary['Klijent'] = summary['Klijent'].str[:12]
print(summary.to_string(index=False))
