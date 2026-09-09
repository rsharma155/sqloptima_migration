// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package extractport

import (
	"fmt"
	"strings"
)

func sanitizeDDLFragment(fragment, kind string) (string, error) {
	trimmed := strings.TrimSpace(fragment)
	if trimmed == "" {
		return "", fmt.Errorf("%s definition is empty", kind)
	}
	if strings.Contains(trimmed, ";") {
		return "", fmt.Errorf("%s definition must not contain a statement separator", kind)
	}
	return trimmed, nil
}

func BuildPostgresDropConstraint(schema, table, name string) string {
	return fmt.Sprintf("ALTER TABLE %s DROP CONSTRAINT %s", quotedTablePG(schema, table), quoteIdentPG(name))
}

func BuildPostgresAddConstraint(schema, table, name, definition string) (string, error) {
	def, err := sanitizeDDLFragment(definition, "constraint")
	if err != nil {
		return "", err
	}
	upper := strings.ToUpper(def)
	if !strings.HasPrefix(upper, "FOREIGN KEY") &&
		!strings.HasPrefix(upper, "CHECK") &&
		!strings.HasPrefix(upper, "UNIQUE") &&
		!strings.HasPrefix(upper, "PRIMARY KEY") &&
		!strings.HasPrefix(upper, "EXCLUDE") {
		return "", fmt.Errorf("constraint definition must be FOREIGN KEY, CHECK, UNIQUE, PRIMARY KEY, or EXCLUDE")
	}
	return fmt.Sprintf("ALTER TABLE %s ADD CONSTRAINT %s %s", quotedTablePG(schema, table), quoteIdentPG(name), def), nil
}

func BuildPostgresDropIndex(schema, name string) string {
	return fmt.Sprintf("DROP INDEX IF EXISTS %s.%s", quoteIdentPG(schema), quoteIdentPG(name))
}

func BuildPostgresCreateIndex(definition string) (string, error) {
	def, err := sanitizeDDLFragment(definition, "index")
	if err != nil {
		return "", err
	}
	if !strings.HasPrefix(strings.ToUpper(def), "CREATE ") {
		return "", fmt.Errorf("index restore SQL must be a CREATE statement")
	}
	return def, nil
}

func BuildPostgresDisableTrigger(schema, table, name string) string {
	return fmt.Sprintf("ALTER TABLE %s DISABLE TRIGGER %s", quotedTablePG(schema, table), quoteIdentPG(name))
}

func BuildPostgresEnableTrigger(schema, table, name string) string {
	return fmt.Sprintf("ALTER TABLE %s ENABLE TRIGGER %s", quotedTablePG(schema, table), quoteIdentPG(name))
}

func BuildMSSQLNoCheckConstraint(schema, table, name string) string {
	return fmt.Sprintf("ALTER TABLE %s NOCHECK CONSTRAINT %s", quotedTableMSSQL(schema, table), quoteIdentMSSQL(name))
}

func BuildMSSQLCheckConstraint(schema, table, name string) string {
	return fmt.Sprintf("ALTER TABLE %s WITH CHECK CHECK CONSTRAINT %s", quotedTableMSSQL(schema, table), quoteIdentMSSQL(name))
}

func BuildMSSQLDisableIndex(schema, table, name string) string {
	return fmt.Sprintf("ALTER INDEX %s ON %s DISABLE", quoteIdentMSSQL(name), quotedTableMSSQL(schema, table))
}

func BuildMSSQLRebuildIndex(schema, table, name string) string {
	return fmt.Sprintf("ALTER INDEX %s ON %s REBUILD", quoteIdentMSSQL(name), quotedTableMSSQL(schema, table))
}

func BuildMSSQLDisableTrigger(schema, table, name string) string {
	return fmt.Sprintf("DISABLE TRIGGER %s ON %s", quoteIdentMSSQL(name), quotedTableMSSQL(schema, table))
}

func BuildMSSQLEnableTrigger(schema, table, name string) string {
	return fmt.Sprintf("ENABLE TRIGGER %s ON %s", quoteIdentMSSQL(name), quotedTableMSSQL(schema, table))
}
