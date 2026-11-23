/* combo.c — 조건 조합 '전부 훑기' 핵심 계산 (2026-11-23).
 *
 * 하는 일: 조건(참·거짓) C개에서 서로 다른 지표의 조건 1~4개를 '그리고'로 묶은 모든 조합 가운데
 *          학습 구간 신호일이 min_raw 일 이상인 것을 하나도 빼지 않고 센다.
 *          (조합의 신호일은 그 부분 조합의 신호일보다 많을 수 없으므로, 신호일이 모자란 조합의 확장은 건너뛰어도 빠지는 것이 없다.)
 * 조합마다: 보유일 h 별로 겹치지 않게 솎은(앞 신호 뒤 h 거래일 지나야 다음 신호) 거래 수·오른 횟수를 학습 구간 두 토막(split 앞·뒤)으로 세고,
 *          고르는 규칙에 맞으면 시험 구간(test_start 이후) 성적과 날짜별 표(votes)를 쌓는다. 가짜 수익(valn)으로도 같은 것을 센다.
 * 시각: day d 의 조건은 d일 장 마감 뒤 값, val[h][d] = d+1일 시가 → d+h일 종가 수익의 부호(1 오름, 0 내림, -1 모름).
 */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <omp.h>

#define MAXH 8
#define MAXB 6
#define MAXR 8
#define MAXL 4
#define NBIN 21

static int C_, T_, nH_, nB_, nR_, maxlevel_, min_raw_, min_n_, TE_, test_start_, split_, K_, TT_, do_hash_;
static int64_t hash_cap_;
static const uint8_t *Bt_; static const int32_t *fid_; static const int8_t *val_, *valn_; static const double *rules_;
static int H_[MAXH], trend_[MAXH], rowwin_[MAXH];   /* rowwin: 1 = 그 줄은 '전환 구간 안인가'(오름 쪽만 봄), 0 = 수익 부호 줄 */
static double ptop_[MAXH];                              /* 전환 구간 줄의 상위 표: 적중(구간 안 비율)이 이 값 이상인 것 가운데 '찾은 수'가 많은 순 */
static volatile int stop4_;
static double t0_, budget_;

typedef struct {
    int64_t *hist, *histn, *sel, *seln, *pool, *xpool; int32_t *votes;   /* xpool: 전환 구간 줄에서 고른 조합의 다른 줄(수익) 성적 */
    double *toplb; int32_t *topid, *topst;
    uint64_t *hbuf; int32_t *hmeta; int64_t hcount;
    int64_t enumc[MAXL + 2]; int64_t l3total, l3expanded;
} TL;

#define CELL(L, hi, dir) ((((L) - 1) * nH_ + (hi)) * 2 + (dir))
#define RCELL(L, r, hi, dir) (((((L) - 1) * nR_ + (r)) * nH_ + (hi)) * 2 + (dir))

static inline double wilson(int k, int n) {
    const double z = 1.28; double p = (double)k / n, d = 1 + z * z / n, c = p + z * z / (2.0 * n), h = z * sqrt(p * (1 - p) / n + z * z / (4.0 * n * n));
    return (c - h) / d;
}
static inline int rule_ok(const double *R, int na, int ua, int n0, int u0, int n1, int u1) {
    if (na < R[0] || ua < R[1] * na - 1e-9 || ua < R[6]) return 0;
    if (R[2] > 0 && (n0 < R[2] || u0 < R[3] * n0 - 1e-9)) return 0;
    if (R[4] > 0 && (n1 < R[4] || u1 < R[5] * n1 - 1e-9)) return 0;
    return 1;
}

