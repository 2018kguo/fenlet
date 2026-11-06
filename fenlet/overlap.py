"""Exact overlap counts and affected windows without enumerating quadratic output.

A sweep counts active Y intervals with Fenwick trees. A max-end segment tree
marks previously untouched intervals; each interval leaves that tree once.
Diagnostic examples are capped, so dense stacks cannot allocate N-squared pairs.
Time: O(N log N + B*N), memory: O(N), where B is the fixed example limit.
"""
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
import heapq
import math


@dataclass(frozen=True)
class Overlaps:
    count: int
    affected: frozenset
    examples: tuple


class Fenwick:
    def __init__(self, size):
        self.values = [0] * (size + 1)

    def add(self, index, delta):
        index += 1
        while index < len(self.values):
            self.values[index] += delta
            index += index & -index

    def before(self, exclusive):
        total = 0
        while exclusive:
            total += self.values[exclusive]
            exclusive -= exclusive & -exclusive
        return total


class UnmarkedIntervals:
    def __init__(self, size):
        self.size = 1 << (max(1, size) - 1).bit_length()
        self.tree = [-math.inf] * (self.size * 2)
        self.heaps = [[] for _ in range(size)]
        self.live = set()
        self.positions = {}

    def refresh(self, position):
        heap = self.heaps[position]
        while heap and heap[0][1] not in self.live:
            heapq.heappop(heap)
        node = self.size + position
        self.tree[node] = -heap[0][0] if heap else -math.inf
        node //= 2
        while node:
            value = max(self.tree[node * 2], self.tree[node * 2 + 1])
            if self.tree[node] == value:
                break
            self.tree[node] = value
            node //= 2

    def add(self, index, position, end):
        self.live.add(index)
        self.positions[index] = position
        heapq.heappush(self.heaps[position], (-end, index))
        self.refresh(position)

    def remove(self, index):
        if index in self.live:
            self.live.remove(index)
            self.refresh(self.positions.pop(index))

    def find(self, exclusive_start, minimum_end):
        def visit(node, left, right):
            if left >= exclusive_start or self.tree[node] <= minimum_end:
                return None
            if right - left == 1:
                return self.heaps[left][0][1]
            middle = (left + right) // 2
            found = visit(node * 2, left, middle)
            return found if found is not None else visit(node * 2 + 1, middle, right)
        return visit(1, 0, self.size)


def analyze_overlaps(frames, example_limit=32):
    intervals, events = {}, []
    for i, b in enumerate(frames):
        if not all(math.isfinite(b[k]) for k in ("x", "y", "width", "height")) or b["width"] <= 0 or b["height"] <= 0:
            raise ValueError("Overlap verification needs finite positive rectangles.")
        if b["width"] <= 1 or b["height"] <= 1:
            continue
        # Shrinking each side by half a point preserves the one-point tolerance.
        left, right = b["x"] + .5, b["x"] + b["width"] - .5
        start, end = b["y"] + .5, b["y"] + b["height"] - .5
        if not all(math.isfinite(v) for v in (left, right, start, end)):
            raise ValueError("Rectangle extents must remain finite.")
        if right <= left or end <= start:
            continue
        intervals[i] = (start, end)
        events.extend(((left, 1, i), (right, 0, i)))
    if not intervals:
        return Overlaps(0, frozenset(), ())
    coordinates = sorted({v for interval in intervals.values() for v in interval})
    positions = {value: i for i, value in enumerate(coordinates)}
    starts, ends = Fenwick(len(coordinates)), Fenwick(len(coordinates))
    unmarked = UnmarkedIntervals(len(coordinates))
    active, affected, examples, count = {}, set(), [], 0
    for _, entering, index in sorted(events):
        start, end = intervals[index]
        if not entering:
            starts.add(positions[start], -1)
            ends.add(positions[end], -1)
            unmarked.remove(index)
            active.pop(index)
            continue
        upper = bisect_left(coordinates, end)
        matches = starts.before(upper) - ends.before(bisect_right(coordinates, start))
        count += matches
        if matches:
            affected.add(index)
            if len(examples) < example_limit:
                for other, (a, b) in active.items():
                    if a < end and b > start:
                        examples.append((other, index))
                        if len(examples) == example_limit:
                            break
            while True:
                other = unmarked.find(upper, start)
                if other is None:
                    break
                affected.add(other)
                unmarked.remove(other)
        else:
            unmarked.add(index, positions[start], end)
        starts.add(positions[start], 1)
        ends.add(positions[end], 1)
        active[index] = (start, end)
    return Overlaps(count, frozenset(affected), tuple(examples))
