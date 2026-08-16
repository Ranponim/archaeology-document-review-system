import os
import sys
from pathlib import Path

# Ensure backend root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

def find_repo_root():
    p = Path(".").resolve()
    for parent in [p] + list(p.parents):
        if (parent / "src").is_dir() and (parent / "README.md").is_file():
            return parent
    raise RuntimeError("root not found")

root = find_repo_root()
from app.services.image_processor import ImageProcessor

# Output directory
out_dir = root / "docs/sample_vlm_processed_images"
out_dir.mkdir(parents=True, exist_ok=True)

# Also worktree docs
out_dir_worktree = root / ".worktrees/windows-docker-foundation/docs/sample_vlm_processed_images"
out_dir_worktree.mkdir(parents=True, exist_ok=True)

TEST_CASES = [
    ("case01_p33_chopper_7_3.jpg", "src/도판(사진들)/Links/7 (3).jpg"),
    ("case02_p34_sidescraper_7_1.jpg", "src/도판(사진들)/Links/7 (1).jpg"),
    ("case03_p35_notch_7_2.jpg", "src/도판(사진들)/Links/7 (2).jpg"),
    ("case04_p36_pestle_8_1.jpg", "src/도판(사진들)/Links/8 (1).jpg"),
    ("case05_p67_pottery_jar_23_2.jpg", "src/도판(사진들)/Links/23 (2).jpg"),
    ("case06_p68_pottery_base_23_1.jpg", "src/도판(사진들)/Links/23 (1).jpg"),
    ("case07_p54_stone_cist_3_1.jpg", "src/도판(사진들)/Links/3 (1).jpg"),
    ("case08_p87_pit_tomb_14_3.jpg", "src/도판(사진들)/Links/14 (3).jpg"),
    ("case09_p97_section_19_1.jpg", "src/도판(사진들)/Links/19 (1).jpg"),
    ("case10_p101_bottom_stone_22_3.jpg", "src/도판(사진들)/Links/22 (3).jpg"),
]

print("=" * 70)
print("   [VLM 실제 전송용 768px 축소 사진 10장 디스크 저장 중...]   ")
print("=" * 70)

saved_files = []
for filename, rel_path in TEST_CASES:
    src_file = root / rel_path
    if not src_file.is_file():
        sample_imgs = list((root / "src/도판(사진들)").glob("**/*.jpg"))
        src_file = sample_imgs[0]

    raw_bytes = src_file.read_bytes()
    prep_bytes = ImageProcessor.prepare_for_vlm(raw_bytes, max_dimension=768, quality=75)

    dest_file1 = out_dir / filename
    dest_file2 = out_dir_worktree / filename
    dest_file1.write_bytes(prep_bytes)
    dest_file2.write_bytes(prep_bytes)

    orig_kb = len(raw_bytes) / 1024.0
    prep_kb = len(prep_bytes) / 1024.0
    saved_files.append((filename, orig_kb, prep_kb, dest_file1))
    print(f"• 저장됨: {filename} (원본 {orig_kb:.1f} KB -> VLM용 {prep_kb:.1f} KB)")

print("\n" + "=" * 70)
print(f"총 {len(saved_files)}장의 VLM 전송 이미지가 다음 폴더에 저장되었습니다:")
print(f"  📁 {out_dir}")
print("=" * 70)
