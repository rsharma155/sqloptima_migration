// Copyright (c) 2026 Ravi Sharma. MIT License.
// SPDX-License-Identifier: MIT

package transfer

import (
	"context"
	"fmt"
	"os/exec"
	"strconv"

	"github.com/ravisharma/sql-optima/engine-go/internal/extractor"
)

// TransferBCPRunner runs native bcp queryout / in. Tests inject a fake.
type TransferBCPRunner interface {
	QueryOut(ctx context.Context, cfg extractor.SQLServerConfig, query, outFile string) error
	BulkIn(ctx context.Context, cfg extractor.SQLServerConfig, dest, inFile string, batch int, keepIdentity bool) error
}

type execBCPRunner struct {
	bin string
}

func newExecBCPRunner() (TransferBCPRunner, error) {
	bin, err := exec.LookPath("bcp")
	if err != nil {
		return nil, fmt.Errorf("bcp not found on PATH: %w", err)
	}
	return &execBCPRunner{bin: bin}, nil
}

func bcpServerAddr(host string, port int) string {
	if port <= 0 {
		return host
	}
	return host + "," + strconv.Itoa(port)
}

func (r *execBCPRunner) QueryOut(ctx context.Context, cfg extractor.SQLServerConfig, query, outFile string) error {
	args := []string{
		query, "queryout", outFile,
		"-n",
		"-S", bcpServerAddr(cfg.Host, cfg.Port),
		"-U", cfg.User,
		"-P", cfg.Password,
		"-q",
	}
	cmd := exec.CommandContext(ctx, r.bin, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("bcp queryout: %w: %s", err, string(out))
	}
	return nil
}

func (r *execBCPRunner) BulkIn(
	ctx context.Context, cfg extractor.SQLServerConfig, dest, inFile string, batch int, keepIdentity bool,
) error {
	if batch < 1 {
		batch = 10000
	}
	args := []string{
		dest, "in", inFile,
		"-n",
		"-b", strconv.Itoa(batch),
		"-S", bcpServerAddr(cfg.Host, cfg.Port),
		"-U", cfg.User,
		"-P", cfg.Password,
		"-q",
	}
	if keepIdentity {
		args = append(args, "-E")
	}
	cmd := exec.CommandContext(ctx, r.bin, args...)
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("bcp in: %w: %s", err, string(out))
	}
	return nil
}

func bcpDestName(database, schema, table string) string {
	return database + "." + schema + "." + table
}
