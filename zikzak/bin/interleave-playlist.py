#!/usr/bin/env python3
"""
Round-robin interleave playlist paths by top-level media category.
Reads absolute paths from stdin (one per line), writes interleaved result to stdout.
Prevents clusters of the same category by cycling across categories.
"""
import sys, random, collections

lines = sys.stdin.read().splitlines()
lines = [l for l in lines if l.strip()]

buckets = collections.defaultdict(list)
for line in lines:
    parts = line.split('/')
    # /mnt/media/<cat>/... → parts[3] is the top-level category
    cat = parts[3] if len(parts) > 3 else '__other__'
    buckets[cat].append(line)

for v in buckets.values():
    random.shuffle(v)

keys = list(buckets.keys())
random.shuffle(keys)

result = []
while any(buckets[k] for k in keys):
    for k in keys:
        if buckets[k]:
            result.append(buckets[k].pop())

print('\n'.join(result))
