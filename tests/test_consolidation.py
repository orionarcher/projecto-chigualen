"""End-to-end check of 06 + 08 on a synthetic five-source fixture.

The real pipeline cannot be run from a checkout — the raw inputs of three of the
five sources are not committed — so this builds a miniature version of all five
cleaned sources that reproduces the exact record shapes behind the bugs the
CITES authority reported, runs the real consolidation over it, and asserts the
results.

Covered:
  * a species must not inherit its synonym's genus, epithet, ids, basionym or
    publication data (Stelis ariasii wearing Anathallis, Vanda falcata wearing
    Holcoglossum)
  * an infraspecific record that collapses onto the same binomial must not
    outrank the species record
  * a contested name must remain visible from the species it was proposed under
  * the three contest classes, and the wording that explains them
  * description_year, including recovery from a CITES author citation

Runs in a temp directory; touches no project data.

    python3 tests/test_consolidation.py
"""
import importlib.util, shutil, sys, tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
import pandas as pd
from _normalize import SCHEMA

tmp = Path(tempfile.mkdtemp())
clean = tmp / "Chigualen" / "data" / "clean"; clean.mkdir(parents=True)
out = tmp / "Chigualen" / "data" / "out"; out.mkdir(parents=True)


def row(**kw):
    r = {c: "" for c in SCHEMA}
    r.update(kw)
    return r


# --- wcvp: Stelis ariasii accepted (id 493188); Anathallis ariasii is its synonym
#     (id 219788). The synonym row is written FIRST, which is what used to make
#     the parent inherit the synonym's genus and ids.
wcvp = [
    row(source="wcvp", source_record_id="219788", relation="synonym_of",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii (Luer & Hirtz) Karremans",
        accepted_authority="(Luer & Hirtz) Karremans",
        synonym_name="Anathallis ariasii", synonym_name_full="Anathallis ariasii (L&H) P&C",
        synonym_authority="(L&H) P&C", synonym_type="Homotypic",
        family="Orchidaceae", genus="Anathallis", species="ariasii", taxon_rank="Species",
        basionym="159344", wcvp_plant_name_id="219788",
        wcvp_accepted_plant_name_id="493188", wcvp_ipni_id="1161084-2",
        first_published="(2001)", place_of_publication="Lindleyana",
        geographic_area="Peru"),
    row(source="wcvp", source_record_id="493188", relation="accepted",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii (Luer & Hirtz) Karremans",
        accepted_authority="(Luer & Hirtz) Karremans",
        family="Orchidaceae", genus="Stelis", species="ariasii", taxon_rank="Species",
        wcvp_plant_name_id="493188", wcvp_accepted_plant_name_id="493188",
        wcvp_ipni_id="77142152-1", first_published="(2014)",
        place_of_publication="Lankesteriana", geographic_area="Peru"),
    # An infraspecific taxon that collapses onto the same binomial and must not
    # outrank the species record.
    row(source="wcvp", source_record_id="999", relation="accepted",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii var. x",
        accepted_authority="Someone", family="Orchidaceae", genus="Stelis",
        species="ariasii", infraspecific_epithet="x", taxon_rank="Variety",
        wcvp_plant_name_id="999", wcvp_accepted_plant_name_id="999",
        wcvp_ipni_id="WRONG-1", first_published="(1899)"),
    # A name every source agrees is a synonym of a contested parent.
    row(source="wcvp", source_record_id="255849", relation="synonym_of",
        accepted_name="Oncidium ariasii", accepted_name_full="Oncidium ariasii Königer",
        accepted_authority="Königer", synonym_name="Oncidium isidrense",
        synonym_authority="Chiron", synonym_type="Heterotypic",
        family="Orchidaceae", genus="Oncidium", species="isidrense"),
    row(source="wcvp", source_record_id="458571", relation="accepted",
        accepted_name="Oncidium ariasii", accepted_name_full="Oncidium ariasii Königer",
        accepted_authority="Königer", family="Orchidaceae", genus="Oncidium",
        species="ariasii", wcvp_plant_name_id="458571"),
]
# --- wfo agrees with wcvp on the ariasii pair
wfo = [
    row(source="wfo", source_record_id="wfo-0000339553", relation="synonym_of",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii (L&H) Karremans",
        accepted_authority="(L&H) Karremans", synonym_name="Anathallis ariasii",
        synonym_authority="(L&H) P&C", synonym_type="Unknown",
        family="Orchidaceae", genus="Anathallis", species="ariasii",
        wfo_taxon_id="wfo-0000339553"),
    row(source="wfo", source_record_id="wfo-0001340449", relation="accepted",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii (L&H) Karremans",
        accepted_authority="(L&H) Karremans", family="Orchidaceae", genus="Stelis",
        species="ariasii", wfo_taxon_id="wfo-0001340449"),
]
# --- cites_csv: lists Anathallis ariasii as accepted, with the year in the author string
cites_csv = [
    # Contradicts wcvp on Oncidium ariasii -> status_conflict, which its
    # unanimously-placed synonym Oncidium isidrense must inherit.
    row(source="cites_csv", source_record_id="61072", relation="synonym_of",
        accepted_name="Oncidium koenigeri", accepted_name_full="Oncidium koenigeri",
        synonym_name="Oncidium ariasii", synonym_type="Unknown",
        family="Orchidaceae", genus="Oncidium", species="ariasii"),
    # Only source for this species, and the only year is inside the author string.
    row(source="cites_csv", source_record_id="80001", relation="accepted",
        accepted_name="Bulbophyllum testicum",
        accepted_name_full="Bulbophyllum testicum Königer, 1994",
        accepted_authority="Königer, 1994", family="Orchidaceae",
        genus="Bulbophyllum", species="testicum", cites_appendix="II"),
    row(source="cites_csv", source_record_id="71932", relation="accepted",
        accepted_name="Anathallis ariasii",
        accepted_name_full="Anathallis ariasii (Luer & Hirtz) Pridgeon & M.W.Chase, 2001",
        accepted_authority="(Luer & Hirtz) Pridgeon & M.W.Chase, 2001",
        family="Orchidaceae", genus="Anathallis", species="ariasii",
        cites_appendix="II", geographic_area="Peru"),
]
# --- cites_pdf and user_synonyms: one pair each, parent-conflict material
cites_pdf = [
    row(source="cites_pdf", source_record_id="p1_y1.0_0", relation="synonym_of",
        accepted_name="Stelis ariasii", accepted_name_full="Stelis ariasii",
        synonym_name="Pleurothallis ariasii", synonym_type="Unknown",
        family="Orchidaceae", genus="Pleurothallis", species="ariasii"),
]
user_synonyms = [
    row(source="user_synonyms", source_record_id="1", relation="synonym_of",
        accepted_name="Specklinia ariasii", accepted_name_full="Specklinia ariasii",
        synonym_name="Pleurothallis ariasii", synonym_type="Homotypic",
        family="Orchidaceae", genus="Pleurothallis", species="ariasii"),
    row(source="user_synonyms", source_record_id="2", relation="accepted",
        accepted_name="Specklinia ariasii", accepted_name_full="Specklinia ariasii",
        family="Orchidaceae", genus="Specklinia", species="ariasii"),
]
for name, rows in [("wcvp", wcvp), ("wfo", wfo), ("cites_csv", cites_csv),
                   ("cites_pdf", cites_pdf), ("user_synonyms", user_synonyms)]:
    pd.DataFrame(rows, columns=SCHEMA).to_csv(clean / f"{name}.csv", index=False)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


