// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package secrets

import (
	"crypto/sha256"
	"encoding/base64"
	"fmt"
	"strings"

	"github.com/fernet/fernet-go"
	"golang.org/x/crypto/pbkdf2"
)

const pbkdf2Iterations = 600000

// DecryptMigrationSecret decrypts a password stored by Python SecretsManager.
// Supports legacy (salt:token), v1:, and v2: formats.
func DecryptMigrationSecret(masterKey, ciphertext string) (string, error) {
	if masterKey == "" {
		return "", fmt.Errorf("MIGRATION_MASTER_KEY is required to decrypt connection passwords")
	}
	if ciphertext == "" {
		return "", fmt.Errorf("empty ciphertext")
	}
	switch {
	case strings.HasPrefix(ciphertext, "v2:"):
		rest := strings.TrimPrefix(ciphertext, "v2:")
		parts := strings.SplitN(rest, ":", 3)
		if len(parts) != 3 {
			return "", fmt.Errorf("invalid v2 ciphertext format")
		}
		return decryptTokenWithSalt(masterKey, parts[1], parts[2])
	case strings.HasPrefix(ciphertext, "v1:"):
		return decryptLegacyPayload(masterKey, strings.TrimPrefix(ciphertext, "v1:"))
	default:
		return decryptLegacyPayload(masterKey, ciphertext)
	}
}

func decryptLegacyPayload(masterKey, payload string) (string, error) {
	idx := strings.Index(payload, ":")
	if idx <= 0 {
		return "", fmt.Errorf("invalid legacy ciphertext format")
	}
	return decryptTokenWithSalt(masterKey, payload[:idx], payload[idx+1:])
}

func decryptTokenWithSalt(masterKey, saltB64, token string) (string, error) {
	salt, err := base64.URLEncoding.DecodeString(saltB64)
	if err != nil {
		return "", fmt.Errorf("decode salt: %w", err)
	}
	derived := pbkdf2.Key([]byte(masterKey), salt, pbkdf2Iterations, 32, sha256.New)
	keyStr := base64.URLEncoding.EncodeToString(derived)
	keys, err := fernet.DecodeKeys(keyStr)
	if err != nil {
		return "", fmt.Errorf("decode fernet key: %w", err)
	}
	plain := fernet.VerifyAndDecrypt([]byte(token), 0, keys)
	if plain == nil {
		return "", fmt.Errorf("fernet decrypt failed")
	}
	return string(plain), nil
}
