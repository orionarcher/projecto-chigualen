# Archive

## `app/` — the Streamlit application

The original interface, superseded by the static site in [`../web`](../web/README.md).
It is kept for two reasons, and only the first is sentimental.

### It is the reference implementation

`app/data.py` holds `resolve()` — the single function that decides what a name
means: whether it is current, what it is a synonym of, and what each source says
about it individually. The browser has its own copy of that logic in
`web/js/data.js`, and two implementations of CITES-relevant semantics is exactly
how a species card and a batch export start disagreeing, which is the failure the
CITES authority originally reported.

So the browser copy is held to this one. `tests/make_parity_fixture.py` imports
`app.data` from here and freezes 1,213 verdicts; `web/parity/` replays every one
of them through the browser resolver and compares field by field, per-source
verdicts included. **Run it after touching either.**

That makes this archive load-bearing rather than dead. If you change the
semantics, change them here first, regenerate the fixture, then make the browser
agree.

### It still runs

Against the same data, with no build step and no browser bundle:

```bash
pip install -r ../requirements.txt
streamlit run archive/app/app.py     # from the repository root
```

Useful for checking a result by a different route when the static site says
something surprising.

## What it does not have

The static site's search box is a ranked typeahead — epithet matching, typo
tolerance, keyboard navigation. This one has the original plain prefix search.
Search ranking is presentation and deliberately sits outside the resolver the two
must agree on, so they are allowed to differ here.
