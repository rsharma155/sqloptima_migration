// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package loader_test

import (
	"testing"

	"github.com/ravisharma/sql-optima/engine-go/internal/loader"
)

var pgSignature = []byte("PGCOPY\n\xff\r\n\x00")

func TestHeaderIsWrittenOnConstruction(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	out := enc.Finish()
	// signature (11) + flags (4) + ext-len (4) = 19 bytes, then -1 trailer (2)
	if len(out) < 19 {
		t.Fatalf("output too short: %d bytes", len(out))
	}
	if string(out[:11]) != string(pgSignature) {
		t.Errorf("signature mismatch: %x", out[:11])
	}
	if out[11] != 0 || out[12] != 0 || out[13] != 0 || out[14] != 0 {
		t.Error("flags must be zero")
	}
	if out[15] != 0 || out[16] != 0 || out[17] != 0 || out[18] != 0 {
		t.Error("header extension length must be zero")
	}
}

func TestTrailerIsMinusOneInt16(t *testing.T) {
	out := loader.NewBinaryCopyEncoder(1).Finish()
	n := len(out)
	if out[n-2] != 0xFF || out[n-1] != 0xFF {
		t.Errorf("trailer must be 0xFFFF, got %x %x", out[n-2], out[n-1])
	}
}

func TestInt32RowEncoding(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 258}}) //nolint:errcheck
	out := enc.Finish()
	// After 19-byte header:
	// Int16 field count = 1
	assertBytes(t, out[19:21], []byte{0x00, 0x01}, "field count")
	// Int32 length = 4
	assertBytes(t, out[21:25], []byte{0x00, 0x00, 0x00, 0x04}, "field length")
	// value 258 = 0x00000102
	assertBytes(t, out[25:29], []byte{0x00, 0x00, 0x01, 0x02}, "int32 value")
}

func TestNullFieldEncodedAsMinusOneLength(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	enc.WriteRow([]loader.CopyValue{loader.CopyNull{}}) //nolint:errcheck
	out := enc.Finish()
	// field count = 1
	assertBytes(t, out[19:21], []byte{0x00, 0x01}, "field count")
	// length = -1 → 0xFFFFFFFF
	assertBytes(t, out[21:25], []byte{0xFF, 0xFF, 0xFF, 0xFF}, "null length")
	// immediately followed by trailer
	assertBytes(t, out[25:27], []byte{0xFF, 0xFF}, "trailer after null")
}

func TestBoolEncoding(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(2)
	enc.WriteRow([]loader.CopyValue{loader.CopyBool{V: true}, loader.CopyBool{V: false}}) //nolint:errcheck
	out := enc.Finish()
	assertBytes(t, out[19:21], []byte{0x00, 0x02}, "field count")
	// field 1: len=1, value=1
	assertBytes(t, out[21:25], []byte{0x00, 0x00, 0x00, 0x01}, "bool true len")
	if out[25] != 0x01 {
		t.Errorf("bool true byte = %x, want 0x01", out[25])
	}
	// field 2: len=1, value=0
	assertBytes(t, out[26:30], []byte{0x00, 0x00, 0x00, 0x01}, "bool false len")
	if out[30] != 0x00 {
		t.Errorf("bool false byte = %x, want 0x00", out[30])
	}
}

func TestTextEncodingIsUTF8Bytes(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	enc.WriteRow([]loader.CopyValue{loader.CopyText{V: "hi"}}) //nolint:errcheck
	out := enc.Finish()
	assertBytes(t, out[19:21], []byte{0x00, 0x01}, "field count")
	assertBytes(t, out[21:25], []byte{0x00, 0x00, 0x00, 0x02}, "text length")
	assertBytes(t, out[25:27], []byte{'h', 'i'}, "text bytes")
}

func TestInt64Encoding(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	enc.WriteRow([]loader.CopyValue{loader.CopyInt64{V: 1}}) //nolint:errcheck
	out := enc.Finish()
	assertBytes(t, out[21:25], []byte{0x00, 0x00, 0x00, 0x08}, "int64 length")
	assertBytes(t, out[25:33], []byte{0, 0, 0, 0, 0, 0, 0, 1}, "int64 value")
}

func TestArityMismatchIsRejected(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(2)
	if err := enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 1}}); err == nil {
		t.Error("arity mismatch must return error")
	}
}

func TestRowsWrittenCountsCorrectly(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(1)
	enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 1}}) //nolint:errcheck
	enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 2}}) //nolint:errcheck
	if enc.RowsWritten() != 2 {
		t.Errorf("RowsWritten() = %d, want 2", enc.RowsWritten())
	}
}

func TestMultiRowRoundtripStructure(t *testing.T) {
	enc := loader.NewBinaryCopyEncoder(2)
	enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 1}, loader.CopyText{V: "a"}}) //nolint:errcheck
	enc.WriteRow([]loader.CopyValue{loader.CopyInt32{V: 2}, loader.CopyNull{}})        //nolint:errcheck
	rows := enc.RowsWritten()
	out := enc.Finish()
	if string(out[:11]) != string(pgSignature) {
		t.Error("header signature must be present")
	}
	n := len(out)
	if out[n-2] != 0xFF || out[n-1] != 0xFF {
		t.Error("trailer must be present at end")
	}
	if rows != 2 {
		t.Errorf("RowsWritten = %d, want 2", rows)
	}
}

func assertBytes(t *testing.T, got, want []byte, label string) {
	t.Helper()
	if len(got) != len(want) {
		t.Errorf("%s: len=%d, want %d", label, len(got), len(want))
		return
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("%s[%d] = %02x, want %02x", label, i, got[i], want[i])
		}
	}
}
