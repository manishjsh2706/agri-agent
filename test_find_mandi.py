"""Quick sanity checks for pune_mandis.find_mandi_by_name().

Run:  python test_find_mandi.py
"""

from pune_mandis import find_mandi_by_name

QUERIES = [
    "Hadapsar",            # area hint -> Pune(Manjri)
    "hadpsar",             # misspelled, fuzzy -> Pune(Manjri) or hadapsar hint
    "hadapsar mandi",      # trailing 'mandi' should be stripped
    "manjri",              # substring / hint -> Pune(Manjri)
    "Pune APMC",           # exact after ' APMC' aliasing -> Pune
    "chakan",              # exact -> Chakan
    "moshi",               # area hint -> Pune(Moshi)
    "kothrud",             # area hint -> Pune
    "pcmc",                # area hint -> Pimpri
    "narayangaon",         # area hint -> Junnar(Narayangaon)
    "bhigwan",             # area hint -> Indapur(Bhigwan)
    "chaakan",             # typo -> fuzzy -> Chakan
    "random-nonsense-xx",  # should be None
]


def main() -> None:
    fails = 0
    for q in QUERIES:
        r = find_mandi_by_name(q)
        if r is None:
            print(f"  {q!r:<24}  ->  None")
            if q != "random-nonsense-xx":
                fails += 1
        else:
            print(f"  {q!r:<24}  ->  {r['matched_name']:<24} "
                  f"({r['latitude']:.4f}, {r['longitude']:.4f})  "
                  f"[{r['match_type']}]")
    if fails:
        raise SystemExit(f"{fails} unexpected None(s)")
    print("\nOK.")


if __name__ == "__main__":
    main()
