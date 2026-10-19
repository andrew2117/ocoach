# Competitive Programming Notes: Segment Trees & Fenwick Trees

This guide covers two of the most important range-query data structures in
competitive programming: **Segment Trees** and **Fenwick Trees (Binary
Indexed Trees)**. Both support efficient range queries and point/range
updates over an array, but they differ in flexibility, constant factor, and
implementation complexity.

## Segment Trees

### Overview

A segment tree is a binary tree built over an array of size `n` where each
node represents a range `[l, r]` of the array and stores an aggregate value
(sum, min, max, gcd, etc.) over that range. The root covers the whole array
`[0, n-1]`, and each node's children split its range roughly in half.

- Build: `O(n)`
- Point update: `O(log n)`
- Range query: `O(log n)`
- Range update (with lazy propagation): `O(log n)`
- Space: `O(4n)` (safe upper bound for an array-based implementation)

Segment trees are the go-to structure when you need **arbitrary associative
range queries** (sum, min, max, gcd, xor, ...) combined with point or range
updates, or when you need more complex per-node state (e.g. counts, hashes,
Kadane's max-subarray, merge-sort-tree style structures).

### Iterative array-based implementation (sum, point update)

```cpp
struct SegTree {
    int n;
    vector<long long> tree;

    SegTree(int n_) : n(n_), tree(2 * n_, 0) {}

    void build(vector<long long>& arr) {
        for (int i = 0; i < n; i++) tree[n + i] = arr[i];
        for (int i = n - 1; i > 0; i--) tree[i] = tree[2 * i] + tree[2 * i + 1];
    }

    void update(int pos, long long value) {
        pos += n;
        tree[pos] = value;
        for (pos /= 2; pos >= 1; pos /= 2)
            tree[pos] = tree[2 * pos] + tree[2 * pos + 1];
    }

    // Sum over half-open range [l, r)
    long long query(int l, int r) {
        long long res = 0;
        for (l += n, r += n; l < r; l /= 2, r /= 2) {
            if (l & 1) res += tree[l++];
            if (r & 1) res += tree[--r];
        }
        return res;
    }
};
```

This "bottom-up" iterative form (popularized by AtCoder/USACO communities) is
compact and fast, but only supports commutative, invertible aggregates
cleanly for point updates. For range updates or non-commutative merges, use
the recursive top-down form below.

### Recursive top-down implementation with lazy propagation (range add, range sum)

```cpp
struct LazySegTree {
    int n;
    vector<long long> tree, lazy;

    LazySegTree(int n_) : n(n_), tree(4 * n_, 0), lazy(4 * n_, 0) {}

    void push_down(int node, int l, int r) {
        if (lazy[node] == 0) return;
        int mid = (l + r) / 2;
        apply(2 * node, l, mid, lazy[node]);
        apply(2 * node + 1, mid + 1, r, lazy[node]);
        lazy[node] = 0;
    }

    void apply(int node, int l, int r, long long val) {
        tree[node] += val * (r - l + 1);
        lazy[node] += val;
    }

    void update(int node, int l, int r, int ql, int qr, long long val) {
        if (qr < l || r < ql) return;
        if (ql <= l && r <= qr) { apply(node, l, r, val); return; }
        push_down(node, l, r);
        int mid = (l + r) / 2;
        update(2 * node, l, mid, ql, qr, val);
        update(2 * node + 1, mid + 1, r, ql, qr, val);
        tree[node] = tree[2 * node] + tree[2 * node + 1];
    }

    long long query(int node, int l, int r, int ql, int qr) {
        if (qr < l || r < ql) return 0;
        if (ql <= l && r <= qr) return tree[node];
        push_down(node, l, r);
        int mid = (l + r) / 2;
        return query(2 * node, l, mid, ql, qr) + query(2 * node + 1, mid + 1, r, ql, qr);
    }
};
```

**Key idea behind lazy propagation:** instead of eagerly pushing a pending
update down to every affected leaf (which would cost `O(n)`), a node stores
"I owe my children this update" in a `lazy` value, and only pushes it down
one level deeper the next time that subtree is actually visited. This keeps
both range updates and range queries at `O(log n)`.

### Common variants and use cases

- **Merge Sort Tree**: each node stores a sorted vector of its range, enabling
  offline "count elements ≤ x in range [l, r]" queries in `O(log^2 n)`.
- **Persistent Segment Tree**: keeps a version history of the tree so you can
  query any historical version — useful for "k-th smallest in range" with
  persistence, or rollback-style problems.
- **Segment Tree Beats (Ji Driver's segment tree)**: handles "chmin/chmax"
  range updates alongside range sum queries in amortized `O(log^2 n)`.
- **2D Segment Tree / Segment Tree of Merge Sort Trees**: for 2D range
  queries, at the cost of extra `log` factors or memory.

### Pitfalls

- Off-by-one errors on inclusive vs. half-open ranges are the #1 source of
  bugs — pick a convention (`[l, r)` or `[l, r]`) and stay consistent.
- Forgetting to `push_down` before recursing into children when lazy values
  are pending silently corrupts results without an obvious crash.
- Array size: the recursive form needs `4 * n` nodes as a safe bound (some
  use `2 * next_power_of_two(n)`).

## Fenwick Trees (Binary Indexed Trees)

### Overview

A Fenwick tree (BIT) is a compact array-based structure that supports prefix
sums (or any invertible, associative aggregate) with `O(log n)` point update
and `O(log n)` prefix query, using only `O(n)` space and a much smaller
constant factor than a segment tree. It exploits the binary representation of
indices: each index `i` is responsible for a range of size `i & (-i)` (the
value of its lowest set bit).

- Build: `O(n log n)` (naive) or `O(n)` (linear build trick)
- Point update: `O(log n)`
- Prefix sum query: `O(log n)`
- Range sum query (via two prefix queries): `O(log n)`
- Space: `O(n)`

Fenwick trees are preferred over segment trees whenever the problem only
needs **prefix sums / point updates** (or can be reduced to that), because
they are simpler to implement correctly and roughly 2-3x faster in practice
due to better cache locality and a smaller constant factor.

### Standard implementation (1-indexed, point update + prefix sum)

```cpp
struct Fenwick {
    int n;
    vector<long long> bit;

    Fenwick(int n_) : n(n_), bit(n_ + 1, 0) {}

    void update(int i, long long delta) {       // i is 1-indexed
        for (; i <= n; i += i & (-i))
            bit[i] += delta;
    }

    long long prefixSum(int i) {                 // sum of [1, i]
        long long res = 0;
        for (; i > 0; i -= i & (-i))
            res += bit[i];
        return res;
    }

    long long rangeSum(int l, int r) {            // sum of [l, r], inclusive, 1-indexed
        return prefixSum(r) - prefixSum(l - 1);
    }
};
```

The magic is in `i & (-i)`, which isolates the lowest set bit of `i`. Moving
"up" (`i += i & (-i)`) walks toward the root during updates; moving "down"
(`i -= i & (-i)`) walks toward index 0 during prefix queries.

### Range update, range query variant

To support range updates (add `delta` to every element in `[l, r]`) alongside
range sum queries, use **two Fenwick trees** representing a difference-array
trick:

```cpp
struct FenwickRangeUpdate {
    int n;
    Fenwick B1, B2; // B1 tracks the delta, B2 tracks delta * index correction

    FenwickRangeUpdate(int n_) : n(n_), B1(n_), B2(n_) {}

    void rangeAdd(int l, int r, long long delta) {
        B1.update(l, delta);
        B1.update(r + 1, -delta);
        B2.update(l, delta * (l - 1));
        B2.update(r + 1, -delta * r);
    }

    long long prefixSum(int i) {
        return B1.prefixSum(i) * i - B2.prefixSum(i);
    }

    long long rangeSum(int l, int r) {
        return prefixSum(r) - prefixSum(l - 1);
    }
};
```

### Fenwick tree as an implicit binary search structure

Because `prefixSum` is monotonic when all values are non-negative, a Fenwick
tree can binary-search for "the smallest index whose prefix sum is ≥ k" in
`O(log n)` using the same bit-trick traversal, without a separate binary
search over indices:

```cpp
int findKth(Fenwick& bit, long long k) {
    int pos = 0;
    for (int pw = highestPowerOfTwoLE(bit.n); pw > 0; pw >>= 1) {
        if (pos + pw <= bit.n && bit.bit[pos + pw] < k) {
            pos += pw;
            k -= bit.bit[pos];
        }
    }
    return pos + 1; // 1-indexed position of the k-th element
}
```

This pattern is extremely common for "k-th smallest remaining element" /
order-statistics problems (e.g. simulating deletions from a multiset while
supporting "find k-th smallest" queries).

### Pitfalls

- Fenwick trees are naturally 1-indexed; using index 0 breaks the `i & (-i)`
  trick (it loops forever, since `0 & (-0) == 0`).
- Fenwick trees only support aggregates with an inverse operation (sum, xor)
  — for min/max you need a segment tree instead (or a specialized "Fenwick
  tree for prefix min" that only supports prefix updates, not arbitrary point
  updates).

## Segment Tree vs. Fenwick Tree: When to Use Which

| Criterion | Segment Tree | Fenwick Tree |
|---|---|---|
| Supported aggregates | Any associative op (sum, min, max, gcd, ...) | Invertible ops only (sum, xor) |
| Range updates | Yes, with lazy propagation | Yes, via difference-array trick (sum only) |
| Implementation complexity | Higher | Lower |
| Constant factor / speed | Slower | ~2-3x faster |
| Memory | `O(4n)` typical | `O(n)` |
| Extra features | Merge sort tree, persistence, beats | Order-statistics via bit-trick binary search |

**Rule of thumb:** if the problem only needs prefix/range sums with point
updates, reach for a Fenwick tree first — it's less code and less likely to
have bugs. Switch to a segment tree the moment you need min/max, a
non-invertible aggregate, or complex per-node merge logic.