m6 = load(REPO / "scripts" / "06_consolidate.py", "consolidate")
m6.ROOT, m6.CLEAN_DIR, m6.OUT_DIR = tmp, clean, out
print("=" * 30, "06")
m6.main()

m8 = load(REPO / "scripts" / "08_wide_format.py", "wide")
m8.ROOT, m8.OUT, m8.CONTESTED_PATH = tmp, out, out / "contested_names.csv"
print("=" * 30, "08")
m8.main()

wide = pd.read_csv(out / "orchid_synonyms_consolidated.csv", dtype=str, keep_default_na=False)
contested = pd.read_csv(out / "contested_names.csv", dtype=str, keep_default_na=False)
print("=" * 30, "assertions")

s = wide[wide.accepted_name == "Stelis ariasii"].iloc[0]
checks = [
    ("genus is Stelis, not Anathallis", s.genus, "Stelis"),
    ("species epithet", s.species, "ariasii"),
    ("wcvp id is the species', not the synonym's", s.wcvp_plant_name_id, "493188"),
    ("ipni is the species', not the synonym's or the variety's", s.wcvp_ipni_id, "77142152-1"),
    ("wfo id is the species'", s.wfo_taxon_id, "wfo-0001340449"),
    ("species record beats the variety", s.taxon_rank, "Species"),
    ("first_published from the species record", s.first_published, "(2014)"),
    ("description year", s.description_year, "2014"),
    ("contested names linked back", s.contested_synonyms,
     "Anathallis ariasii, Pleurothallis ariasii"),
    ("contested count", s.contested_synonym_count, "2"),
]
a = contested[contested.binomial == "Anathallis ariasii"]
checks += [
    ("Anathallis ariasii is a status_conflict", a.contest_class.iloc[0], "status_conflict"),
    ("cites_csv says accepted",
     a[a.source == "cites_csv"].source_says_relation.iloc[0], "accepted"),
    ("wcvp says synonym of Stelis ariasii",
     a[a.source == "wcvp"].source_says_accepted_parent.iloc[0], "Stelis ariasii"),
    ("reason is spelled out", "accepted by cites_csv" in a.contest_reason.iloc[0], True),
]
iso = contested[contested.binomial == "Oncidium isidrense"]
checks.append(("Oncidium isidrense inherits its parent's doubt",
               iso.contest_class.iloc[0] if len(iso) else "MISSING", "parent_contested"))
pl = contested[contested.binomial == "Pleurothallis ariasii"]
checks.append(("Pleurothallis ariasii has two claimed parents",
               pl.contest_class.iloc[0] if len(pl) else "MISSING", "parent_conflict"))
b = wide[wide.accepted_name == "Bulbophyllum testicum"]
checks.append(("year is recovered from a CITES author string",
               b.description_year.iloc[0] if len(b) else "MISSING", "1994"))
checks.append(("CITES-only species keeps its appendix",
               b.cites_appendix.iloc[0] if len(b) else "MISSING", "II"))

ok = True
for label, got, want in checks:
    good = got == want
    ok &= good
    print(f"  {'PASS' if good else 'FAIL'}  {label}: {got!r}" + ("" if good else f" (want {want!r})"))

ref = pd.read_csv(out / "contest_class_reference.csv")
print(f"  {'PASS' if len(ref) == 3 else 'FAIL'}  contest_class_reference has 3 rules")
shutil.rmtree(tmp)
print("\nALL PASS" if ok else "\nFAILURES ABOVE")
sys.exit(0 if ok else 1)
