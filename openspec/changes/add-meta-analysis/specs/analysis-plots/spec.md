# analysis-plots Specification

## Purpose

Deterministic, accessible SVG plots of analysis results — forest, funnel,
bubble, and Baujat — always accompanied by the values needed to rebuild them
elsewhere.

## ADDED Requirements

### Requirement: Deterministic, accessible plots

Plots MUST be emitted as deterministic SVG with content-derived element ids,
theme-aware (light and dark), with colour-blind-safe palettes, and MUST never
rely on colour alone to convey a distinction. Every plot MUST support
`--format svg|pdf|png` and MUST be accompanied by the underlying values in
`studies.tsv`.

#### Scenario: Cross-platform regeneration

- **WHEN** a forest plot is regenerated on Windows from the same commit that produced it on Linux
- **THEN** the SVG is byte-identical

### Requirement: Forest plot contents

A forest plot MUST show study label, `n`, the effect estimate and CI
numerically, the plotted estimate with CI, the weight, a diamond for the pooled
estimate, the prediction interval as a distinct band, and a heterogeneity
footer (`k`, `tau`, `I2`, `Q`, `p`), with subgroup rows when a categorical
moderator is specified.

#### Scenario: Random-effects forest plot

- **WHEN** a random-effects forest plot is rendered
- **THEN** it includes the pooled diamond, a distinct prediction-interval band, and the heterogeneity footer

### Requirement: Funnel and bubble plots

The funnel plot MUST default to contour-enhanced, with the pooled estimate and
pseudo-confidence contours marked. The bubble plot for a continuous moderator
MUST plot effect against moderator with bubble area proportional to weight and
a fitted line with a confidence band.

#### Scenario: Default funnel plot

- **WHEN** a funnel plot is requested without options
- **THEN** it is contour-enhanced
