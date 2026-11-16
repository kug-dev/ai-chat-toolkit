"""Similarity module for Chat Topic Finder."""
from __future__ import annotations
from .common import *
from .indexing import build_features, sync_sqlite_cache_and_fts
from .llm import apply_llm_report_features
from .text import log_msg

def make_vectors(
    chats: list[Chat],
    log: Callable[[str], None] | None = None,
    db_path: Path | None = None,
    llm_mode: str = "hybrid",
) -> None:
    n = len(chats)
    df: Counter = Counter()
    if db_path is not None:
        sync_sqlite_cache_and_fts(chats, db_path, log)
    else:
        for chat in chats:
            build_features(chat)
    for chat in chats:
        if chat.llm_report:
            apply_llm_report_features(chat, llm_mode=llm_mode)
        df.update(chat.features.keys())
    for chat in chats:
        weighted = {}
        for key, tf in chat.features.items():
            idf = math.log(1.0 + (n - df[key] + 0.5) / (df[key] + 0.5))
            weighted[key] = (1.0 + math.log(max(tf, 1e-9))) * idf
        norm = math.sqrt(sum(v * v for v in weighted.values()))
        chat.vector = {k: v / norm for k, v in weighted.items()} if norm else {}
        if chat.truncated:
            log_msg(log, f"Note: text truncated at {MAX_TEXT_CHARS:,} characters: {chat.title}")
    log_msg(log, f"Indexed {n} chat(s), {len(df):,} distinct features (mode={llm_mode}).")

