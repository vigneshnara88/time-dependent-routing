import heapq
import json
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from math import isfinite


EPS = 1e-9


def _coord(value):
    return tuple(value)


def _parse_time(value):
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    stamp = datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp


def _format_time(value):
    text = value.isoformat()
    if text.endswith("+00:00"):
        text = text[:-6] + "Z"
    return text


def _json_number(value):
    rounded = round(value)
    if abs(value - rounded) <= 1e-7:
        return int(rounded)
    return round(value, 6)


class Timeline:
    __slots__ = ("points", "factors")

    def __init__(self, windows):
        events = defaultdict(lambda: {"start": [], "end": []})
        for window_id, (start, end, factor) in enumerate(windows):
            events[start]["start"].append((factor, window_id))
            events[end]["end"].append(window_id)

        self.points = sorted(events)
        self.factors = []
        active = []
        ended = set()

        for point in self.points:
            for window_id in events[point]["end"]:
                ended.add(window_id)
            for factor, window_id in events[point]["start"]:
                heapq.heappush(active, (factor, window_id))
            while active and active[0][1] in ended:
                heapq.heappop(active)

            self.factors.append(active[0][0] if active else 1.0)

    def query(self, moment):
        index = bisect_right(self.points, moment) - 1
        if index < 0:
            return 1.0, self.points[0] if self.points else None

        next_point = self.points[index + 1] if index + 1 < len(self.points) else None
        return self.factors[index], next_point


_CLEAR_TIMELINE = Timeline([])


def _arrival_after(base_duration, timeline, depart):
    if not timeline.points:
        return depart + base_duration

    factor, _ = timeline.query(depart)
    if factor <= 0:
        return None
    if base_duration == 0:
        return depart

    remaining = float(base_duration)
    moment = float(depart)

    while remaining > EPS:
        factor, next_point = timeline.query(moment)

        if factor <= 0:
            if next_point is None:
                return None
            moment = next_point
            continue

        if next_point is None:
            return moment + remaining / factor

        span = next_point - moment
        progress = span * factor
        if progress + EPS >= remaining:
            return moment + remaining / factor

        remaining -= progress
        moment = next_point

    return moment


def _static_shortest_paths(adjacency, end):
    distances = defaultdict(lambda: float("inf"))
    parent = {}
    distances[end] = 0.0
    heap = [(0.0, end)]

    while heap:
        distance, node = heapq.heappop(heap)
        if distance > distances[node] + EPS:
            continue

        for edge in adjacency.get(node, ()):
            nxt = edge["to"]
            candidate = distance + edge["base_duration"]
            if candidate + EPS < distances[nxt]:
                distances[nxt] = candidate
                parent[nxt] = (edge["edge_id"], node)
                heapq.heappush(heap, (candidate, nxt))

    return distances, parent


def _static_path(parent, start, end):
    path = []
    node = start
    seen = set()

    while node != end:
        if node in seen or node not in parent:
            return None
        seen.add(node)
        edge_id, node = parent[node]
        path.append(edge_id)

    return path


def _trace_path(trace, index):
    path = []
    while index > 0:
        index, edge_id = trace[index]
        path.append(edge_id)
    path.reverse()
    return path


def _unreachable():
    return json.dumps({"total_duration_sec": None, "arrival_time": None, "path": []})


def solve(data: str) -> str:
    request = json.loads(data)

    start = _coord(request["start_coordinate"])
    end = _coord(request["end_coordinate"])
    start_dt = _parse_time(request["start_time"])

    if start == end:
        return json.dumps(
            {
                "total_duration_sec": 0,
                "arrival_time": _format_time(start_dt),
                "path": [],
            }
        )

    adjacency = defaultdict(list)
    for order, edge in enumerate(request.get("edges") or ()):
        node1 = _coord(edge["node1"])
        node2 = _coord(edge["node2"])
        base_duration = float(edge["base_duration_sec"])
        edge_id = edge["edge_id"]

        adjacency[node1].append(
            {
                "edge_id": edge_id,
                "from": node1,
                "to": node2,
                "base_duration": base_duration,
                "order": order,
            }
        )
        adjacency[node2].append(
            {
                "edge_id": edge_id,
                "from": node2,
                "to": node1,
                "base_duration": base_duration,
                "order": order,
            }
        )

    for edges in adjacency.values():
        edges.sort(key=lambda edge: (edge["order"], edge["edge_id"], edge["to"]))

    windows = defaultdict(list)
    horizon = 0.0
    fastest_factor = 1.0

    for obstruction in request.get("obstructions") or ():
        obs_start = (_parse_time(obstruction["start_time"]) - start_dt).total_seconds()
        obs_end = (_parse_time(obstruction["end_time"]) - start_dt).total_seconds()
        if obs_end <= obs_start:
            continue

        factor = float(obstruction["speed_factor"])
        key = (
            obstruction["edge_id"],
            _coord(obstruction["edge"]["from"]),
            _coord(obstruction["edge"]["to"]),
        )
        windows[key].append((float(obs_start), float(obs_end), factor))
        horizon = max(horizon, float(obs_end))
        fastest_factor = max(fastest_factor, factor)

    timelines = {key: Timeline(entries) for key, entries in windows.items()}
    for edges in adjacency.values():
        for edge in edges:
            edge["timeline"] = timelines.get(
                (edge["edge_id"], edge["from"], edge["to"]),
                _CLEAR_TIMELINE,
            )

    static_distances, static_parent = _static_shortest_paths(adjacency, end)
    if not isfinite(static_distances[start]):
        return _unreachable()

    def lower_bound(node):
        return static_distances[node] / fastest_factor

    trace = [(-1, None)]
    heap = [(lower_bound(start), 0.0, 0, start, 0)]
    counter = 1
    seen_times = defaultdict(set)
    static_seen = {}
    best_arrival = None
    best_path = None

    while heap:
        estimate, elapsed, _, node, trace_index = heapq.heappop(heap)

        if best_arrival is not None and estimate >= best_arrival - EPS:
            break

        time_key = round(elapsed, 9)
        if time_key in seen_times[node]:
            continue
        seen_times[node].add(time_key)

        if node == end:
            best_arrival = elapsed
            best_path = _trace_path(trace, trace_index)
            break

        if elapsed >= horizon - EPS:
            previous = static_seen.get(node)
            if previous is not None and elapsed >= previous - EPS:
                continue
            static_seen[node] = elapsed

            suffix = _static_path(static_parent, node, end)
            if suffix is not None:
                candidate = elapsed + static_distances[node]
                if best_arrival is None or candidate < best_arrival - EPS:
                    best_arrival = candidate
                    best_path = _trace_path(trace, trace_index) + suffix
            continue

        for edge in adjacency.get(node, ()):
            if not isfinite(static_distances[edge["to"]]):
                continue

            arrival = _arrival_after(edge["base_duration"], edge["timeline"], elapsed)
            if arrival is None or arrival < elapsed - EPS:
                continue

            estimate_next = arrival + lower_bound(edge["to"])
            if best_arrival is not None and estimate_next >= best_arrival - EPS:
                continue

            trace.append((trace_index, edge["edge_id"]))
            heapq.heappush(
                heap,
                (estimate_next, arrival, counter, edge["to"], len(trace) - 1),
            )
            counter += 1

    if best_arrival is None:
        return _unreachable()

    duration = _json_number(best_arrival)
    return json.dumps(
        {
            "total_duration_sec": duration,
            "arrival_time": _format_time(start_dt + timedelta(seconds=duration)),
            "path": best_path,
        }
    )


if __name__ == "__main__":
    import sys

    print(solve(sys.stdin.read()))
