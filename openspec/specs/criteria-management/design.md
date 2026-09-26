# Design: criteria-management

*Informative.* The requirements are in [spec.md](spec.md).

## Why the user classifies the direction

Whether an edit tightens, loosens, or merely rewords a criterion determines how
much work becomes stale, and the tool cannot reliably infer it from text. So it
asks:

```
  You edited EXC-03.

    was:  Publications not written in English.
    now:  Publications not written in English, and publications in English
          translation where the original instrument was not validated in
          the translated language.

  How does this change the set of papers the criterion excludes?

    [t] Tightened  - it now excludes MORE papers than before
    [l] Loosened   - it now excludes FEWER papers than before
    [b] Both       - some in, some out (or you are not sure)
    [e] Editorial  - wording only; the same papers are affected
```

"Tightened" is defined in terms of the included pool (it can only shrink) so the
same word works for inclusion and exclusion criteria.

## Why the editorial claim is checked

`editorial` is the one option that lets a user assert "nothing to redo", and it
is therefore the one a rushed user will reach for. `strata` does not accept the
assertion on trust: if the definition's meaning-bearing text changed, the honest
options are `tightened`, `loosened`, or `both` — and `both` is always safe.

## Added and retired

An added criterion creates new grounds for exclusion, so it behaves as
tightened. A retired criterion removes grounds, so it behaves as loosened.
Retired criteria stay in the file forever, and their ids are never reused,
because historical decisions cite them.
