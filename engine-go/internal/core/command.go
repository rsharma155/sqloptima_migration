// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package core

import "fmt"

// Command is an instruction issued by the Python control-plane API to the
// Go data-plane engine. Written to the metadata DB; read by the engine before
// each chunk operation.
type Command string

const (
	CommandStart  Command = "START"
	CommandPause  Command = "PAUSE"
	CommandResume Command = "RESUME"
	CommandStop   Command = "STOP"
	CommandCancel Command = "CANCEL"
)

// IsStop returns true for any command that should permanently halt the job.
func (c Command) IsStop() bool { return c == CommandStop || c == CommandCancel }

// IsPause returns true for commands that should temporarily suspend the job.
func (c Command) IsPause() bool { return c == CommandPause }

// String satisfies fmt.Stringer.
func (c Command) String() string { return string(c) }

// ParseCommand validates and parses a raw string from the metadata DB.
func ParseCommand(s string) (Command, error) {
	switch Command(s) {
	case CommandStart, CommandPause, CommandResume, CommandStop, CommandCancel:
		return Command(s), nil
	}
	return "", fmt.Errorf("unknown command %q", s)
}
