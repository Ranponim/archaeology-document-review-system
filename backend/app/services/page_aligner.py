from dataclasses import dataclass
import difflib
from enum import Enum
import re
from app.domain.document_structure import ParsedPage


class AlignmentStatus(str, Enum):
    EXACT = "exact"
    PROBABLE = "probable"
    MANUAL_REVIEW = "manual_review"
    UNMATCHED = "unmatched"


@dataclass(frozen=True, slots=True)
class AlignedPagePair:
    page_a: ParsedPage | None
    page_b: ParsedPage | None
    similarity_score: float
    status: AlignmentStatus | str
    method: str = "dtw_weighted"


@dataclass(frozen=True, slots=True)
class AlignedPageRow:
    row_id: int
    pages: dict[str, ParsedPage | None]
    similarity_score: float
    sequence_matcher_ratio: float
    status: AlignmentStatus | str = AlignmentStatus.UNMATCHED



class PageAligner:
    EXACT_THRESHOLD: float = 0.85
    PROBABLE_THRESHOLD: float = 0.60
    MANUAL_REVIEW_THRESHOLD: float = 0.30

    @classmethod
    def classify_status(
        cls,
        similarity: float,
        has_gap: bool = False,
        exact_threshold: float = EXACT_THRESHOLD,
        probable_threshold: float = PROBABLE_THRESHOLD,
        manual_review_threshold: float = MANUAL_REVIEW_THRESHOLD,
    ) -> AlignmentStatus:
        """Classify alignment status based on similarity score and gap presence."""
        if has_gap or similarity < manual_review_threshold:
            return AlignmentStatus.UNMATCHED
        if similarity >= exact_threshold:
            return AlignmentStatus.EXACT
        if similarity >= probable_threshold:
            return AlignmentStatus.PROBABLE
        return AlignmentStatus.MANUAL_REVIEW

    @staticmethod
    def _clean_for_ngrams(text: str) -> str:
        return re.sub(r"\s+", "", text)

    @classmethod
    def _ngrams(cls, text: str, n: int = 4) -> set[str]:
        clean = cls._clean_for_ngrams(text)
        if len(clean) < n:
            return {clean} if clean else set()
        return {clean[i : i + n] for i in range(len(clean) - n + 1)}

    @staticmethod
    def _jaccard(set_a: set, set_b: set) -> float:
        if not set_a and not set_b:
            return 1.0
        if not set_a or not set_b:
            return 0.0
        return len(set_a & set_b) / len(set_a | set_b)

    @classmethod
    def _jaccard_similarity(cls, set_a: set, set_b: set) -> float:
        return cls._jaccard(set_a, set_b)

    @classmethod
    def calculate_weighted_similarity(cls, text_a: str, text_b: str) -> float:
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        word_jaccard = cls._jaccard(words_a, words_b)

        ngrams_a = cls._ngrams(text_a, 4)
        ngrams_b = cls._ngrams(text_b, 4)
        ngram_jaccard = cls._jaccard(ngrams_a, ngrams_b)

        return 0.45 * word_jaccard + 0.55 * ngram_jaccard

    @classmethod
    def weighted_similarity(
        cls, a: str | ParsedPage, b: str | ParsedPage
    ) -> float:
        text_a = a.normalized_text if isinstance(a, ParsedPage) else a
        text_b = b.normalized_text if isinstance(b, ParsedPage) else b
        return cls.calculate_weighted_similarity(text_a, text_b)

    @staticmethod
    def calculate_sequence_matcher_ratio(text_a: str, text_b: str) -> float:
        return difflib.SequenceMatcher(None, text_a, text_b, autojunk=False).ratio()

    @classmethod
    def _page_features(cls, page: ParsedPage) -> tuple[set[str], set[str]]:
        text = page.normalized_text
        words = set(text.split())
        ngrams = cls._ngrams(text, 4)
        return words, ngrams

    @classmethod
    def _similarity_from_features(
        cls,
        feat_a: tuple[set[str], set[str]],
        feat_b: tuple[set[str], set[str]],
    ) -> float:
        words_a, ngrams_a = feat_a
        words_b, ngrams_b = feat_b
        word_jaccard = cls._jaccard(words_a, words_b)
        ngram_jaccard = cls._jaccard(ngrams_a, ngrams_b)
        return 0.45 * word_jaccard + 0.55 * ngram_jaccard

    def _align_pairwise_dtw(
        self,
        ref_pages: list[ParsedPage],
        other_pages: list[ParsedPage],
        gap_cost: float = 1.0,
    ) -> list[tuple[ParsedPage | None, ParsedPage | None]]:
        n = len(ref_pages)
        m = len(other_pages)

        if n == 0 and m == 0:
            return []
        if n == 0:
            return [(None, page) for page in other_pages]
        if m == 0:
            return [(page, None) for page in ref_pages]

        # Precompute features for fast similarity calculation
        ref_feats = [self._page_features(p) for p in ref_pages]
        other_feats = [self._page_features(p) for p in other_pages]

        # Compute similarity matrix: sim[i][j] in [0, 1]
        sim = [
            [
                self._similarity_from_features(ref_feats[i], other_feats[j])
                for j in range(m)
            ]
            for i in range(n)
        ]

        # Build (n + 1) x (m + 1) DTW cost matrix
        # D[i][j] represents optimal alignment cost of prefixes ref_pages[:i] and other_pages[:j]
        D = [[0.0] * (m + 1) for _ in range(n + 1)]
        for i in range(1, n + 1):
            D[i][0] = D[i - 1][0] + gap_cost
        for j in range(1, m + 1):
            D[0][j] = D[0][j - 1] + gap_cost

        for i in range(1, n + 1):
            for j in range(1, m + 1):
                match_cost = 1.0 - sim[i - 1][j - 1]
                D[i][j] = min(
                    D[i - 1][j - 1] + match_cost,  # Match (both advance)
                    D[i - 1][j] + gap_cost,        # Deletion (ref page skipped in other)
                    D[i][j - 1] + gap_cost,        # Insertion (extra page in other)
                )

        # Backtrack from (n, m) to (0, 0)
        i, j = n, m
        alignment: list[tuple[ParsedPage | None, ParsedPage | None]] = []

        while i > 0 or j > 0:
            if i > 0 and j > 0:
                match_cost = 1.0 - sim[i - 1][j - 1]
                diag_cost = D[i - 1][j - 1] + match_cost
                up_cost = D[i - 1][j] + gap_cost
                left_cost = D[i][j - 1] + gap_cost

                diag_optimal = abs(D[i][j] - diag_cost) < 1e-9
                up_optimal = abs(D[i][j] - up_cost) < 1e-9
                left_optimal = abs(D[i][j] - left_cost) < 1e-9

                # Prefer a real match only when the diagonal similarity clears
                # the manual-review floor. Never manufacture a match for
                # unrelated pages: when the diagonal is below the floor, prefer
                # a gap over the diagonal even when their costs tie (plan Task 8
                # DTW fix). A unique-min diagonal below the floor is kept
                # (cost-optimal) and reclassified by the post-pass.
                if diag_optimal and sim[i - 1][j - 1] >= self.MANUAL_REVIEW_THRESHOLD:
                    alignment.append((ref_pages[i - 1], other_pages[j - 1]))
                    i -= 1
                    j -= 1
                elif up_optimal:
                    alignment.append((ref_pages[i - 1], None))
                    i -= 1
                elif left_optimal:
                    alignment.append((None, other_pages[j - 1]))
                    j -= 1
                elif diag_optimal:
                    alignment.append((ref_pages[i - 1], other_pages[j - 1]))
                    i -= 1
                    j -= 1
                else:
                    if up_cost <= left_cost:
                        alignment.append((ref_pages[i - 1], None))
                        i -= 1
                    else:
                        alignment.append((None, other_pages[j - 1]))
                        j -= 1
            elif i > 0:
                alignment.append((ref_pages[i - 1], None))
                i -= 1
            else:
                alignment.append((None, other_pages[j - 1]))
                j -= 1

        alignment.reverse()
        return alignment

    def align_parallel_ranges(
        self, version_pages: dict[str, list[ParsedPage]]
    ) -> list[AlignedPageRow]:
        """Aligns corresponding pages across versions using Dynamic Time Warping (DTW)."""
        stages = list(version_pages.keys())
        if not stages:
            return []

        ref_stage = stages[0]
        ref_pages = version_pages[ref_stage]

        if len(stages) == 1:
            raw_rows: list[dict[str, ParsedPage | None]] = [
                {ref_stage: page} for page in ref_pages
            ]
        else:
            other_stages = stages[1:]
            n_ref = len(ref_pages)

            insertions_before: dict[str, list[list[ParsedPage]]] = {
                st: [[] for _ in range(n_ref)] for st in other_stages
            }
            matched_ref: dict[str, list[ParsedPage | None]] = {
                st: [None for _ in range(n_ref)] for st in other_stages
            }
            trailing_insertions: dict[str, list[ParsedPage]] = {
                st: [] for st in other_stages
            }

            for st in other_stages:
                pairs = self._align_pairwise_dtw(ref_pages, version_pages[st])
                ref_idx = 0
                for r_page, o_page in pairs:
                    if r_page is not None:
                        matched_ref[st][ref_idx] = o_page
                        ref_idx += 1
                    else:
                        if ref_idx < n_ref:
                            if o_page is not None:
                                insertions_before[st][ref_idx].append(o_page)
                        else:
                            if o_page is not None:
                                trailing_insertions[st].append(o_page)

            raw_rows = []

            for i in range(n_ref):
                max_ins = max(
                    (len(insertions_before[st][i]) for st in other_stages),
                    default=0,
                )
                for slot in range(max_ins):
                    row: dict[str, ParsedPage | None] = {ref_stage: None}
                    for st in other_stages:
                        ins_list = insertions_before[st][i]
                        row[st] = ins_list[slot] if slot < len(ins_list) else None
                    raw_rows.append(row)

                row_ref: dict[str, ParsedPage | None] = {ref_stage: ref_pages[i]}
                for st in other_stages:
                    row_ref[st] = matched_ref[st][i]
                raw_rows.append(row_ref)

            max_trail = max(
                (len(trailing_insertions[st]) for st in other_stages),
                default=0,
            )
            for slot in range(max_trail):
                row_trail: dict[str, ParsedPage | None] = {ref_stage: None}
                for st in other_stages:
                    trail_list = trailing_insertions[st]
                    row_trail[st] = trail_list[slot] if slot < len(trail_list) else None
                raw_rows.append(row_trail)

        rows: list[AlignedPageRow] = []
        for idx, row_pages in enumerate(raw_rows):
            w_sims: list[float] = []
            s_sims: list[float] = []

            for idx_a in range(len(stages)):
                for idx_b in range(idx_a + 1, len(stages)):
                    st_a, st_b = stages[idx_a], stages[idx_b]
                    page_a = row_pages.get(st_a)
                    page_b = row_pages.get(st_b)
                    if page_a is not None and page_b is not None:
                        t_a = page_a.normalized_text
                        t_b = page_b.normalized_text
                        w_sims.append(self.calculate_weighted_similarity(t_a, t_b))
                        s_sims.append(self.calculate_sequence_matcher_ratio(t_a, t_b))

            has_gap = any(row_pages.get(st) is None for st in stages)

            if w_sims:
                avg_w = sum(w_sims) / len(w_sims)
                avg_s = sum(s_sims) / len(s_sims)
                min_w = min(w_sims)
                if min_w < self.MANUAL_REVIEW_THRESHOLD:
                    status = AlignmentStatus.UNMATCHED
                elif has_gap:
                    status = AlignmentStatus.UNMATCHED
                else:
                    status = self.classify_status(avg_w, has_gap=has_gap)
            else:
                if len(stages) <= 1:
                    avg_w = 1.0
                    avg_s = 1.0
                    status = AlignmentStatus.EXACT
                else:
                    avg_w = 0.0
                    avg_s = 0.0
                    status = AlignmentStatus.UNMATCHED

            rows.append(
                AlignedPageRow(
                    row_id=idx + 1,
                    pages=row_pages,
                    similarity_score=avg_w,
                    sequence_matcher_ratio=avg_s,
                    status=status,
                )
            )

        return rows

    def align_page_pair(
        self,
        page_a: ParsedPage | None,
        page_b: ParsedPage | None,
        method: str = "weighted_similarity",
    ) -> AlignedPagePair:
        """Aligns a single pair of pages with similarity score and status."""
        if page_a is None or page_b is None:
            return AlignedPagePair(
                page_a=page_a,
                page_b=page_b,
                similarity_score=0.0,
                status=AlignmentStatus.UNMATCHED,
                method=method,
            )
        sim = self.calculate_weighted_similarity(
            page_a.normalized_text, page_b.normalized_text
        )
        status = self.classify_status(sim)
        return AlignedPagePair(
            page_a=page_a,
            page_b=page_b,
            similarity_score=sim,
            status=status,
            method=method,
        )

    def align_pairwise(
        self,
        pages_a: list[ParsedPage],
        pages_b: list[ParsedPage],
        gap_cost: float = 1.0,
        method: str = "dtw_weighted",
    ) -> list[AlignedPagePair]:
        """Aligns two lists of pages using DTW and returns a list of AlignedPagePair."""
        pairs = self._align_pairwise_dtw(pages_a, pages_b, gap_cost=gap_cost)
        result: list[AlignedPagePair] = []
        for p_a, p_b in pairs:
            if p_a is None or p_b is None:
                sim = 0.0
                status = AlignmentStatus.UNMATCHED
            else:
                sim = self.calculate_weighted_similarity(
                    p_a.normalized_text, p_b.normalized_text
                )
                status = self.classify_status(sim)
            result.append(
                AlignedPagePair(
                    page_a=p_a,
                    page_b=p_b,
                    similarity_score=sim,
                    status=status,
                    method=method,
                )
            )
        return result

    def find_best_matching_page(
        self, target_page: ParsedPage, candidate_pages: list[ParsedPage]
    ) -> tuple[ParsedPage, float]:
        if not candidate_pages:
            raise ValueError("candidate_pages cannot be empty")
        best_page = candidate_pages[0]
        best_score = -1.0

        for cand in candidate_pages:
            score = self.calculate_weighted_similarity(
                target_page.normalized_text, cand.normalized_text
            )
            if score > best_score:
                best_score = score
                best_page = cand

        return best_page, best_score
