// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package metadata

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/ravisharma/sql-optima/engine-go/internal/core"
)

// CommandPoller checks for pending commands using two complementary strategies:
//  1. LISTEN/NOTIFY — sub-millisecond delivery when PostgreSQL sends NOTIFY.
//  2. Direct SELECT  — fallback poll used before each chunk to guarantee
//     no command is missed if a NOTIFY is dropped during a network hiccup.
//
// This dual-path mirrors the Rust CommandPoller exactly.
type CommandPoller struct {
	client           *Client
	fallbackInterval time.Duration
}

// NewCommandPoller creates a poller with a 500 ms fallback interval.
func NewCommandPoller(c *Client) *CommandPoller {
	return &CommandPoller{client: c, fallbackInterval: 500 * time.Millisecond}
}

// WithInterval overrides the fallback poll interval. Useful in tests.
func (p *CommandPoller) WithInterval(d time.Duration) *CommandPoller {
	p.fallbackInterval = d
	return p
}

// PollOnce performs a direct DB read for the current command for jobID.
// Returns ("", false, nil) when no command is pending.
func (p *CommandPoller) PollOnce(ctx context.Context, jobID uuid.UUID) (core.Command, bool, error) {
	return p.client.GetCommand(ctx, jobID)
}

// Ack marks the current command as acknowledged.
func (p *CommandPoller) Ack(ctx context.Context, jobID uuid.UUID) error {
	return p.client.AckCommand(ctx, jobID)
}

// ListenSQL returns a LISTEN statement for a known metadata channel.
// Channel names are allow-listed so they are never interpolated from user input.
func ListenSQL(channel string) (string, error) {
	switch channel {
	case "migration_commands", "transfer_commands":
		return "LISTEN " + channel, nil
	default:
		return "", fmt.Errorf("unsupported listen channel %q", channel)
	}
}

// ListenLoop starts a PostgreSQL LISTEN loop on the "migration_commands" channel
// and calls onNotify each time a notification arrives. It runs until ctx is
// cancelled. Reconnects automatically on transient errors.
//
// This is the real-time delivery path; PollOnce is the authoritative fallback.
func (p *CommandPoller) ListenLoop(ctx context.Context, connStr string, onNotify func()) error {
	return p.ListenLoopOn(ctx, connStr, "migration_commands", onNotify)
}

// ListenLoopOn LISTENs on a named PostgreSQL channel (migration_commands or transfer_commands).
func (p *CommandPoller) ListenLoopOn(ctx context.Context, connStr, channel string, onNotify func()) error {
	for {
		if err := ctx.Err(); err != nil {
			return nil
		}
		if err := p.listenOnce(ctx, connStr, channel, onNotify); err != nil {
			if ctx.Err() != nil {
				return nil
			}
			select {
			case <-time.After(p.fallbackInterval):
			case <-ctx.Done():
				return nil
			}
		}
	}
}

func (p *CommandPoller) listenOnce(ctx context.Context, connStr, channel string, onNotify func()) error {
	listenSQL, err := ListenSQL(channel)
	if err != nil {
		return err
	}

	conn, err := pgx.Connect(ctx, connStr)
	if err != nil {
		return err
	}
	defer conn.Close(ctx)

	if _, err = conn.Exec(ctx, listenSQL); err != nil {
		return err
	}

	for {
		// 500 ms timeout keeps the loop responsive to context cancellation.
		waitCtx, cancel := context.WithTimeout(ctx, p.fallbackInterval)
		_, err := conn.WaitForNotification(waitCtx)
		cancel()

		if ctx.Err() != nil {
			return nil
		}
		if err == nil {
			// Real notification arrived — invoke the callback so the main loop
			// can call PollOnce to read the actual command.
			onNotify()
		}
		// Timeout (context.DeadlineExceeded from waitCtx) is normal; continue.
	}
}