static void eval_combo(TL *t, int L, const int *ids, const int32_t *A, int nA, const int32_t *E, int nE) {
    int n[MAXH][2], up[MAXH][2], nn[MAXB][MAXH][2], upn[MAXB][MAXH][2], last[MAXH];
    memset(n, 0, sizeof n); memset(up, 0, sizeof up); memset(nn, 0, sizeof nn); memset(upn, 0, sizeof upn);
    for (int hi = 0; hi < nH_; hi++) last[hi] = -1000000;
    for (int a = 0; a < nA; a++) {
        int d = A[a];
        for (int hi = 0; hi < nH_; hi++) {
            if (d >= trend_[hi] || d - last[hi] < H_[hi]) continue;
            int v = val_[(size_t)hi * T_ + d]; if (v < 0) continue;
            last[hi] = d; int s = d >= split_; n[hi][s]++; up[hi][s] += v;
            for (int b = 0; b < nB_; b++) { int vb = valn_[((size_t)b * nH_ + hi) * T_ + d]; if (vb >= 0) { nn[b][hi][s]++; upn[b][hi][s] += vb; } }
        }
    }
    t->enumc[L]++;
    unsigned selmask[MAXH][2]; int topins[MAXH][2]; double lbv[MAXH][2]; int nall[MAXH][2], uall[MAXH][2]; int need = 0;
    for (int hi = 0; hi < nH_; hi++) for (int dir = 0; dir < 2; dir++) {
        selmask[hi][dir] = 0; topins[hi][dir] = 0;
        if (rowwin_[hi] && dir) continue;
        int n0 = n[hi][0], n1 = n[hi][1], na = n0 + n1;
        if (na >= min_n_) {
            int u0 = dir ? n0 - up[hi][0] : up[hi][0], u1 = dir ? n1 - up[hi][1] : up[hi][1], ua = u0 + u1;
            nall[hi][dir] = na; uall[hi][dir] = ua;
            int bin = (int)((double)ua * 20.0 / na + 1e-9); t->hist[(size_t)CELL(L, hi, dir) * NBIN + bin]++;
            for (int r = 0; r < nR_; r++) if (rule_ok(rules_ + r * 7, na, ua, n0, u0, n1, u1)) {
                selmask[hi][dir] |= 1u << r; size_t rc = RCELL(L, r, hi, dir); t->sel[rc]++; t->pool[rc * 4 + 0] += na; t->pool[rc * 4 + 1] += ua; need = 1;
            }
            double lb = wilson(ua, na);
            if (rowwin_[hi]) lb = (ua >= ptop_[hi] * na - 1e-9) ? (double)ua + lb : -1.0;      /* 찾은 수가 먼저, 같으면 하한 */
            lbv[hi][dir] = lb;
            if (K_ > 0) { const double *tl = t->toplb + (size_t)CELL(L, hi, dir) * K_; double mn = tl[0]; for (int q = 1; q < K_; q++) if (tl[q] < mn) mn = tl[q];
                if (lb > mn) { topins[hi][dir] = 1; need = 1; } }
        }
        for (int b = 0; b < nB_; b++) {
            int m0 = nn[b][hi][0], m1 = nn[b][hi][1], ma = m0 + m1; if (ma < min_n_) continue;
            int w0 = dir ? m0 - upn[b][hi][0] : upn[b][hi][0], w1 = dir ? m1 - upn[b][hi][1] : upn[b][hi][1], wa = w0 + w1;
            int bin = (int)((double)wa * 20.0 / ma + 1e-9); t->histn[((size_t)b * MAXL * nH_ * 2 + CELL(L, hi, dir)) * NBIN + bin]++;
            for (int r = 0; r < nR_; r++) if (rule_ok(rules_ + r * 7, ma, wa, m0, w0, m1, w1)) t->seln[(size_t)b * MAXL * nR_ * nH_ * 2 + RCELL(L, r, hi, dir)]++;
        }
    }
    if (!need) return;
    int nt[MAXH], ut[MAXH], lastt[MAXH];
    for (int hi = 0; hi < nH_; hi++) { nt[hi] = ut[hi] = 0; lastt[hi] = -1000000; }
    for (int e = 0; e < nE; e++) { int d = E[e];
        for (int hi = 0; hi < nH_; hi++) { if (d - lastt[hi] < H_[hi]) continue; int v = val_[(size_t)hi * T_ + d]; if (v < 0) continue; lastt[hi] = d; nt[hi]++; ut[hi] += v; } }
    uint64_t hsh = 0; int hashed = 0;
    for (int hi = 0; hi < nH_; hi++) for (int dir = 0; dir < 2; dir++) {
        int te_n = nt[hi], te_u = dir ? nt[hi] - ut[hi] : ut[hi];
        unsigned m = selmask[hi][dir];
        for (int r = 0; m; r++, m >>= 1) if (m & 1u) {
            size_t rc = RCELL(L, r, hi, dir); t->pool[rc * 4 + 2] += te_n; t->pool[rc * 4 + 3] += te_u;
            if (rowwin_[hi]) for (int h2 = 0; h2 < nH_; h2++) if (!rowwin_[h2]) {
                int64_t *xp = t->xpool + (((((size_t)(L - 1) * nR_ + r) * nH_ + hi) * nH_ + h2) * 4);
                xp[0] += n[h2][0] + n[h2][1]; xp[1] += up[h2][0] + up[h2][1]; xp[2] += nt[h2]; xp[3] += ut[h2];
            }
            if (TT_ > 0) { int32_t *vv = t->votes + rc * TT_; for (int e = 0; e < nE; e++) vv[E[e] - test_start_]++; }
            if (do_hash_ && r < 2) {
                if (!hashed) { hsh = 1469598103934665603ULL; for (int a = 0; a < nA; a++) { hsh ^= (uint64_t)(A[a] + 1); hsh *= 1099511628211ULL; } hashed = 1; }
                if (t->hcount < hash_cap_) { t->hbuf[t->hcount] = hsh; t->hmeta[t->hcount] = (L << 16) | (hi << 8) | (dir << 4) | r; }
                t->hcount++;
            }
        }
        if (topins[hi][dir]) {
            size_t c = (size_t)CELL(L, hi, dir) * K_; double *tl = t->toplb + c; int q0 = 0; for (int q = 1; q < K_; q++) if (tl[q] < tl[q0]) q0 = q;
            tl[q0] = lbv[hi][dir]; int32_t *ti = t->topid + (c + q0) * 4, *ts = t->topst + (c + q0) * 4;
            for (int x = 0; x < 4; x++) ti[x] = x < L ? ids[x] : -1;
            ts[0] = nall[hi][dir]; ts[1] = uall[hi][dir]; ts[2] = te_n; ts[3] = te_u;
        }
    }
}

