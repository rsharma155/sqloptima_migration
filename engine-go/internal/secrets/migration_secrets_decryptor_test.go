// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package secrets

import "testing"

// Vectors produced by Python SecretsManager (shared/security/secrets_manager.py).
const (
	testMasterKey = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
	testPlaintext = "secret-password"

	// sm.encrypt("secret-password")
	testLegacyCiphertext = "LCYF_WBTSWWt6w1GcHSF4Q==:gAAAAABqJCZL0mVobJnknl3bB56LXEEA0_F67S55kIpIKES-dDmHkr4-BAUHCP3enHlLaH5-xfZUWLBVC9o8Gsxtjk6ILMPfLA=="

	// sm.encrypt_v2("secret-password")
	testV2Ciphertext = "v2:current:4vhwfMRCF1i__Zk1TZXIcg==:gAAAAABqJCZLemNC2hinOGUhhM6N3i9eTxIKdlxCx6D2xag8d32lWotIpdoQncwMKvpRYyfKGT0qJ5lZaSa402VqsqkKcJSJVA=="
)

func TestDecryptMigrationSecret_legacyPythonFormat(t *testing.T) {
	got, err := DecryptMigrationSecret(testMasterKey, testLegacyCiphertext)
	if err != nil {
		t.Fatalf("legacy decrypt: %v", err)
	}
	if got != testPlaintext {
		t.Fatalf("got %q want %q", got, testPlaintext)
	}
}

func TestDecryptMigrationSecret_v2PythonFormat(t *testing.T) {
	got, err := DecryptMigrationSecret(testMasterKey, testV2Ciphertext)
	if err != nil {
		t.Fatalf("v2 decrypt: %v", err)
	}
	if got != testPlaintext {
		t.Fatalf("got %q want %q", got, testPlaintext)
	}
}

func TestDecryptMigrationSecret_requiresMasterKey(t *testing.T) {
	_, err := DecryptMigrationSecret("", testLegacyCiphertext)
	if err == nil {
		t.Fatal("expected error for empty master key")
	}
}
