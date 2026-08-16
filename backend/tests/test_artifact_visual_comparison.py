import os
import sys
import time
import json
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def find_repo_root():
    p = Path(".").resolve()
    for parent in [p] + list(p.parents):
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("root not found")

root = find_repo_root()
load_dotenv(root / ".env")
load_dotenv(root / ".worktrees/windows-docker-foundation/.env")

from app.services.openrouter_client import OpenRouterConfig
from app.services.image_processor import ImageProcessor
import httpx


async def run_artifact_visual_comparison():
    print("=" * 80)
    print("   [고고학 유물 실물 사진 vs 본문 제원·형상 서술 시각 정밀 대조 분석]   ")
    print("=" * 80)

    config = OpenRouterConfig.from_env()
    print(f"• 모델: {config.model}")
    print(f"• 대상: 실제 발굴 유물 사진 vs 1차 보고서 37쪽 유물 실측 기술문\n")

    # 1. Real artifact photo (e.g. 석기/도구 사진)
    plates_dir = root / "src/도판(사진들)"
    imgs = list(plates_dir.glob("**/*.jpg")) + list(plates_dir.glob("**/*.JPG"))
    if not imgs:
        print("도판 사진이 없습니다.")
        return

    # Select an artifact photo (e.g. photo 7 (3).jpg or 23 (2).jpg)
    img_path = imgs[5] # 7 (3).jpg
    print(f"• 분석 대상 사진 파일: {img_path.name}")
    raw_bytes = img_path.read_bytes()
    compressed_bytes = ImageProcessor.prepare_for_vlm(raw_bytes, max_dimension=768, quality=75)

    # 2. Text description from report (1차 p.37)
    artifact_description = """
    [본문 유물 1번 서술]
    - 명칭: 찍개 (Chopper)
    - 제원: 길이 12.7cm, 너비 10.7cm, 두께 7.9cm, 무게 1,146g
    - 재질 및 색조: 회백색/백색 석영 자갈(Quartz pebble)로 제작
    - 형태적 특징: 
      1) 평면 형태는 물방울형(tear-drop)에 가까움.
      2) 상단부에는 미약한 수준의 첨두부가 존재하며 좌우에 가파른 각도의 찍는날(chopping edge) 존재.
      3) 하단부는 자연면(cortex)으로 이루어져 둥근 형태.
      4) 배면 상단의 편평한 자연면을 단면 가공하여 찍는날 형성. 박리흔 일부 확인.
    """

    print("--------------------------------------------------------------------------------")
    print("• 본문 서술 내용:")
    print(artifact_description.strip())
    print("--------------------------------------------------------------------------------\n")

    # 3. Call GPT-5.6 LUNA VLM for Deep Archaeological Morphological Comparison
    import base64
    b64_image = base64.b64encode(compressed_bytes).decode("utf-8")
    image_data_uri = f"data:image/jpeg;base64,{b64_image}"

    prompt = f"""
    당신은 고고학 유물 감정 및 보고서 검수 최고 전문가입니다.
    첨부된 [실제 유물 사진]을 정밀 관찰하고, 아래 [본문 서술 내용]과 시각적으로 대조하여 분석 리포트를 작성하십시오.

    {artifact_description}

    다음 항목들을 상세히 비교하여 JSON 형식으로 출력하십시오:
    1. artifact_type_observed: 사진 속 유물의 실제 관찰된 종류/형태
    2. material_and_color_match: 재질(석영/자갈 등) 및 색상(회백색 등) 일치 여부 및 시각적 특징
    3. morphology_comparison:
       - 형태(물방울형 여부): 일치/불일치 및 설명
       - 가공흔/날(찍는날, 박리흔, 자연면 잔존): 시각적 관찰 결과
    4. discrepancy_found: 본문 서술과 사진 간의 불일치점 또는 의심되는 오류 (예: 사진 속 유물이 다른 번호 유물이거나 서술과 다른 부분)
    5. final_verdict: "일치(MATCH)", "부분일치(PARTIAL)", "불일치(MISMATCH)" 중 하나
    6. expert_comment: 고고학 연구원을 위한 종합 검토 소견

    반드시 JSON 형식으로만 응답하십시오.
    """

    payload = {
        "model": config.model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data_uri, "detail": "low"}}
                ]
            }
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"}
    }

    headers = {
        "Authorization": f"Bearer {config.api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Ranponim/archaeology-document-review-system",
        "X-Title": "Archaeology Artifact Comparison"
    }

    print("• GPT-5.6 LUNA VLM 실물 형상 대조 분석 진행 중 (API 호출)...")
    t0 = time.time()
    async with httpx.AsyncClient(timeout=30.0) as client:
        endpoint = config.base_url
        if not endpoint.endswith("/chat/completions") and not endpoint.endswith("/responses"):
            endpoint = endpoint.rstrip("/") + "/chat/completions"
        resp = await client.post(endpoint, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    t_elapsed = time.time() - t0
    content = data["choices"][0]["message"]["content"]
    usage = data.get("usage", {})

    print(f"-> 분석 완료 ({t_elapsed:.2f}초 소요, 소모 토큰: {usage.get('total_tokens', 0)} tok)\n")
    print("=" * 80)
    print("                     [AI 고고학 시각 정밀 대조 결과]                     ")
    print("=" * 80)

    try:
        from app.services.json_utils import strip_markdown_json
        parsed = json.loads(strip_markdown_json(content))
        print(f"1. 관찰된 유물 유형 : {parsed.get('artifact_type_observed')}")
        print(f"2. 재질 및 색상     : {parsed.get('material_and_color_match')}")
        print(f"3. 형상 및 가공흔 대조:")
        morph = parsed.get('morphology_comparison', {})
        if isinstance(morph, dict):
            for k, v in morph.items():
                print(f"   • {k}: {v}")
        else:
            print(f"   • {morph}")
        print(f"4. 발견된 불일치점  : {parsed.get('discrepancy_found')}")
        print(f"5. 최종 판정 (Verdict): {parsed.get('final_verdict')}")
        print(f"6. 연구원 권고 사항 : {parsed.get('expert_comment')}")
    except Exception:
        print(content)
    print("=" * 80)


if __name__ == "__main__":
    asyncio.run(run_artifact_visual_comparison())
