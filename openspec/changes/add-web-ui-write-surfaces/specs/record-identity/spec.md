# Spec Delta

## ADDED Requirements

### Requirement: Corrections keep matching in step

When a correction changes a record's canonical key, the record MUST keep its id, take the new key as its canonical key, and make the id the new key gives an alias of the record, so that an import row carrying the corrected identity is matched to the record and not added beside it.

#### Scenario: A corrected DOI

- **GIVEN** a record imported with the DOI `10.1000/wrong`
- **WHEN** the DOI is corrected to `10.1000/right` and an export carrying `10.1000/right` is imported
- **THEN** the row is matched to the existing record and adds a source to it, and no record is added

#### Scenario: The old identity still matches

- **GIVEN** the same correction
- **WHEN** an export carrying `10.1000/wrong` is imported
- **THEN** the row is matched to the same record

#### Scenario: A corrected year on a record with no identifier

- **GIVEN** a record with no DOI or other identifier, whose identity includes its year
- **WHEN** the year is corrected and an export carrying the corrected year is imported
- **THEN** the row is matched to the record

### Requirement: A correction onto another identity is named

When the new key is already the identity of another record, no alias MUST be made and the correction MUST name that record, so that the two can be merged.

#### Scenario: A correction onto another record's identity

- **GIVEN** two records, `rec_a` and `rec_b`
- **WHEN** `rec_a`'s DOI is corrected to `rec_b`'s
- **THEN** no alias is made, the correction names `rec_b`, and `strata dedup` merges them
