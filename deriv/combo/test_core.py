"""combo.c 검산: 작은 무작위 문제에서 뻔한 파이썬 계산과 숫자가 모두 같은지."""
import numpy as np
import combo_core as K

rng = np.random.default_rng(3)
for trial in range(3):
    T, C = 520, 16
    base = rng.random((T, 5)) < 0.5
    Bt = np.zeros((T, C), np.uint8)
    for c in range(C): Bt[:, c] = (base[:, rng.integers(0, 5)] | (rng.random(T) < 0.45)) & (rng.random(T) < 0.9)
    fid = rng.integers(0, 9, C).astype(np.int32); H = np.array([1, 3, 5], np.int32)
    test_start = 440; TE = test_start - 1; trend = np.array([test_start - h for h in H], np.int32); split = 300
    val = rng.integers(0, 2, (3, T)).astype(np.int8); val[rng.random((3, T)) < 0.03] = -1
    valn = np.stack([np.roll(val, s, axis=1) for s in (97, 211)]); valn[:, :, TE:] = -1
    rules = np.array([[8, 0.6, 0, 0, 0, 0], [8, 0.55, 3, 0.5, 3, 0.5], [12, 0.5, 0, 0, 2, 0.6]], float)
    kw = dict(maxlevel=4, min_raw=6, min_n=6)
    a = K.scan(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, K=5, **kw)
    b = K.brute(Bt, fid, H, trend, val, valn, rules, TE, test_start, split, **kw)
    for k in ('enum', 'hist', 'histn', 'sel', 'seln', 'pool', 'votes'):
        assert np.array_equal(a[k], b[k]), (trial, k, int(np.abs(a[k].astype(np.int64) - b[k]).sum()))
    # 상위 K: 가장 높은 하한이 뻔한 계산의 최고와 같은지(1단계, h=0, 오름)
    print('시험', trial, '같음 · 조합 수', a['enum'][1:5].tolist(), '고른 것', int(a['sel'].sum()), '가짜로 고른 것', int(a['seln'].sum()), '표', int(a['votes'].sum()))
print('검산 통과')
