 # Samia Experiment Summary

## Objective

Evaluate how `connection-only` and `continuous` authorization modes behave when project access is revoked while a WebSocket connection is active.

## Experiment Configuration

Six experiments were conducted using Project Red (project ID 1). The authorization modes were tested with cutoff intervals of 1, 5, and 10 seconds.

## Experiment Results

| Experiment | Authorization Mode | Cutoff (seconds) | Execution Status | Result |
|---:|---|---:|---|---|
| 1 | `connection-only` | 1 | Completed | **FAIL** |
| 2 | `continuous` | 1 | Completed | **PASS** |
| 3 | `connection-only` | 5 | Completed | **FAIL** |
| 4 | `continuous` | 5 | Completed | **PASS** |
| 5 | `connection-only` | 10 | Completed | **FAIL** |
| 6 | `continuous` | 10 | Completed | **PASS** |

All six experiments completed successfully at the execution level, with one attempt each and no reported execution errors. The `result` field represents the experiment outcome, not whether the experiment itself executed successfully.

## Overall Outcome

| Authorization Mode | Passed | Failed |
|---|---:|---:|
| `connection-only` | 0 | 3 |
| `continuous` | 3 | 0 |
| **Total** | **3** | **3** |

## Observations

- In all three `connection-only` experiments, the WebSocket observed a private message created after access was revoked.
- In all three `continuous` experiments, the WebSocket observed an `access_revoked` event indicating that project access had been removed.
- The same result pattern occurred at all tested cutoff intervals: 1, 5, and 10 seconds.
- All six experiments recorded a `cleanup_completed` event confirming that Alice's access was restored with HTTP 200.

## Conclusion

In these six runs, `connection-only` authorization did not prevent the active WebSocket from receiving private message content after access revocation. The `continuous` mode instead reported the access revocation and did not expose the private message content in the recorded WebSocket observation.

The results support continuous authorization checks for this tested revocation scenario. They describe the observed behavior of these experiments and do not establish a guarantee for every possible configuration or runtime condition.

## Evidence

The combined experiment responses, including configuration, timestamps, results, and event logs, are stored in `experiment-results.json`.