"""`parse_mapping` and `describe_table`: what the import pipeline can say about a spreadsheet-like
export before anything is imported (OpenSpec change `add-web-ui-write-surfaces`, task 1.3).

Both exist so a surface that offers a column or sheet choice (the web review page) is decided by
the same code as the import itself.
"""

from pathlib import Path

import pytest

from strata.ingest import pipeline
from strata.ingest.parsers import csv_tsv
from tests.unit._xlsx import build_xlsx

_SCOPUS_HEADER = ["Authors", "Title", "Year", "Source title", "EID", "DOI", "Abstract"]
_CUSTOM_HEADER = ["MyTitle", "MyAuthor", "MyYear"]


def _write(tmp_path: Path, name: str, text: str) -> Path:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


# ------------------------------------------------------------------------------ parse_mapping


def test_parse_mapping_reads_field_equals_column_pairs() -> None:
    assert pipeline.parse_mapping("title=Article Title, doi = DOI") == {
        "title": "Article Title",
        "doi": "DOI",
    }


def test_parse_mapping_keeps_an_equals_sign_inside_a_column_name() -> None:
    assert pipeline.parse_mapping("title=a=b") == {"title": "a=b"}


def test_parse_mapping_refuses_an_entry_without_an_equals_sign() -> None:
    with pytest.raises(pipeline.MappingSyntaxError, match="'author' is not of the form"):
        pipeline.parse_mapping("title=T,author")


def test_the_mappable_fields_are_the_csv_parsers() -> None:
    assert "title" in pipeline.MAPPABLE_FIELDS and "DOI" in pipeline.MAPPABLE_FIELDS
    assert list(pipeline.MAPPABLE_FIELDS) == sorted(pipeline.MAPPABLE_FIELDS)


# ----------------------------------------------------------------------------- describe_table


def test_a_known_platform_csv_is_recognised_with_the_mapping_it_implies(tmp_path: Path) -> None:
    path = _write(tmp_path, "scopus.csv", ",".join(_SCOPUS_HEADER) + "\nx,y,2020,j,e,d,a\n")

    layout = pipeline.describe_table(path)

    assert layout is not None
    assert (layout.format, layout.columns, layout.platform) == ("csv", _SCOPUS_HEADER, "scopus")
    assert layout.detected_mapping is not None
    assert layout.detected_mapping["title"] == "Title"
    # Only columns this export actually has: a profile lists every column a platform might emit.
    assert "Author Keywords" not in layout.detected_mapping.values()
    assert layout.sheets is None and layout.sheet is None


def test_an_unrecognised_csv_reports_its_columns_and_no_platform(tmp_path: Path) -> None:
    path = _write(tmp_path, "custom.csv", ",".join(_CUSTOM_HEADER) + "\nA Title,Doe,2020\n")

    layout = pipeline.describe_table(path)

    assert layout is not None
    assert layout.columns == _CUSTOM_HEADER
    assert layout.platform is None and layout.detected_mapping is None


def test_a_tsv_is_split_on_tabs(tmp_path: Path) -> None:
    path = _write(tmp_path, "custom.tsv", "\t".join(_CUSTOM_HEADER) + "\nA Title\tDoe\t2020\n")

    layout = pipeline.describe_table(path)

    assert layout is not None and (layout.format, layout.columns) == ("tsv", _CUSTOM_HEADER)


def test_a_workbook_lists_its_sheets_and_reads_the_first_by_default(tmp_path: Path) -> None:
    path = tmp_path / "export.xlsx"
    path.write_bytes(
        build_xlsx({"Export": [_CUSTOM_HEADER, ["T", "A", 2020]], "Notes": [["only"], ["notes"]]})
    )

    layout = pipeline.describe_table(path)

    assert layout is not None
    assert layout.format == "xlsx"
    assert layout.sheets == ["Export", "Notes"] and layout.sheet == "Export"
    assert layout.columns == _CUSTOM_HEADER


def test_a_workbook_sheet_can_be_chosen(tmp_path: Path) -> None:
    path = tmp_path / "export.xlsx"
    path.write_bytes(build_xlsx({"Export": [_CUSTOM_HEADER], "Other": [["Authors", "Title"]]}))

    layout = pipeline.describe_table(path, sheet="Other")

    assert layout is not None and layout.sheet == "Other" and layout.columns == ["Authors", "Title"]


def test_a_workbook_sheet_that_does_not_exist_is_an_import_error(tmp_path: Path) -> None:
    path = tmp_path / "export.xlsx"
    path.write_bytes(build_xlsx({"Export": [_CUSTOM_HEADER]}))

    with pytest.raises(pipeline.ImportPipelineError, match="no sheet 'Missing'"):
        pipeline.describe_table(path, sheet="Missing")


def test_a_corrupt_workbook_is_an_import_error_naming_the_file(tmp_path: Path) -> None:
    path = tmp_path / "broken.xlsx"
    path.write_bytes(b"this is not a zip archive")

    with pytest.raises(pipeline.ImportPipelineError, match=r"broken\.xlsx: .*not an \.xlsx"):
        pipeline.describe_table(path)


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("export.json", '[{"title": "T"}]'),
        ("export.ris", "TY  - JOUR\nTI  - T\nER  - \n"),
        ("export.bib", "@article{a, title={T}}"),
    ],
)
def test_other_formats_have_no_table_to_describe(tmp_path: Path, name: str, text: str) -> None:
    assert pipeline.describe_table(_write(tmp_path, name, text)) is None


def test_describing_a_missing_file_is_an_import_error(tmp_path: Path) -> None:
    with pytest.raises(pipeline.ImportPipelineError, match="no such file"):
        pipeline.describe_table(tmp_path / "nope.csv")


def test_a_sheet_is_refused_for_a_format_that_has_none(tmp_path: Path) -> None:
    path = _write(tmp_path, "custom.csv", "a,b\n1,2\n")

    with pytest.raises(pipeline.ImportPipelineError, match="only applies to an .xlsx"):
        pipeline.describe_table(path, sheet="1")


def test_description_agrees_with_what_import_would_use(tmp_path: Path) -> None:
    # The point of sharing the reader: the columns described are the columns the import maps.
    path = _write(tmp_path, "custom.csv", ",".join(_CUSTOM_HEADER) + "\nA Title,Doe,2020\n")
    layout = pipeline.describe_table(path)
    assert layout is not None

    mapping = {"title": layout.columns[0], "author": layout.columns[1]}
    text = path.read_text(encoding="utf-8")

    parsed = csv_tsv.parse(text, delimiter=",", mapping=mapping)
    assert [r["title"] for r in parsed.records] == ["A Title"]
