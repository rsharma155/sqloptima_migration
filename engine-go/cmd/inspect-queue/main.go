// One-off diagnostic: list bbolt chunk statuses for a job ID.
package main

import (
	"encoding/json"
	"fmt"
	"os"

	"github.com/google/uuid"

	"github.com/ravisharma/sql-optima/engine-go/internal/core"
	"github.com/ravisharma/sql-optima/engine-go/internal/queue"
)

func main() {
	path := "/Users/ravisharma/MyStuff/AI_Code/sql_optima/sqlserver_to_postgres/data/migration_queue.bbolt"
	if len(os.Args) > 1 {
		path = os.Args[1]
	}
	jidStr := "41468e4c-af13-479a-9182-db1e1b94d435"
	if len(os.Args) > 2 {
		jidStr = os.Args[2]
	}
	q, err := queue.Open(path)
	if err != nil {
		panic(err)
	}
	defer q.Close()
	jid, err := uuid.Parse(jidStr)
	if err != nil {
		panic(err)
	}
	for _, st := range []core.ChunkStatus{
		core.ChunkStatusPending, core.ChunkStatusClaimed, core.ChunkStatusExtracting,
		core.ChunkStatusExtracted, core.ChunkStatusLoading, core.ChunkStatusLoaded,
		core.ChunkStatusFailed, core.ChunkStatusRetrying,
	} {
		chunks, err := q.ListChunksByStatus(jid, st)
		if err != nil {
			fmt.Println("err", st, err)
			continue
		}
		if len(chunks) == 0 {
			continue
		}
		fmt.Printf("status=%s count=%d\n", st, len(chunks))
		limit := len(chunks)
		if limit > 3 {
			limit = 3
		}
		for i := 0; i < limit; i++ {
			b, _ := json.Marshal(chunks[i])
			fmt.Printf("  %s\n", string(b))
		}
		if len(chunks) > 3 {
			fmt.Printf("  ... +%d more\n", len(chunks)-3)
		}
	}
}
