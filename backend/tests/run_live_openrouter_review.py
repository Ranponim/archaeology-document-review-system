import os
import sys
import time
import json
import asyncio
from pathlib import Path

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Load .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

from app.services.openrouter_client import OpenRouterConfig, OpenRouterClient
from app.services.ai_review_service import AIReviewService
from app.services.vlm_review_service import VLMReviewService
from app.services.asset_cache import AssetHashCache
from app.services.image_processor import ImageProcessor
from app.domain.document_structure import ParsedPage, TextBlockData, CaptionData


def _find_repo_root() -> Path:
    p = Path(__file__).resolve()
    for parent in p.parents:
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("Could not find repository root containing src/ directory")


REPO_ROOT = _find_repo_root()
PLATES_DIR = REPO_ROOT / "src/도판(사진들)"


async def run_live_test():
    print("=" * 80)
    print("       [실제 OpenRouter API 키 연동: 라이브 LLM & VLM 실증 분석 테스트]       ")
    print("=" * 80)

    config = OpenRouterConfig.from_env()
    masked_key = (config.api_key[:8] + "..." + config.api_key[-4:]) if config.api_key else "없음"
    print(f"• OpenRouter API Key 설정 여부 : {'성공 (Key: ' + masked_key + ')' if config.api_key else '실패 (Key 없음)'}")
    print(f"• Base URL                     : {config.base_url}")
    print(f"• 대상 모델 (Model)            : {config.model}")
    print("=" * 80 + "\n")

    if not config.api_key:
        print("❌ 오류: .env에 OPENROUTER_API_KEY가 없습니다. 확인해 주세요.")
        return

    # -------------------------------------------------------------
    # Test 1: Real Live LLM Text Analysis (고고학 문맥 분석)
    # -------------------------------------------------------------
    print("[1/2] 실제 라이브 LLM(GPT-5.6 LUNA) 고고학 문맥 분석 요청 중...")
    
    ai_service = AIReviewService(model=config.model)
    sample_page = ParsedPage(
        physical_page=30,
        printed_page=26,
        header="115집 논산 산노리 산17-1번지 유적 | 26",
        raw_text="2) 4지점(도면 : , 도판 : ) 4지점 내 퇴적층은 지형의 흐름을 따라 동에서 서쪽으로 가면서 해발고도가 차츰 낮아지는 퇴적 양상을 보여준다. 조사 결과 확인된 층준은 토양화된 부식토층 → 암황갈색 사질점토+쐐기층 → 적갈색 사질점토+쐐기층 → 암갈색 점토층의 순으로 쐐기포함층과 퇴적토가 반복되는 양상을 보인다. 유적 전반에서 쐐기포함층이 반복되어 확인되지만 유물포함층으로 추정되는 갈색 점토계열 퇴적층에서 수성퇴적의 흔적이 나타나는 점으로 미루어볼 때, 4지점은 고토양층이 잔존하고 있었으나 풍화암반토(생토) 포함여부 확인이 필요하다.",
        normalized_text="2) 4지점(도면 : , 도판 : ) 4지점 내 퇴적층은...",
        text_blocks=[
            TextBlockData(block_id="p30_b1", text="2) 4지점(도면 : , 도판 : )", normalized_text="2) 4지점(도면 : , 도판 : )", order=1),
            TextBlockData(block_id="p30_b2", text="풍화암반토(생토) 포함여부 확인이 필요하다.", normalized_text="풍화암반토(생토) 포함여부 확인이 필요하다.", order=2),
        ],
        captions=[
            CaptionData(caption_id="p30_c1", raw_text="2) 4지점(도면 : , 도판 : )", is_blank_reference=True)
        ]
    )

    t0 = time.time()
    try:
        llm_result = await ai_service.analyze_page("project_live_test", "1차", sample_page)
        t_llm = time.time() - t0
        print(f"  -> 라이브 LLM 응답 수신 성공! ({t_llm:.2f}초 소요)")
        print(f"  • 소모 토큰: 입력 {llm_result.prompt_tokens} tok / 출력 {llm_result.completion_tokens} tok (총 {llm_result.total_tokens} tok)")
        print(f"  • 추출된 교정 후보 수: {len(llm_result.candidates)}건\n")
        for idx, cand in enumerate(llm_result.candidates, 1):
            print(f"     [{idx}] 분류: {cand.rule_category} | 원문: {cand.original_text}")
            print(f"         제안: {cand.proposed_text}")
            print(f"         근거: {cand.evidence.rationale}")
    except Exception as e:
        print(f"  ❌ LLM 호출 실패: {e}")
        import traceback
        traceback.print_exc()

    print("\n" + "-" * 80 + "\n")

    # -------------------------------------------------------------
    # Test 2: Real Live VLM Multimodal Analysis (실제 발굴 사진 시각 판독)
    # -------------------------------------------------------------
    print("[2/2] 실제 라이브 VLM(GPT-5.6 LUNA) 발굴 사진 표찰·방위 시각 판독 요청 중...")
    
    # Find a real plate image in src/도판(사진들)
    sample_images = list(PLATES_DIR.glob("**/*.jpg")) + list(PLATES_DIR.glob("**/*.JPG")) + list(PLATES_DIR.glob("**/*.png"))
    
    if sample_images:
        sample_img_path = sample_images[0]
        print(f"  • 테스트 대상 실제 사진: {sample_img_path.name} (크기: {sample_img_path.stat().st_size / 1024:.1f} KB)")
        
        raw_bytes = sample_img_path.read_bytes()
        compressed_bytes = ImageProcessor.prepare_for_vlm(raw_bytes, max_dimension=768, quality=75)
        print(f"  • 스마트 크롭/압축 완료 : {len(compressed_bytes) / 1024:.1f} KB (전송 데이터 최적화)")

        cache_dir = Path("/tmp/archaeology_live_cache")
        cache = AssetHashCache(cache_dir=cache_dir)
        vlm_service = VLMReviewService(cache=cache, model=config.model)

        t1 = time.time()
        try:
            vlm_result = await vlm_service.verify_plate_photo(
                image_bytes=compressed_bytes,
                expected_feature="토광묘",
                expected_site="2지점"
            )
            t_vlm = time.time() - t1
            print(f"  -> 라이브 VLM 응답 수신 성공! ({t_vlm:.2f}초 소요)")
            print(f"  • 소모 토큰    : 입력 {vlm_result.prompt_tokens} tok / 출력 {vlm_result.completion_tokens} tok")
            print(f"  • 표찰 텍스트  : '{vlm_result.label_detected}'")
            print(f"  • 유구 식별번호: '{vlm_result.feature_number}'")
            print(f"  • 방위(방향)   : '{vlm_result.compass_north}'")
            print(f"  • 일치 여부    : {'일치 (MATCH)' if vlm_result.is_match else '불일치 / 검토 필요'}")
            print(f"  • 판독 근거    : {vlm_result.rationale}")
        except Exception as e:
            print(f"  ❌ VLM 호출 실패: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("  ⚠️ 도판 사진 파일을 찾을 수 없습니다.")

    print("\n" + "=" * 80)
    print("                     [라이브 API 연동 실증 완료]                     ")
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_live_test())
