-- Edge-case fixture values for migration round-trip regression tests.
-- Covers NULL vs empty string, Unicode, precision, and boundary values.

-- NULL vs empty string
SELECT NULL AS null_val, '' AS empty_str, ' ' AS whitespace;

-- Unicode / emoji / CJK
SELECT N'日本語テスト' AS cjk, N'🎉 emoji' AS emoji, N'café' AS accented;

-- Decimal / money precision
SELECT CAST(123456789012345678901234567890.123456789012345678 AS DECIMAL(38,18)) AS high_precision;

-- Zero / negative identity boundary
SELECT 0 AS zero_id, -1 AS negative_id;

-- Binary with NUL byte (represented as hex in test harness)
SELECT 0x00 AS nul_byte;