def dot_similarity(a: dict[str, float], b: dict[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return min(1.0, max(0.0, sum(v * b.get(k, 0.0) for k, v in a.items())))

def candidate_pairs(chats: list[Chat], log: Callable[[str], None] | None = None) -> set[tuple[int, int]]:
    n = len(chats)
    if n <= 1:
        return set()
    postings: dict[str, list[int]] = defaultdict(list)
    df = Counter(k for c in chats for k in c.features)
    posting_cap = max(10, min(90, int(2.1 * math.sqrt(n))))
    for i, chat in enumerate(chats):
        best = sorted(chat.vector.items(), key=lambda kv: kv[1], reverse=True)[:90]
        for key, _ in best:
            if df[key] <= posting_cap:
                postings[key].append(i)
    pairs: set[tuple[int, int]] = set()
    reached_cap = False
    for key, ids in postings.items():
        if len(ids) < 2:
            continue
        for x in range(len(ids) - 1):
            a = ids[x]
            for y in range(x + 1, len(ids)):
                b = ids[y]
                pairs.add((a, b) if a < b else (b, a))
                if len(pairs) >= MAX_CANDIDATE_PAIRS:
                    reached_cap = True
                    break
            if reached_cap:
                break
        if reached_cap:
            break
    by_hash: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(chats):
        if c.digest:
            by_hash[c.digest].append(i)
    for ids in by_hash.values():
        for x in range(len(ids) - 1):
            for y in range(x + 1, len(ids)):
                pairs.add((min(ids[x], ids[y]), max(ids[x], ids[y])))
    if reached_cap:
        log_msg(log, f"Warning: candidate-pair safety cap ({MAX_CANDIDATE_PAIRS:,}) reached; results may omit some links. Consider analyzing smaller batches.")
    log_msg(log, f"Comparing {len(pairs):,} candidate pair(s)…")
    return pairs

def shared_terms(a: Chat, b: Chat, count: int = 6) -> list[str]:
    common = set(a.vector) & set(b.vector)
    scored = []
    for key in common:
        if key.startswith("r:"):
            label = f"report:{key[2:]}"
            weight = a.vector[key] * b.vector[key] * 1.65
        elif key.startswith("w:"):
            label = key[2:]
            weight = a.vector[key] * b.vector[key] * 1.05
        elif key.startswith("b:"):
            label = key[2:]
            weight = a.vector[key] * b.vector[key] * 1.5
        elif key.startswith("a:"):
            label = f"artifact:{key[2:]}"
            weight = a.vector[key] * b.vector[key] * 1.45
        elif key.startswith("s:"):
            label = key[2:]
            weight = a.vector[key] * b.vector[key] * 1.15
        elif key.startswith("k:"):
            label = f"code:{key[2:]}"
            weight = a.vector[key] * b.vector[key] * 0.95
        else:
            continue
        scored.append((weight, label))
    scored.sort(reverse=True)
    out = []
    for _, label in scored:
        if label not in out:
            out.append(label)
        if len(out) >= count:
            break
    return out

def top_chat_terms(chat: Chat, count: int = 8) -> list[list[str | float]]:
    """Return top lexical or LLM-report terms and weights for a single chat."""
    scored: list[tuple[float, str]] = []
    for key, val in chat.vector.items():
        if key.startswith("r:"):
            scored.append((val * 1.5, key[2:]))
        elif key.startswith("w:"):
            scored.append((val, key[2:]))
        elif key.startswith("b:"):
            scored.append((val * 1.35, key[2:]))
        elif key.startswith("a:"):
            scored.append((val * 1.3, key[2:]))
        elif key.startswith("s:"):
            scored.append((val * 1.05, key[2:]))
    scored.sort(reverse=True)
    out: list[list[str | float]] = []
    seen: set[str] = set()
    for weight, label in scored:
        if label not in seen:
            seen.add(label)
            out.append([label, round(weight, 4)])
        if len(out) >= count:
            break
    return out

def compare_chats(
    chats: list[Chat],
    threshold: float,
    log=None,
    interactive_pool: list[dict] | None = None,
    db_path: Path | None = None,
    llm_mode: str = "hybrid",
) -> list[dict]:
    make_vectors(chats, log, db_path=db_path, llm_mode=llm_mode)
    candidates = candidate_pairs(chats, log)
    edges = []
    pool_edges = []
    floor = min(threshold, REPORT_PAIR_FLOOR)
    total = len(candidates)
    for j, (a, b) in enumerate(candidates):
        score = 1.0 if chats[a].digest == chats[b].digest else dot_similarity(chats[a].vector, chats[b].vector)
        if score >= threshold:
            edge = {"a": a, "b": b, "score": score, "shared_terms": shared_terms(chats[a], chats[b])}
            edges.append(edge)
            if interactive_pool is not None:
                pool_edges.append(edge)
        elif interactive_pool is not None and score >= floor:
            pool_edges.append({"a": a, "b": b, "score": score, "shared_terms": shared_terms(chats[a], chats[b])})
        if total > 100 and j % 50000 == 0 and j:
            log_msg(log, f"Scored {j:,}/{total:,} candidate pairs…")
    edges.sort(key=lambda e: (-e["score"], chats[e["a"]].title.casefold(), chats[e["b"]].title.casefold()))
    if interactive_pool is not None:
        pool_edges.sort(key=lambda e: (-e["score"], chats[e["a"]].title.casefold(), chats[e["b"]].title.casefold()))
        interactive_pool.clear()
        interactive_pool.extend(pool_edges[:MAX_INTERACTIVE_EDGES])
    log_msg(log, f"Found {len(edges):,} pair(s) at or above similarity threshold {threshold:.2f}.")
    return edges

def filter_mutual_knn_edges(edges: list[dict], mutual_knn: int) -> list[dict]:
    """Retain only edges (u, v) where v is in u's top-k neighbors AND u is in v's top-k.
    Exact duplicate matches (score >= 0.9999) are always preserved."""
    if mutual_knn <= 0 or not edges:
        return list(edges)
    adj: dict[int, list[tuple[float, int]]] = defaultdict(list)
    for e in edges:
        a, b, s = e["a"], e["b"], e["score"]
        adj[a].append((s, b))
        adj[b].append((s, a))
    top_neighbors: dict[int, set[int]] = {}
    for node, nbrs in adj.items():
        nbrs.sort(key=lambda item: -item[0])
        cutoff_score = nbrs[min(len(nbrs), mutual_knn) - 1][0]
        # Include ties at the k-th boundary so ordering is deterministic.
        top_neighbors[node] = {nb for sc, nb in nbrs if sc >= cutoff_score or sc >= 0.9999}
    filtered = [
        e for e in edges
        if e["score"] >= 0.9999 or (e["b"] in top_neighbors.get(e["a"], set()) and e["a"] in top_neighbors.get(e["b"], set()))
    ]
    return filtered

def _raw_connected_components(nodes: Iterable[int], edges: list[dict], min_size: int = 2) -> list[list[int]]:
    node_list = sorted(set(nodes))
    if len(node_list) < min_size:
        return []
    node_set = set(node_list)
    parent = {u: u for u in node_list}
    rank = {u: 0 for u in node_list}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x: int, y: int) -> None:
        rx, ry = find(x), find(y)
        if rx == ry:
            return
        if rank[rx] < rank[ry]:
            rx, ry = ry, rx
        parent[ry] = rx
        if rank[rx] == rank[ry]:
            rank[rx] += 1

    for e in edges:
        a, b = e["a"], e["b"]
        if a in node_set and b in node_set:
            union(a, b)

    groups: dict[int, list[int]] = defaultdict(list)
    for u in node_list:
        groups[find(u)].append(u)

    result = [g for g in groups.values() if len(g) >= min_size]
    edge_max = {(min(e["a"], e["b"]), max(e["a"], e["b"])): e["score"] for e in edges}
    result.sort(
        key=lambda g: (
            -len(g),
            -max((edge_max.get((min(a, b), max(a, b)), 0.0) for idx, a in enumerate(g) for b in g[idx + 1:]), default=0.0),
        )
    )
    return result

def _prune_bridge_edges_by_betweenness(nodes: list[int], sub_edges: list[dict], min_size: int) -> list[list[int]]:
    """Fallback splitter when uniform edge scores prevent threshold tightening from
    splitting an oversized cluster: iteratively remove edges with the highest
    Brandes shortest-path betweenness weighted by inverse similarity."""
    if len(sub_edges) <= 1:
        return [nodes]
    active_edges = list(sub_edges)
    node_set = set(nodes)
    max_iters = max(8, len(sub_edges) // 2)

    for _ in range(max_iters):
        comps = _raw_connected_components(node_set, active_edges, min_size=min_size)
        if len(comps) >= 2:
            return comps
        if len(active_edges) <= 1:
            break

        adj: dict[int, list[int]] = defaultdict(list)
        for e in active_edges:
            adj[e["a"]].append(e["b"])
            adj[e["b"]].append(e["a"])

        edge_bet: Counter[tuple[int, int]] = Counter()
        for s in nodes:
            stack: list[int] = []
            pred: dict[int, list[int]] = defaultdict(list)
            sigma: dict[int, float] = defaultdict(float)
            sigma[s] = 1.0
            dist: dict[int, int] = {s: 0}
            q: deque[int] = deque([s])
            while q:
                v = q.popleft()
                stack.append(v)
                for w in adj[v]:
                    if w not in dist:
                        dist[w] = dist[v] + 1
                        q.append(w)
                    if dist[w] == dist[v] + 1:
                        sigma[w] += sigma[v]
                        pred[w].append(v)
            delta: dict[int, float] = defaultdict(float)
            while stack:
                w = stack.pop()
                for v in pred[w]:
                    if sigma[w] > 0:
                        c = (sigma[v] / sigma[w]) * (1.0 + delta[w])
                        key = (min(v, w), max(v, w))
                        edge_bet[key] += c
                        delta[v] += c

        if not edge_bet:
            break
        # Favor cutting high-betweenness, lower-similarity bridge edges (never cut exact duplicates).
        best_edge = None
        best_metric = -1.0
        for e in active_edges:
            if e["score"] >= 0.9999:
                continue
            key = (min(e["a"], e["b"]), max(e["a"], e["b"]))
            metric = edge_bet.get(key, 0.0) / max(e["score"], 0.05)
            if metric > best_metric:
                best_metric = metric
                best_edge = key
        if best_edge is None:
            break
        active_edges = [e for e in active_edges if (min(e["a"], e["b"]), max(e["a"], e["b"])) != best_edge]

    return [nodes]

def _subcluster_component(
    members: list[int],
    comp_edges: list[dict],
    base_threshold: float,
    min_size: int,
    max_group_size: int,
    subcluster_step: float,
    mutual_knn: int,
    depth: int = 0,
) -> list[tuple[list[int], float]]:
    """Recursively split an oversized connected component into tighter sub-clusters."""
    if max_group_size <= 0 or len(members) <= max_group_size or depth >= 5:
        return [(members, base_threshold)]

    step = max(0.02, subcluster_step)
    member_set = set(members)
    local_edges = [e for e in comp_edges if e["a"] in member_set and e["b"] in member_set]
    if not local_edges:
        return [(members, base_threshold)]

    # Try progressive threshold tightening combined with slightly stricter mutual k-NN.
    tighter_k = max(3, (mutual_knn * 2) // 3) if mutual_knn > 0 else 8
    cur_th = base_threshold
    split_comps: list[list[int]] = []
    chosen_th = base_threshold

    for attempt in range(1, 6):
        candidate_th = min(0.95, cur_th + step * attempt)
        above = [e for e in local_edges if e["score"] >= candidate_th]
        above = filter_mutual_knn_edges(above, tighter_k)
        comps = _raw_connected_components(member_set, above, min_size=min_size)
        if len(comps) >= 2 or (len(comps) == 1 and len(comps[0]) <= max_group_size and len(comps[0]) >= min_size):
            split_comps = comps
            chosen_th = candidate_th
            break

    # If threshold tightening didn't cleanly divide the component, try shortest-path bridge pruning.
    if not split_comps:
        pruned_comps = _prune_bridge_edges_by_betweenness(members, local_edges, min_size=min_size)
        if len(pruned_comps) >= 2:
            split_comps = pruned_comps
            chosen_th = base_threshold

    if not split_comps or (len(split_comps) == 1 and len(split_comps[0]) == len(members)):
        return [(members, base_threshold)]

    results: list[tuple[list[int], float]] = []
    assigned: set[int] = set()
    for sub in split_comps:
        assigned.update(sub)
        if len(sub) > max_group_size:
            results.extend(
                _subcluster_component(
                    sub,
                    local_edges,
                    chosen_th,
                    min_size=min_size,
                    max_group_size=max_group_size,
                    subcluster_step=step,
                    mutual_knn=tighter_k,
                    depth=depth + 1,
                )
            )
        else:
            results.append((sub, chosen_th))

    # Regroup leftover peripheral nodes if they still form valid mini-clusters at base_threshold.
    leftover = [u for u in members if u not in assigned]
    if len(leftover) >= min_size:
        left_set = set(leftover)
        left_edges = [e for e in local_edges if e["a"] in left_set and e["b"] in left_set]
        for lcomp in _raw_connected_components(left_set, left_edges, min_size=min_size):
            results.append((lcomp, base_threshold))

    return results if results else [(members, base_threshold)]

def connected_groups(
    n: int,
    edges: list[dict],
    min_size: int = 2,
    mutual_knn: int = 12,
    max_group_size: int = 25,
     threshold: float = 0.20,
    subcluster_step: float = 0.08,
    log: Callable[[str], None] | None = None,
) -> list[TopicGroup]:
    """Build topic groups using Mutual k-NN edge filtering and recursive sub-clustering
    to prevent 'giant hairball' clusters."""
    filtered_edges = filter_mutual_knn_edges(edges, mutual_knn)
    if mutual_knn > 0 and len(filtered_edges) < len(edges):
        log_msg(log, f"Mutual {mutual_knn}-NN filter refined {len(edges):,} -> {len(filtered_edges):,} clustering edges.")

    base_components = _raw_connected_components(range(n), filtered_edges, min_size=min_size)
    topic_groups: list[TopicGroup] = []
    oversized_split_count = 0

    for parent_idx, comp in enumerate(base_components, 1):
        if max_group_size > 0 and len(comp) > max_group_size:
            sub_results = _subcluster_component(
                comp,
                filtered_edges,
                base_threshold=threshold,
                min_size=min_size,
                max_group_size=max_group_size,
                subcluster_step=subcluster_step,
                mutual_knn=mutual_knn,
            )
            if len(sub_results) > 1 or (len(sub_results) == 1 and len(sub_results[0][0]) < len(comp)):
                oversized_split_count += 1
                for sub_idx, (sub_members, eff_th) in enumerate(sub_results, 1):
                    gid = f"{parent_idx}.{sub_idx}" if len(sub_results) > 1 else str(parent_idx)
                    topic_groups.append(
                        TopicGroup(
                            id=gid,
                            members=sub_members,
                            parent_id=parent_idx,
                            subclustered=True,
                            effective_threshold=eff_th,
                        )
                    )
                continue
        topic_groups.append(
            TopicGroup(
                id=str(parent_idx),
                members=comp,
                parent_id=None,
                subclustered=False,
                effective_threshold=threshold,
            )
        )

    if oversized_split_count:
        log_msg(log, f"Sub-clustered {oversized_split_count} oversized component(s) (> {max_group_size} chats) into cohesive sub-topics.")
    return topic_groups

def group_label(group: list[int], chats: list[Chat]) -> str:
    totals: Counter = Counter()
    topic_votes: Counter = Counter()
    for i in group:
        pt = (chats[i].llm_report or {}).get("primary_topic", "").strip()
        if pt:
            topic_votes[pt] += 1
        v = chats[i].vector
        for k, value in v.items():
            if k.startswith("r:"):
                totals[k[2:]] += value * 1.5
            elif k.startswith("w:"):
                totals[k[2:]] += value
            elif k.startswith("b:"):
                totals[k[2:]] += value * 1.35
            elif k.startswith("a:"):
                totals[k[2:]] += value * 1.25
    if topic_votes:
        top_topics = [t for t, _ in topic_votes.most_common(2)]
        if top_topics:
            return " · ".join(top_topics)
    if not totals:
        return "Shared-topic group"
    terms = [x for x, _ in totals.most_common(4)]
    bigrams = [x for x in terms if " " in x]
    words = [x for x in terms if " " not in x]
    chosen = (bigrams[:2] + words[:2])[:3]
    return " · ".join(chosen) if chosen else "Shared-topic group"

def safe_slug(text: str, max_len: int = 48) -> str:
    cleaned = re.sub(r"[^\w\u0590-\u05FF-]+", "_", text, flags=re.U).strip("_")
    return (cleaned[:max_len] or "topic").strip("_")
