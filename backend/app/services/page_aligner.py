from dataclasses import dataclass
import difflib
import re
from app.domain.document_structure import ParsedPage


@dataclass(frozen=True, slots=True)
class AlignedPageRow:
    row_id: int
    pages: dict[str, ParsedPage]
    similarity_score: float
    sequence_matcher_ratio: float


class PageAligner:
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
    def calculate_weighted_similarity(cls, text_a: str, text_b: str) -> float:
        words_a = set(text_a.split())
        words_b = set(text_b.split())
        word_jaccard = cls._jaccard(words_a, words_b)

        ngrams_a = cls._ngrams(text_a, 4)
        ngrams_b = cls._ngrams(text_b, 4)
        ngram_jaccard = cls._jaccard(ngrams_a, ngrams_b)

        return 0.45 * word_jaccard + 0.55 * ngram_jaccard

    @staticmethod
    def calculate_sequence_matcher_ratio(text_a: str, text_b: str) -> float:
        return difflib.SequenceMatcher(None, text_a, text_b, autojunk=False).ratio()

    def align_parallel_ranges(
        self, version_pages: dict[str, list[ParsedPage]]
    ) -> list[AlignedPageRow]:
        """Aligns corresponding pages assuming parallel slices of equal length."""
        stages = list(version_pages.keys())
        if not stages:
            return []

        min_len = min(len(pages) for pages in version_pages.values())
        rows: list[AlignedPageRow] = []

        for i in range(min_len):
            row_pages = {stage: version_pages[stage][i] for stage in stages}

            # Calculate pairwise similarity across all combinations
            w_sims: list[float] = []
            s_sims: list[float] = []

            for idx_a in range(len(stages)):
                for idx_b in range(idx_a + 1, len(stages)):
                    st_a, st_b = stages[idx_a], stages[idx_b]
                    t_a = row_pages[st_a].normalized_text
                    t_b = row_pages[st_b].normalized_text
                    w_sims.append(self.calculate_weighted_similarity(t_a, t_b))
                    s_sims.append(self.calculate_sequence_matcher_ratio(t_a, t_b))

            avg_w = sum(w_sims) / len(w_sims) if w_sims else 1.0
            avg_s = sum(s_sims) / len(s_sims) if s_sims else 1.0

            rows.append(
                AlignedPageRow(
                    row_id=i + 1,
                    pages=row_pages,
                    similarity_score=avg_w,
                    sequence_matcher_ratio=avg_s,
                )
            )

        return rows

    def find_best_matching_page(
        self, target_page: ParsedPage, candidate_pages: list[ParsedPage]
    ) -> tuple[ParsedPage, float]:
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
