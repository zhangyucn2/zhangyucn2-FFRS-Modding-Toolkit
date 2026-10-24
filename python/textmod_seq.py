"""字幕时间轴：在**原始 Zen chunk** 里定位并改写关键帧时间。

2026-10-17 实测（FFRS demo，UE5.6）：

* 字幕轨 = `MovieSceneEventTriggerSection` 的一条通道，键数 == 该技能的字幕行数，
  时间单位 **tick = 1/24000 s**，30fps 下 1 帧 = 800 tick。
* 每段 section 数据都以固定 8 字节前缀开头：`00 02 01 02 10 03 00 05`，紧跟
  `[i32 键数][n × i32 tick]` —— 用这个签名定位最稳。
* 同一份 chunk 里还有一份**关键帧句柄表**（运行时求值用它，只改通道无效）：
      [i32 句柄序号][u8 1][i32 tick][u8 1][i32 tick][i32 -1][i32 0][i32 -1]   ← 每条 26 字节
  记录按 tick 升序。
* 必须「通道 + 句柄表」同时改；打包必须 `retoc get` + `retoc pack-raw`，
  否则 `to-zen` 重 cook 会让 chunk 头变化、游戏静默忽略整个容器。
* 「影片在序列里的起点」实测 440011 是 2.0~2.03 s，所以
      tick = (影片内秒数 + 起点) × 24000
"""
import struct

REC = 26
TICK = 24000
TICKS_PER_FRAME = 800
SECTION_PREFIX = bytes.fromhex("0002010210030005")


def _i32(b, o):
    return struct.unpack_from("<i", b, o)[0]


def find_handle_table(b):
    """定位句柄表，返回 [(offset, 句柄序号, tick)]（按 tick 升序）；找不到返回 []。"""
    n = len(b)
    for start in range(0, max(0, n - REC * 3)):
        recs, o = [], start
        while o + REC <= n:
            idx = _i32(b, o)
            f1, f2 = b[o + 4], b[o + 9]
            t1, t2 = _i32(b, o + 5), _i32(b, o + 10)
            e1, e2, e3 = _i32(b, o + 14), _i32(b, o + 18), _i32(b, o + 22)
            if (f1, f2, e1, e2, e3) != (1, 1, -1, 0, -1) or t1 != t2:
                break
            if not (0 <= t1 < 10 ** 9) or not (0 <= idx < 10 ** 6):
                break
            recs.append((o, idx, t1))
            o += REC
        if len(recs) >= 3 and all(recs[i][2] < recs[i + 1][2] for i in range(len(recs) - 1)):
            return recs
    return []


def find_sections(b, sorted_only=True):
    """按固定前缀找所有 trigger section，返回 [(offset, [tick...])]。

    sorted_only=False 时也返回乱序的（用来检测「另一条轨被打乱」）。
    """
    out, i = [], b.find(SECTION_PREFIX)
    while i >= 0:
        if i + 12 <= len(b):
            n = _i32(b, i + 8)
            if 1 <= n <= 60 and i + 12 + 4 * n <= len(b):
                ticks = [_i32(b, i + 12 + 4 * k) for k in range(n)]
                ok = all(0 <= t < 10 ** 7 for t in ticks)
                if ok and (not sorted_only or ticks == sorted(ticks)):
                    out.append((i, ticks))
        i = b.find(SECTION_PREFIX, i + 1)
    return out


def pick_subtitle_section(b, n_rows):
    """挑字幕 section：键数 == 行数、时间都出现在句柄表里、首键 > 0、跨度 ≥ 1 秒（实测校准）。"""
    recs = find_handle_table(b)
    tset = {r[2] for r in recs}
    secs = [s for s in find_sections(b) if len(s[1]) == n_rows]
    scored = []
    for off, ticks in secs:
        inside = all(t in tset for t in ticks)
        span = (ticks[-1] - ticks[0]) / TICK
        ok = inside and ticks[0] > 0 and span >= 1.0
        scored.append((ok, inside, span, off, ticks))
    good = [s for s in scored if s[0]]
    pool = good or scored
    if not pool:
        return None, recs, secs
    pool.sort(key=lambda s: s[2])          # 跨度最小者优先
    ok, inside, span, off, ticks = pool[0]
    return {"off": off, "ticks": list(ticks), "span": span,
            "in_table": inside, "confident": ok}, recs, secs


VALUE = 24          # 每个关键帧的值定长 24 字节（实测：全部 section 都符合）
VALUE_MAGIC = bytes.fromhex("00030005")


def parse_section(b, off):
    """解析一个 section：{off, n, ticks, values(24B 定长), values_off}。"""
    n = _i32(b, off + 8)
    if not (1 <= n <= 60):
        raise ValueError(f"{off:#x} 不是 section")
    ticks = [_i32(b, off + 12 + 4 * k) for k in range(n)]
    vo = off + 12 + 4 * n
    if _i32(b, vo) != n:
        raise ValueError(f"{off:#x} 值数量不匹配")
    vs = vo + 4
    values = []
    for k in range(n):
        p2 = vs + VALUE * k
        if b[p2:p2 + 4] != VALUE_MAGIC:
            raise ValueError(f"{off:#x} 第 {k} 个值不是 24B 结构")
        values.append(bytes(b[p2:p2 + VALUE]))
    return {"off": off, "n": n, "ticks": ticks, "values": values, "values_off": vs}


