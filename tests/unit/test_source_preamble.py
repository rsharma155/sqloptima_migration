from domains.transpilation.source_preamble import attach_source_preamble, extract_source_preamble


def test_extract_leading_line_comments():
    sql = """-- Author: Example
-- Purpose: Demo proc
CREATE PROCEDURE dbo.usp_demo AS
BEGIN
    SELECT 1;
END"""
    preamble, body = extract_source_preamble(sql)
    assert "Author: Example" in preamble
    assert body.startswith("CREATE PROCEDURE")


def test_attach_preamble_to_converted():
    preamble = "-- Source metadata"
    converted = "CREATE OR REPLACE PROCEDURE public.usp_demo() AS $$ BEGIN END; $$;"
    out = attach_source_preamble(preamble, converted)
    assert out.startswith("-- Source metadata")
    assert "CREATE OR REPLACE PROCEDURE" in out
