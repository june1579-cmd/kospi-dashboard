"""combo.c 검산: 작은 무작위 문제에서 뻔한 파이썬 계산과 숫자가 모두 같은지(세는 값 전부 + 상위 표 두 가지)."""
import numpy as np
import combo_core as K

rng = np.random.default_rng(3)
KTOP = 5


def check_top(a, b, key_lb, key_id, key_st, ref, rowwin, trial):
    """C 의 상위 표: (1) 켜진 날이 같은 조합을 하나로 보았을 때 점수 상위 KTOP 개가 뻔한 계산과 같고 (2) 표에 든 조합마다 숫자 8개가 뻔한 계산과 같고
    (3) 한 스레드의 표 안에 켜진 날이 같은 조합이 두 번 들지 않았는지."""
    nth, ML, nH, _, k = a[key_lb].shape; seen = 0
    for L in range(1, ML + 1):
        for hi in range(nH):
            for dr in range(2):
                lb = a[key_lb][:, L - 1, hi, dr].ravel(); ids = a[key_id][:, L - 1, hi, dr].reshape(-1, 4); st = a[key_st][:, L - 1, hi, dr].reshape(-1, K.NST)
                got = sorted([(float(lb[q]), tuple(int(i) for i in ids[q] if i >= 0), [int(x) for x in st[q]]) for q in range(len(lb)) if lb[q] > -1.0], reverse=True)
                want = ref.get((L, hi, dr) if key_lb == 'toplb' else (L, hi), {}) if not (key_lb != 'toplb' and dr) else {}
                best = {}
                for v in want.values(): best[v[2]] = max(best.get(v[2], -9.0), v[0])
                ws = sorted(best.values(), reverse=True)[:KTOP]; gd = {}
                for sc, cid, s8 in got:
                    assert cid in want and abs(want[cid][0] - sc) < 1e-12 and want[cid][1] == s8, (trial, key_lb, L, hi, dr, cid, sc, s8, want.get(cid))
                    gd[want[cid][2]] = sc; seen += 1
                gs = sorted(gd.values(), reverse=True)
                assert len(gs) >= len(ws) and np.allclose(gs[:len(ws)], ws), (trial, key_lb, L, hi, dr, gs[:KTOP], ws)
                for q in range(nth):      # 스레드 하나의 표 안에는 켜진 날이 같은 조합이 없어야 한다
                    keys = [want[tuple(int(i) for i in a[key_id][q, L - 1, hi, dr, x] if i >= 0)][2] for x in range(k) if a[key_lb][q, L - 1, hi, dr, x] > -1.0]
                    assert len(keys) == len(set(keys)), (trial, key_lb, L, hi, dr, q)
    return seen


for trial in range(4):
    T, C = 520, 16
    base = rng.random((T, 5)) < 0.5
    Bt = np.zeros((T, C), np.uint8)
    for c in range(C): Bt[:, c] = (base[:, rng.integers(0, 5)] | (rng.random(T) < 0.45)) & (rng.random(T) < 0.9)
    fid = rng.integers(0, 9, C).astype(np.int32); H = np.array([1, 3, 5, 3], np.int32)
    test_start = 440; TE = test_start - 1; trend = np.array([test_start - h for h in H], np.int32); split = 300
    val = rng.integers(0, 2, (4, T)).astype(np.int8); val[rng.random((4, T)) < 0.03] = -1
    valn = np.stack([np.roll(val, s, axis=1) for s in (97, 211)]); valn[:, :, TE:] = -1
    if trial % 2:      # 홀수 번째 시험: 첫 줄 = 저점 전환 구간 줄, 넷째 줄 = 고점 전환 구간 줄, 셋째 줄 = 동반 수익 줄. 규칙에 '적용 줄'과 '동반 수익 조건'을 섞는다.
        rw = np.array([1, 0, 0, 2], np.int32); comp, toprule = 2, 1; val[0] = np.abs(val[0]); val[3] = np.abs(val[3]); valn[:, [0, 3], :TE] = np.abs(valn[:, [0, 3], :TE])
        rules = np.array([[8, 0.6, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0], [8, 0.5, 0, 0, 0, 0, 5, 1, 0, 0, 0, 0], [8, 0.5, 0, 0, 0, 0, 5, 1, 0.55, 6, 0, 0], [12, 0.5, 0, 0, 2, 0.6, 0, 2, 0, 0, 0, 0]], float)
    else:
        rw = np.array([0, 0, 0, 0], np.int32); comp, toprule = -1, -1
        rules = np.array([[8, 0.6, 0, 0, 0, 0, 0], [8, 0.55, 3, 0.5, 3, 0.5, 6], [12, 0.5, 0, 0, 2, 0.6, 0]], float)
    kw = dict(maxlevel=4, min_raw=6, min_n=6, rowwin=rw, ptop=np.array([0.5, 0, 0, 0.45]), comp=comp, toprule=toprule, top2_min_n=6)
    a = K.scan(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, K=KTOP, nthreads=3, **kw)
    b = K.brute(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, **kw)
    for k in ('enum', 'hist', 'histn', 'sel', 'seln', 'pool', 'votes', 'xpool'):
        assert np.array_equal(a[k], b[k]), (trial, k, int(np.abs(a[k].astype(np.int64) - b[k]).sum()))
    n1 = check_top(a, b, 'toplb', 'topid', 'topst8', b['t1'], rw, trial); n2 = check_top(a, b, 'top2lb', 'top2id', 'top2st', b['t2'], rw, trial)
    print('시험', trial, '같음 · 조합 수', a['enum'][1:5].tolist(), '고른 것', int(a['sel'].sum()), '가짜로 고른 것', int(a['seln'].sum()), '표', int(a['votes'].sum()), '교차', int(a['xpool'].sum()), '상위 표 1·2 확인', n1, n2)
print('검산 통과')