def rewrite_section(b, off, mapping):
    """按 mapping(old_tick→new_tick) 重写一个 section：**键和值成对排序后一起写回**。

    ★ v1.7 的关键修复：只改键不改值 → 事件时刻和它的载荷（字幕文本）脱钩，实测「时间/内容全乱」。
    """
    sec = parse_section(b, off)
    pairs = [(mapping.get(t, t), v) for t, v in zip(sec["ticks"], sec["values"])]
    pairs.sort(key=lambda e: e[0])
    for k, (t, v) in enumerate(pairs):
        struct.pack_into("<i", b, off + 12 + 4 * k, t)
        p2 = sec["values_off"] + VALUE * k
        b[p2:p2 + VALUE] = v
    return sec["n"]


def clear_keys(b, channel_off):
    """找「清场键」：同一时刻集合还出现在一条键更多的轨上（121 → 122），
    那条轨里多出来的键就是「收掉上一条字幕」的触发点（按时间升序返回）。"""
    secs = {off: ticks for off, ticks in find_sections(b, sorted_only=False)}
    start = secs.get(channel_off)
    if not start:
        raise ValueError("找不到字幕通道")
    sset = set(start)
    best = None
    for off, ticks in secs.items():
        if off == channel_off:
            continue
        if sset.issubset(set(ticks)) and len(ticks) > len(start):
            if best is None or len(ticks) > len(best[1]):
                best = (off, ticks)
    if best is None:
        return None, []
    extras = sorted(t for t in best[1] if t not in sset)
    return best[0], extras


def rewrite(b, channel_off, new_ticks, new_ends=None):
    """把字幕轨的时刻改成 new_ticks（tick）：
        ① 所有含旧 tick 的 section：键 + 24B 值成对排序后重写（121 和 122 一起，保持各自升序）
        ② 句柄表按新时间重排（必须在改之前把记录抓下来）
        ③ 回读前自检：各 section 仍升序、值与键一一对应

    b 必须是 bytearray（原始 chunk）。返回 (重写的 section 数, 警告列表)。
    """
    warn = []
    sec = {off: ticks for off, ticks in find_sections(b)}
    old_ticks = sec.get(channel_off)
    if not old_ticks:
        raise ValueError("找不到字幕通道")
    if len(new_ticks) != len(old_ticks):
        raise ValueError("新旧时间个数不一致")
    new_sorted = sorted(int(t) for t in new_ticks)

    recs = find_handle_table(b)           # ① 先抓句柄表（改完就认不出来了）
    if not recs:
        raise ValueError("句柄表定位失败")
    first_rec, rec_list = recs[0][0], [(idx, t) for (_o, idx, t) in recs]
    mapping = dict(zip(sorted(old_ticks), new_sorted))

    # ★ 结束时间：把同轨的「清场键」挪到指定时刻（实测：字幕显示到下一个清场键为止）
    clears_off, clears = (None, [])
    if new_ends:
        clears_off, clears = clear_keys(b, channel_off)
        if len(clears) < len(new_ends):
            raise ValueError(f"清场键只有 {len(clears)} 个，不够 {len(new_ends)} 条字幕")
        for old_t, new_t in zip(clears[:len(new_ends)], sorted(int(t) for t in new_ends)):
            mapping[old_t] = new_t
        # 最后一个没被占用的清场键：如果它比所有结束时刻都早，往后推，免得把末条字幕截短
        if len(clears) > len(new_ends):
            tail = clears[len(new_ends):]
            limit = max(mapping.get(c, c) for c in clears[:len(new_ends)])
            for t in tail:
                if t <= limit:
                    mapping[t] = limit + TICK * 2
                    limit = mapping[t]

    touched = 0                            # ② 所有含旧 tick 的 section 一起重写
    for off, ticks in find_sections(b, sorted_only=False):
        if not any(t in mapping for t in ticks):
            continue
        rewrite_section(b, off, mapping)
        touched += 1

    mapped = [(idx, mapping.get(t, t)) for idx, t in rec_list]   # ③ 句柄表重排
    mapped.sort(key=lambda e: e[1])
    for k, (idx, t) in enumerate(mapped):
        o = first_rec + REC * k
        struct.pack_into("<i", b, o, idx)
        b[o + 4] = 1
        struct.pack_into("<i", b, o + 5, t)
        b[o + 9] = 1
        struct.pack_into("<i", b, o + 10, t)
        struct.pack_into("<i", b, o + 14, -1)
        struct.pack_into("<i", b, o + 18, 0)
        struct.pack_into("<i", b, o + 22, -1)

    for off, ticks in find_sections(bytes(b), sorted_only=False):   # ④ 自检
        if any(ticks[i] > ticks[i + 1] for i in range(len(ticks) - 1)):
            raise ValueError(f"自检失败：section @{off:#x} 不升序")
    return touched, warn


def verify(b, channel_off, expect_ticks):
    """回读校验：通道里的键是否等于期望值，且句柄表仍升序。"""
    sec = {off: ticks for off, ticks in find_sections(bytes(b))}
    got = sec.get(channel_off)
    if got != sorted(int(t) for t in expect_ticks):
        raise RuntimeError(f"回读校验失败：通道 {got} != {sorted(expect_ticks)}")
    recs = find_handle_table(bytes(b))
    ts = [r[2] for r in recs]
    if ts != sorted(ts):
        raise RuntimeError("回读校验失败：句柄表不再升序")
    return True
