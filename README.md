# Time-dependent routing

A Python graph-routing exercise for finding an early arrival when road conditions change during a journey. Edges are bidirectional, obstructions are directional, and a traversal can cross several speed windows.

The distinctive constraint is that a traveller cannot wait at a node. Returning to a node later through a cycle can therefore lead to a different continuation. The solver keeps multiple arrival-time states instead of retaining only one arrival per node.

## The question behind the solver

A shortest route on a map is not always the fastest journey at a particular departure time. A road may slow down, become blocked or recover while the traveller is already moving. The relevant question is therefore: **which sequence of roads gets us to the destination earliest, given when each road will be entered and how its conditions change during traversal?**

The problem becomes especially interesting when waiting at intersections is disallowed. In a conventional shortest-path search, reaching a node earlier often allows later arrivals to be discarded. Here, an early arrival may encounter an entry block, while returning to the same node through a cycle at a later time can permit a different onward route. The solver therefore searches over both location and elapsed time.

This is useful for understanding the assumptions behind routing algorithms. The rules about waiting, direction and when an obstruction affects a journey determine which search states matter; changing those rules changes the problem being solved.

## A road journey as a timeline

Each edge starts with a base traversal duration. Time windows apply speed factors to a particular direction of that edge. The traversal routine tracks how much of the base journey remains and advances through each boundary at which the applicable factor changes.

As an illustration, a road whose unconstrained traversal takes one minute need not take two minutes just because its speed is halved at entry. If the slow window ends partway through the trip, the remaining portion is completed at the restored speed. Conversely, a new obstruction can affect a journey already in progress. Evaluating the condition only at departure would miss these changes.

The implementation distinguishes a blocked entry from a block encountered after entry: the former prevents starting that traversal, while the latter pauses progress on the edge until movement becomes possible. The returned path records the chosen edge sequence, including repeated edges if the selected journey uses a cycle.

## Interface

The implementation uses only the Python standard library. Its main interface accepts and returns JSON strings:

```python
import json
from main import solve

request = {
    "start_coordinate": [0, 0],
    "end_coordinate": [1, 0],
    "start_time": "2026-01-01T09:00:00Z",
    "edges": [
        {
            "edge_id": "road_a",
            "node1": [0, 0],
            "node2": [1, 0],
            "base_duration_sec": 60,
        }
    ],
    "obstructions": [],
}
result = json.loads(solve(json.dumps(request)))
```

This is an illustrative input, not a saved test or benchmark. Python 3.10 or newer is a practical starting environment; no third-party dependencies are needed.

The script also reads one JSON request from standard input and writes one JSON response:

```powershell
Get-Content -Raw request.json | python main.py
```

## Input model

| Field | Meaning |
| --- | --- |
| `start_coordinate`, `end_coordinate` | Node identifiers represented as coordinate arrays. Coordinates identify nodes; they are not converted to geographic distances. |
| `start_time` | ISO-format departure timestamp. A trailing `Z` denotes UTC; timestamps without an offset are treated as UTC. |
| `edges` | Objects containing `edge_id`, `node1`, `node2`, and `base_duration_sec`. Each creates both traversal directions. |
| `obstructions` | Time windows with `edge_id`, an `edge` object containing `from` and `to`, `start_time`, `end_time`, and `speed_factor`. |

An optional `nodes` field is not used: the solver builds connectivity from edge endpoints. Supply finite, nonnegative durations and speed factors, consistent node identifiers, and unambiguous edge IDs. The current interface assumes a well-formed request and does not provide full schema validation.

An obstruction's edge ID and direction must both match the traversal. Windows are half-open: the start is included and the end is excluded. Invalid windows whose end is not later than their start are ignored.

`speed_factor` scales progress relative to the base speed: 0.5 halves speed, 1 leaves it unchanged, and values above 1 speed up traversal. When several windows overlap, the smallest active factor applies. With no active window the factor is 1.

## Algorithm

1. Compile each directed edge's windows into a piecewise-constant timeline using a heap of active factors.
2. Compute static shortest-path distances from the destination using base durations.
3. Use those distances, divided by the largest speed factor, as a lower bound in an A*-style search over `(node, elapsed_time)` states.
4. Integrate progress across timeline changes when traversing an edge and retain back-pointers for path recovery.
5. Once every obstruction has ended, complete a candidate route using the static shortest-path suffix.

The search does not add waiting actions at nodes. Entry is blocked when the current factor is zero. If an edge becomes blocked after traversal begins, the implementation pauses progress on that edge until a later boundary permits movement. A zero-duration edge is also subject to the entry-block rule.

## Output

The response contains:

- `total_duration_sec`: the selected journey duration, rounded for JSON output.
- `arrival_time`: the departure timestamp plus that duration, preserving its timezone offset.
- `path`: edge IDs in traversal order; an edge may occur more than once.

If the destination is unreachable under the implemented rules, duration and arrival are `null` and the path is empty. If start and destination are identical, duration is zero and the path is empty.

## Scope

The implementation is a graph algorithm exercise, with no map service, live traffic feed, customer data, or organizational integration. Floating-point time comparisons use a tolerance, repeated-state keys are rounded, and final noninteger durations are rounded to six decimal places. Those choices can matter near time-window boundaries.

Short cycles and a long obstruction horizon can create many arrival-time states; there is no general bound on practical runtime or memory usage stated here. No performance ranking, benchmark numbers, or correctness-validation claim is included.

The retained source carries no license notice. No new license or corporate affiliation is asserted. Reference exercise documents, PDF-derived fixtures, and development timing notes are not distributed with this repository.