static inline void split_list(const int32_t *src, int ns, int c, int32_t *dst, int *nd) {
    int m = 0; for (int a = 0; a < ns; a++) { int d = src[a]; if (Bt_[(size_t)d * C_ + c]) dst[m++] = d; } *nd = m;
}
static inline void count_ext(const int32_t *A, int nA, int from, uint16_t *cnt) {
    memset(cnt, 0, (size_t)C_ * sizeof(uint16_t));
    for (int a = 0; a < nA; a++) { const uint8_t *row = Bt_ + (size_t)A[a] * C_; for (int k = from; k < C_; k++) cnt[k] += row[k]; }
}

/* ip: C,T,nH,nB,nR,maxlevel,min_raw,min_n,TE,test_start,split,K,do_hash,nthreads_max   dp: budget_sec   hash_cap: 스레드마다 */
int combo_scan(const int32_t *ip, const double *dp, const uint8_t *Bt, const int32_t *fid, const int32_t *H, const int32_t *trend,
               const int8_t *val, const int8_t *valn, const double *rules, int64_t hash_cap, const int32_t *rowwin, const double *ptop, int64_t *o_xpool,
               int64_t *o_enum, int64_t *o_hist, int64_t *o_histn, int64_t *o_sel, int64_t *o_seln, int64_t *o_pool, int32_t *o_votes,
               double *o_toplb, int32_t *o_topid, int32_t *o_topst, uint64_t *o_hbuf, int32_t *o_hmeta, int64_t *o_hcount, int64_t *o_misc) {
    C_ = ip[0]; T_ = ip[1]; nH_ = ip[2]; nB_ = ip[3]; nR_ = ip[4]; maxlevel_ = ip[5]; min_raw_ = ip[6]; min_n_ = ip[7]; TE_ = ip[8]; test_start_ = ip[9]; split_ = ip[10]; K_ = ip[11]; do_hash_ = ip[12];
    int nth = ip[13]; if (nth > 0) omp_set_num_threads(nth); nth = omp_get_max_threads();
    if (nH_ > MAXH || nB_ > MAXB || nR_ > MAXR || maxlevel_ > MAXL) return -1;
    Bt_ = Bt; fid_ = fid; val_ = val; valn_ = valn; rules_ = rules; hash_cap_ = hash_cap; budget_ = dp[0];
    for (int i = 0; i < nH_; i++) { H_[i] = H[i]; trend_[i] = trend[i]; rowwin_[i] = rowwin[i]; ptop_[i] = ptop[i]; }
    TT_ = T_ - test_start_; if (TT_ < 0) TT_ = 0;
    size_t nc = (size_t)MAXL * nH_ * 2, nrc = (size_t)MAXL * nR_ * nH_ * 2;
    TL *tls = (TL *)calloc(nth, sizeof(TL));
    for (int q = 0; q < nth; q++) {
        TL *t = &tls[q];
        t->hist = calloc(nc * NBIN, 8); t->histn = calloc((size_t)(nB_ ? nB_ : 1) * nc * NBIN, 8); t->sel = calloc(nrc, 8); t->seln = calloc((size_t)(nB_ ? nB_ : 1) * nrc, 8); t->pool = calloc(nrc * 4, 8); t->xpool = calloc((size_t)MAXL * nR_ * nH_ * nH_ * 4, 8);
        t->votes = calloc(nrc * (TT_ ? TT_ : 1), 4); t->toplb = o_toplb + (size_t)q * nc * K_; t->topid = o_topid + (size_t)q * nc * K_ * 4; t->topst = o_topst + (size_t)q * nc * K_ * 4;
        t->hbuf = o_hbuf + (size_t)q * hash_cap; t->hmeta = o_hmeta + (size_t)q * hash_cap; t->hcount = 0;
    }
    stop4_ = 0; t0_ = omp_get_wtime();
    #pragma omp parallel
    {
        TL *t = &tls[omp_get_thread_num()];
        int32_t *A1 = malloc(4 * (size_t)T_), *A2 = malloc(4 * (size_t)T_), *A3 = malloc(4 * (size_t)T_), *A4 = malloc(4 * (size_t)T_);
        int32_t *E1 = malloc(4 * (size_t)T_), *E2 = malloc(4 * (size_t)T_), *E3 = malloc(4 * (size_t)T_), *E4 = malloc(4 * (size_t)T_);
        uint16_t *c2 = malloc(2 * (size_t)C_), *c3 = malloc(2 * (size_t)C_), *c4 = malloc(2 * (size_t)C_);
        int ids[4];
        #pragma omp for schedule(dynamic, 1)
        for (int i = 0; i < C_; i++) {
            int nA1 = 0, nE1 = 0;
            for (int d = 0; d < T_; d++) if (Bt_[(size_t)d * C_ + i]) { if (d < TE_) A1[nA1++] = d; else if (d >= test_start_) E1[nE1++] = d; }
            ids[0] = i; eval_combo(t, 1, ids, A1, nA1, E1, nE1);
            if (maxlevel_ < 2 || nA1 < min_raw_) continue;
            count_ext(A1, nA1, i + 1, c2);
            for (int j = i + 1; j < C_; j++) {
                if (c2[j] < min_raw_ || fid_[j] == fid_[i]) continue;
                int nA2, nE2; split_list(A1, nA1, j, A2, &nA2); split_list(E1, nE1, j, E2, &nE2);
                ids[1] = j; eval_combo(t, 2, ids, A2, nA2, E2, nE2);
                if (maxlevel_ < 3) continue;
                count_ext(A2, nA2, j + 1, c3);
                for (int k = j + 1; k < C_; k++) {
                    if (c3[k] < min_raw_ || fid_[k] == fid_[i] || fid_[k] == fid_[j]) continue;
                    int nA3, nE3; split_list(A2, nA2, k, A3, &nA3); split_list(E2, nE2, k, E3, &nE3);
                    ids[2] = k; eval_combo(t, 3, ids, A3, nA3, E3, nE3);
                    if (maxlevel_ < 4) continue;
                    t->l3total++;
                    if (stop4_) continue;
                    if ((t->l3total & 255) == 0 && budget_ > 0 && omp_get_wtime() - t0_ > budget_) { stop4_ = 1; continue; }
                    t->l3expanded++;
                    count_ext(A3, nA3, k + 1, c4);
                    for (int l = k + 1; l < C_; l++) {
                        if (c4[l] < min_raw_ || fid_[l] == fid_[i] || fid_[l] == fid_[j] || fid_[l] == fid_[k]) continue;
                        int nA4, nE4; split_list(A3, nA3, l, A4, &nA4); split_list(E3, nE3, l, E4, &nE4);
                        ids[3] = l; eval_combo(t, 4, ids, A4, nA4, E4, nE4);
                    }
                }
            }
        }
        free(A1); free(A2); free(A3); free(A4); free(E1); free(E2); free(E3); free(E4); free(c2); free(c3); free(c4);
    }
    for (int q = 0; q < nth; q++) {
        TL *t = &tls[q];
        for (int L = 1; L <= MAXL; L++) o_enum[L] += t->enumc[L];
        for (size_t x = 0; x < nc * NBIN; x++) o_hist[x] += t->hist[x];
        for (size_t x = 0; x < (size_t)nB_ * nc * NBIN; x++) o_histn[x] += t->histn[x];
        for (size_t x = 0; x < nrc; x++) o_sel[x] += t->sel[x];
        for (size_t x = 0; x < (size_t)nB_ * nrc; x++) o_seln[x] += t->seln[x];
        for (size_t x = 0; x < nrc * 4; x++) o_pool[x] += t->pool[x];
        for (size_t x = 0; x < (size_t)MAXL * nR_ * nH_ * nH_ * 4; x++) o_xpool[x] += t->xpool[x];
        for (size_t x = 0; x < nrc * (size_t)TT_; x++) o_votes[x] += t->votes[x];
        o_hcount[q] = t->hcount; o_misc[1] += t->l3total; o_misc[2] += t->l3expanded;
        free(t->hist); free(t->histn); free(t->sel); free(t->seln); free(t->pool); free(t->xpool); free(t->votes);
    }
    o_misc[0] = stop4_; o_misc[3] = nth; o_misc[4] = (int64_t)((omp_get_wtime() - t0_) * 1000);
    free(tls);
    return 0;
}
