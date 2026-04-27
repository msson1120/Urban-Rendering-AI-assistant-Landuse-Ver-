# app_landuse.py
# PlanVision AI v2 — 토지이용계획도 기반 도시개발 조감도 자동생성
# 입력: 토지이용계획도 + 위성사진(선택) + 토지이용계획표 (RGB 매핑)
# 3-STEP: PASS1(2D배치도) → PASS2(3D조감도) → PASS3(각도변환)

from io import BytesIO

import streamlit as st
from PIL import Image, ImageDraw, ImageFilter

# ── 선택적 의존성 ──────────────────────────────────────────────
GENAI_AVAILABLE = True
GENAI_TYPES_AVAILABLE = True
try:
    from google import genai
    try:
        from google.genai import types  # type: ignore
    except Exception:
        GENAI_TYPES_AVAILABLE = False
except Exception:
    GENAI_AVAILABLE = False
    GENAI_TYPES_AVAILABLE = False

CV2_AVAILABLE = True
try:
    import cv2  # type: ignore
    import numpy as np  # type: ignore
except Exception:
    CV2_AVAILABLE = False
    np = None  # type: ignore

# ──────────────────────────────────────────────────────────────
# 페이지 설정
# ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="PlanVision AI v2 — 토지이용계획 기반", layout="wide")

st.markdown("""
<style>
:root {
    --primary: #2563EB;
    --primary-light: #EFF6FF;
    --success: #16A34A;
    --border: #E5E7EB;
    --radius: 10px;
}
.block-container { max-width: 1280px; padding: 1.5rem 2rem; margin: 0 auto; }
div[data-testid="stButton"] button { border-radius:8px !important; font-weight:600 !important; }
div[data-testid="stButton"] button[kind="primary"] {
    background:#2563EB !important; border:none !important; color:#fff !important;
}
.section-header {
    font-size: 20px; font-weight: 800; color: #111827;
    border-left: 4px solid #2563EB;
    padding: 10px 16px; background: #EFF6FF;
    border-radius: 0 8px 8px 0; margin: 20px 0 12px 0;
}
.sub-label {
    font-size: 11px; font-weight: 700; color: #9CA3AF;
    letter-spacing: 0.1em; text-transform: uppercase;
    margin: 16px 0 6px 0;
}
[data-testid="stDecoration"] { display:none !important; }
</style>
""", unsafe_allow_html=True)

st.markdown("""
<div style="padding:16px 0 20px 0;">
  <div style="font-size:13px;font-weight:700;color:#2563EB;letter-spacing:.1em;text-transform:uppercase;margin-bottom:6px;">
    KH ENGINEERING · URBAN AI
  </div>
  <div style="font-size:40px;font-weight:900;letter-spacing:-.02em;
    background:linear-gradient(90deg,#111827,#1E40AF);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;line-height:1.1;">
    PlanVision AI <span style="font-size:18px;font-weight:600;opacity:.5;">v2</span>
  </div>
  <div style="font-size:14px;color:#6B7280;margin-top:6px;">
    토지이용계획도 + RGB 매핑 기반 도시개발 조감도 자동생성
  </div>
</div>
<div style="height:3px;background:linear-gradient(90deg,#2563EB,#1E293B 80%);border-radius:2px;margin-bottom:28px;"></div>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────────────────────
MODEL_NAME = "gemini-3.1-flash-image-preview"

STANDARD_LAND_USES = [
    # 주거
    ("단독주택",          (255, 255, 127), "단독주택",                    "저층 단독주택"),
    ("연립·다세대주택",   (255, 230, 100), "연립·다세대주택",             "저~중층 연립"),
    ("공동주택(판상)",    (255, 220,  60), "공동주택(판상형 아파트)",     "판상형 아파트"),
    ("공동주택(타워)",    (255, 180,  30), "공동주택(타워형 아파트)",     "타워형 아파트"),
    ("준주거용지",        (255, 200, 150), "준주거용지",                  "준주거 혼합"),
    ("숙박시설",          (255, 191, 127), "[직접입력]",                  ""),
    ("콘도미니엄",        (159, 127, 255), "[직접입력]",                  ""),
    # 상업·업무
    ("근린생활시설",      (255, 140, 140), "근린생활시설용지",            "근린상가"),
    ("일반상업용지",      (255,  80,  80), "일반상업용지",                "일반상업"),
    ("복합상업시설",      (220,  50,  50), "복합상업시설(대형몰·복합몰)", "복합상업"),
    ("업무시설용지",      (180, 130, 220), "업무시설용지(오피스)",        "오피스"),
    ("복합업무용지",      (150, 100, 200), "복합업무용지(오피스+상업)",   "복합업무"),
    ("R&D·첨단산업",     (130, 100, 180), "첨단산업단지(R&D·지식산업)",  "R&D 캠퍼스"),
    ("6차산업",           (165,  82, 124), "[직접입력]",                  ""),
    ("스마트팜",          (223, 127, 255), "[직접입력]",                  ""),
    ("파머스마켓",        (255,   0, 255), "[직접입력]",                  ""),
    # 공원·녹지
    ("공원",              (  0, 165,   0), "근린공원·주제공원",           "공원녹지"),
    ("녹지·완충녹지",     (191, 255, 127), "근린공원·주제공원",           "완충녹지"),
    ("치유의숲",          (127, 255,   0), "[직접입력]",                  ""),
    ("마을농원",          (145, 165,  82), "[직접입력]",                  ""),
    ("파크골프장",        (103, 165,  82), "[직접입력]",                  ""),
    ("하천·수변",         ( 80, 160, 220), "하천·수변공간",               "수변공간"),
    ("저류지",            (127, 223, 255), "[직접입력]",                  ""),
    ("인피니티풀",        (173, 241, 255), "[직접입력]",                  ""),
    # 공공·편의
    ("공공청사",          (180, 220, 200), "공공청사·행정시설",           "공공청사"),
    ("학교·교육",         (200, 230, 255), "학교·교육시설",               "교육시설"),
    ("의료시설",          (220, 240, 255), "종합의료시설(병원)",          "병원"),
    ("문화시설",          (220, 180, 240), "대규모 문화시설(공연·전시·컨벤션)", "문화시설"),
    ("복지시설",          (165, 165,   0), "[직접입력]",                  ""),
    ("주민편의시설",      (127, 191, 255), "[직접입력]",                  ""),
    ("복합커뮤니티시설",  (255, 159, 127), "[직접입력]",                  ""),
    ("복합문화체육시설",  ( 82, 165, 124), "[직접입력]",                  ""),
    ("버스킹공연장",      (251, 203, 229), "[직접입력]",                  ""),
    # 기반시설
    ("광장·공공공지",     (240, 240, 240), "광장·공공공지",               "광장"),
    ("주차장",            (137, 137, 137), "주차장",                      "주차장"),
    ("도로",              (255, 255, 255), "광장·공공공지",               "도로"),
    ("보행자전용도로",    (165, 124,   0), "[직접입력]",                  ""),
    ("산책로",            (165,  82,   0), "[직접입력]",                  ""),
    # 산업·물류
    ("일반산업단지",      (200, 170, 130), "일반산업단지(공장용지)",      "공장용지"),
    ("물류단지",          (180, 150, 110), "첨단물류단지",                "물류"),
    ("복합용지",          (255, 200, 180), "복합용지(혼합개발)",          "혼합개발"),
]

# ──────────────────────────────────────────────────────────────
# 프리셋
# ──────────────────────────────────────────────────────────────
ZONE_PRESETS_SIMPLE = {
    "단독주택": {
        "Primary Function": "Residential - Detached housing",
        "floor_level": "Low",
        "prompt_note": "Low-rise detached housing, 2~3F, garden plots, private residential character",
    },
    "연립·다세대주택": {
        "Primary Function": "Residential - Attached housing",
        "floor_level": "Low",
        "prompt_note": "Low-to-mid rise attached housing, 3~5F, courtyard arrangement",
    },
    "공동주택(판상형 아파트)": {
        "Primary Function": "Residential - Slab apartment complex",
        "floor_level": "Medium–High",
        "prompt_note": "Slab-type apartment, 8~15F, south-facing orientation, central green space",
    },
    "공동주택(타워형 아파트)": {
        "Primary Function": "Residential - High-rise tower apartment",
        "floor_level": "High",
        "prompt_note": "High-rise point tower apartment, 20~30F, large landscaped podium",
    },
    "준주거용지": {
        "Primary Function": "Quasi-residential mixed-use",
        "floor_level": "Low",
        "prompt_note": "Mixed-use quasi-residential, ground retail with residential above, 3~6F",
    },
    "근린생활시설용지": {
        "Primary Function": "Commercial dominant",
        "floor_level": "Low",
        "prompt_note": "Low-rise neighborhood commercial strip, 2~4F storefronts",
    },
    "일반상업용지": {
        "Primary Function": "Commercial dominant",
        "floor_level": "Medium–High",
        "prompt_note": "General commercial zone, podium-and-tower typology, 8~20F",
    },
    "복합상업시설(대형몰·복합몰)": {
        "Primary Function": "Commercial dominant",
        "floor_level": "Medium–High",
        "prompt_note": "Large-scale mixed commercial complex, COEX style, 10~25F",
    },
    "업무시설용지(오피스)": {
        "Primary Function": "Office dominant",
        "floor_level": "High",
        "prompt_note": "Office tower district, plaza-level retail activation, 15~30F",
    },
    "복합업무용지(오피스+상업)": {
        "Primary Function": "Office + Commercial mixed-use",
        "floor_level": "High",
        "prompt_note": "Mixed office and commercial complex, podium retail with tower, 15~30F",
    },
    "첨단산업단지(R&D·지식산업)": {
        "Primary Function": "Innovation/R&D dominant",
        "floor_level": "Medium",
        "prompt_note": "High-tech R&D campus, courtyard green network, 3~8F",
    },
    "근린공원·주제공원": {
        "Primary Function": "Park / Open space",
        "floor_level": "Very low",
        "prompt_note": "Neighborhood park, tree canopy, walking paths, event lawn, no buildings",
    },
    "하천·수변공간": {
        "Primary Function": "Park / Open space",
        "floor_level": "Very low",
        "prompt_note": "River corridor, riparian planting, boardwalk, water feature visible, no buildings",
    },
    "공공청사·행정시설": {
        "Primary Function": "Civic / Government",
        "floor_level": "Medium",
        "prompt_note": "Civic government building, formal plaza entry, institutional character, 5~12F",
    },
    "학교·교육시설": {
        "Primary Function": "Education",
        "floor_level": "Low",
        "prompt_note": "School campus, playgrounds and sports fields, 2~4F",
    },
    "종합의료시설(병원)": {
        "Primary Function": "Medical / Healthcare",
        "floor_level": "Medium–High",
        "prompt_note": "General hospital complex, tower block with podium, 8~20F",
    },
    "대규모 문화시설(공연·전시·컨벤션)": {
        "Primary Function": "Large-scale cultural / Convention",
        "floor_level": "Medium",
        "prompt_note": "Large cultural landmark: convention center, grand civic plaza",
    },
    "광장·공공공지": {
        "Primary Function": "Open space dominant",
        "floor_level": "Very low",
        "prompt_note": "Civic plaza, paved surface, fountain or public art, no buildings",
    },
    "주차장": {
        "Primary Function": "Parking",
        "floor_level": "Very low",
        "prompt_note": "Surface or structured parking lot, organized layout, 1~3F",
    },
    "일반산업단지(공장용지)": {
        "Primary Function": "General industrial",
        "floor_level": "Low",
        "prompt_note": "General industrial zone, large-footprint factory buildings, low-rise",
    },
    "첨단물류단지": {
        "Primary Function": "Logistics / Distribution",
        "floor_level": "Low",
        "prompt_note": "Advanced logistics center, large-scale warehouse buildings, truck access roads",
    },
    "복합용지(혼합개발)": {
        "Primary Function": "Mixed urban fabric",
        "floor_level": "Medium–High",
        "prompt_note": "Mixed-use development zone, podium base with tower elements",
    },
}

PARK_PF = "Park / Open space"
PRESET_KEYS = list(ZONE_PRESETS_SIMPLE.keys())
PRESET_OPTIONS = ["[직접입력]"] + PRESET_KEYS

# ──────────────────────────────────────────────────────────────
# 세션 초기화
# ──────────────────────────────────────────────────────────────
def ensure_session():
    defs = {
        "step": 0,
        "img_landuse_bytes": None,
        "img_sat_bytes": None,
        "land_use_table": [],
        "site_area_sqm": 100000.0,
        "pass1_outputs": [],
        "pass1_selected_idx": 0,
        "pass1_output_bytes": None,
        "pass2_outputs": [],
        "pass2_selected_idx": 0,
        "pass2_output_bytes": None,
        "pass3_outputs": [],
        "pass3_selected_idx": 0,
        "_auto_colors": [],
        "_errors": [],
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

ensure_session()

# ──────────────────────────────────────────────────────────────
# 기본 테이블
# ──────────────────────────────────────────────────────────────
def make_default_table():
    defaults = [
        ("단독주택",         (255, 255, 127), "단독주택",               "",                                                                  10000.0),
        ("공원",             (  0, 165,   0), "근린공원·주제공원",      "",                                                                  15000.0),
        ("녹지·완충녹지",    (191, 255, 127), "근린공원·주제공원",      "",                                                                   8000.0),
        ("공공청사",         (180, 220, 200), "공공청사·행정시설",      "",                                                                   5000.0),
        ("주차장",           (137, 137, 137), "주차장",                 "",                                                                   3000.0),
        ("숙박시설",         (255, 191, 127), "[직접입력]",             "resort hotel with amenity facilities, 5~10F, warm facade",          12000.0),
        ("복합커뮤니티시설", (255, 159, 127), "[직접입력]",             "community center with multipurpose hall and outdoor plaza",           4000.0),
        ("치유의숲",         (127, 255,   0), "[직접입력]",             "healing forest with walking trails, meditation zones, no buildings", 20000.0),
    ]
    return [
        {
            "name": n,
            "r": rgb[0], "g": rgb[1], "b": rgb[2],
            "preset": preset,
            "custom_desc": custom_desc,
            "area_sqm": area,
            "tolerance": 25,
            "enabled": True,
        }
        for n, rgb, preset, custom_desc, area in defaults
    ]

if not st.session_state.land_use_table:
    st.session_state.land_use_table = []

# ──────────────────────────────────────────────────────────────
# 이미지 유틸
# ──────────────────────────────────────────────────────────────
def pil_to_png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def bytes_to_pil(b: bytes) -> Image.Image:
    return Image.open(BytesIO(b)).convert("RGB")

# ──────────────────────────────────────────────────────────────
# 마스크 추출 + 클립 (경계 이탈 원천 차단)
# ──────────────────────────────────────────────────────────────
def extract_site_mask(plan_bytes: bytes, white_threshold: int = 240) -> "np.ndarray | None":
    """
    흰배경 계획도에서 사이트 마스크 추출.
    반환: 흰색=0(외부), 유색=255(내부) grayscale numpy array
    """
    if not (CV2_AVAILABLE and np is not None):
        return None
    arr = np.array(bytes_to_pil(plan_bytes))
    white = (
        (arr[:, :, 0] >= white_threshold) &
        (arr[:, :, 1] >= white_threshold) &
        (arr[:, :, 2] >= white_threshold)
    )
    mask = np.where(white, 0, 255).astype(np.uint8)
    # 작은 노이즈 제거
    kernel = np.ones((5, 5), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
    return mask

def apply_clip(
    generated_bytes: bytes,
    satellite_bytes: bytes,
    site_mask: "np.ndarray",
    feather_radius: int = 3,
) -> bytes:
    """
    생성 결과를 사이트 마스크로 클립.
    마스크 내부 = 생성 픽셀, 외부 = 위성 픽셀.
    """
    if not (CV2_AVAILABLE and np is not None) or site_mask is None:
        return generated_bytes

    gen = np.array(bytes_to_pil(generated_bytes))
    h, w = gen.shape[:2]

    sat = np.array(bytes_to_pil(satellite_bytes))
    sat = cv2.resize(sat, (w, h), interpolation=cv2.INTER_LANCZOS4)

    mask = cv2.resize(site_mask, (w, h), interpolation=cv2.INTER_LINEAR)

    # 엣지 페더링
    if feather_radius > 0:
        mask = cv2.GaussianBlur(mask, (feather_radius * 2 + 1, feather_radius * 2 + 1), 0)

    alpha = mask.astype(np.float32) / 255.0
    alpha3 = np.stack([alpha] * 3, axis=-1)

    result = (gen * alpha3 + sat * (1 - alpha3)).astype(np.uint8)
    return pil_to_png_bytes(Image.fromarray(result))

# ──────────────────────────────────────────────────────────────
# 범례 이미지 — UI 확인용
# ──────────────────────────────────────────────────────────────
def build_legend_image(table: list):
    enabled = [row for row in table if row.get("enabled", True)]
    if not enabled:
        return None

    chip_w, chip_h = 60, 36
    row_h = chip_h + 14
    padding = 16
    text_x = chip_w + padding + 10
    img_w = 560
    header_h = 32
    img_h = header_h + padding * 2 + row_h * len(enabled)

    img = Image.new("RGB", (img_w, img_h), (255, 255, 255))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 0, img_w, header_h], fill=(30, 30, 30))
    draw.text((padding, 8), "LAND USE LEGEND", fill=(255, 255, 255))

    for i, row in enumerate(enabled):
        y = header_h + padding + i * row_h
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        draw.rectangle([padding, y, padding + chip_w, y + chip_h],
                       fill=(r, g, b), outline=(80, 80, 80), width=1)
        draw.text((padding, y + chip_h + 1), "R%d G%d B%d" % (r, g, b), fill=(140, 140, 140))

        preset_key = row.get("preset", "")
        custom = row.get("custom_desc", "").strip()
        if custom:
            label_main = custom[:45]
            label_sub = ""
        elif preset_key in ZONE_PRESETS_SIMPLE:
            p = ZONE_PRESETS_SIMPLE[preset_key]
            label_main = p.get("Primary Function", preset_key)[:45]
            label_sub = p.get("prompt_note", "")[:55]
        else:
            label_main = row.get("name", "")[:45]
            label_sub = ""

        draw.text((text_x, y + 4), label_main, fill=(20, 20, 20))
        if label_sub:
            draw.text((text_x, y + 20), label_sub, fill=(90, 90, 90))
        draw.line([padding, y + row_h - 1, img_w - padding, y + row_h - 1],
                  fill=(230, 230, 230), width=1)

    return pil_to_png_bytes(img)

# ──────────────────────────────────────────────────────────────
# 색상 자동 추출
# ──────────────────────────────────────────────────────────────
def extract_dominant_colors(img_bytes: bytes, n_colors: int = 12) -> list:
    if not (CV2_AVAILABLE and np is not None):
        return []
    arr = np.array(bytes_to_pil(img_bytes)).reshape(-1, 3)
    arr = arr[arr.sum(axis=1) > 60]
    arr = arr[~((arr[:, 0] > 230) & (arr[:, 1] > 230) & (arr[:, 2] > 230))]
    if len(arr) < 100:
        return []

    arr_q = (arr // 4 * 4).astype(np.int32)
    keys = arr_q[:, 0] * 65536 + arr_q[:, 1] * 256 + arr_q[:, 2]
    unique, counts = np.unique(keys, return_counts=True)
    total = len(arr)

    results = []
    for idx in np.argsort(-counts):
        key = int(unique[idx])
        b = key % 256
        g = (key // 256) % 256
        r = (key // 65536) % 256
        ratio = counts[idx] / total
        if ratio < 0.005:
            break
        if any(abs(r - er) + abs(g - eg) + abs(b - eb) < 30 for er, eg, eb, _ in results):
            continue
        results.append((r, g, b, float(ratio)))
        if len(results) >= n_colors:
            break
    return results

def build_table_from_detected_colors(
    img_bytes: bytes,
    site_area_sqm: float,
    n_colors: int = 20,
    white_threshold: int = 240,
    black_threshold: int = 60,
) -> list:
    """
    흰 배경 토지이용계획도에서 RGB 색상별 면적비를 추정하여
    토지이용 항목 목록을 자동 생성한다.
    - 흰색 배경 제외
    - 검정 도로/경계선 제외
    - 색상별 픽셀 비율 × 전체 대상지면적 = 추정면적
    """
    if not (CV2_AVAILABLE and np is not None):
        return []

    img = bytes_to_pil(img_bytes)
    arr = np.array(img)

    # 흰색 외부 배경 제외
    white_bg = (
        (arr[:, :, 0] >= white_threshold) &
        (arr[:, :, 1] >= white_threshold) &
        (arr[:, :, 2] >= white_threshold)
    )

    # 검정 도로/경계선 제외
    black_line = (
        (arr[:, :, 0] <= black_threshold) &
        (arr[:, :, 1] <= black_threshold) &
        (arr[:, :, 2] <= black_threshold)
    )

    valid_mask = (~white_bg) & (~black_line)
    valid_pixels = arr[valid_mask]

    if len(valid_pixels) < 100:
        return []

    # 색상 양자화: 안티앨리어싱/경계 노이즈 완화
    q = 4
    arr_q = (valid_pixels // q * q).astype(np.int32)

    keys = arr_q[:, 0] * 65536 + arr_q[:, 1] * 256 + arr_q[:, 2]
    unique, counts = np.unique(keys, return_counts=True)

    total_px = int(np.sum(counts))
    results = []

    for idx in np.argsort(-counts):
        key = int(unique[idx])
        cnt = int(counts[idx])

        b = key % 256
        g = (key // 256) % 256
        r = (key // 65536) % 256

        ratio = cnt / total_px

        # 너무 작은 노이즈 색상 제거
        if ratio < 0.003:
            continue

        # 유사 색상 중복 제거
        if any(abs(r - er) + abs(g - eg) + abs(b - eb) < 35 for er, eg, eb, _ in results):
            continue

        results.append((r, g, b, ratio))

        if len(results) >= n_colors:
            break

    new_rows = []
    for i, (r, g, b, ratio) in enumerate(results, start=1):
        area_sqm = float(site_area_sqm) * float(ratio)

        new_rows.append({
            "name": f"용도_{i}",
            "r": int(r),
            "g": int(g),
            "b": int(b),
            "preset": "[직접입력]",
            "custom_desc": "",
            "area_sqm": round(area_sqm, 1),
            "tolerance": 20,
            "enabled": True,
        })

    return new_rows

# ──────────────────────────────────────────────────────────────
# RGB 기반 구역 마스크 추출
# ──────────────────────────────────────────────────────────────
def extract_zone_masks(landuse_bytes: bytes, table: list) -> dict:
    if not (CV2_AVAILABLE and np is not None):
        return {}
    rgb_arr = np.array(bytes_to_pil(landuse_bytes))
    h, w = rgb_arr.shape[:2]
    results = {}
    for i, row in enumerate(table):
        if not row.get("enabled", True):
            continue
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        tol = int(row.get("tolerance", 25))
        lo = np.array([max(0, r-tol), max(0, g-tol), max(0, b-tol)], dtype=np.uint8)
        hi = np.array([min(255, r+tol), min(255, g+tol), min(255, b+tol)], dtype=np.uint8)
        mask = cv2.inRange(rgb_arr, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
        area_px = int(np.count_nonzero(mask))
        if area_px < 50:
            continue
        m = cv2.moments(mask)
        cx = int(m["m10"] / m["m00"]) if m["m00"] > 0 else w // 2
        cy = int(m["m01"] / m["m00"]) if m["m00"] > 0 else h // 2
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if cnts:
            x_, y_, ww, hh = cv2.boundingRect(np.concatenate(cnts, axis=0))
        else:
            x_, y_, ww, hh = 0, 0, w, h
        results[i] = {
            "mask": mask, "area_px": area_px,
            "centroid": (cx, cy), "bbox": (x_, y_, ww, hh),
            "img_size": (w, h),
        }
    return results

def describe_position(cx, cy, w, h) -> str:
    lr = "western" if cx < w * 0.4 else ("eastern" if cx > w * 0.6 else "central")
    tb = "northern" if cy < h * 0.4 else ("southern" if cy > h * 0.6 else "central")
    if lr == "central" and tb == "central":
        return "center of the site"
    if lr == "central":
        return "%s part of the site" % tb
    if tb == "central":
        return "%s part of the site" % lr
    return "%s-%s part of the site" % (tb, lr)

# ──────────────────────────────────────────────────────────────
# 공원/녹지 여부 판별
# ──────────────────────────────────────────────────────────────
def should_keep_color(row: dict) -> bool:
    preset = row.get("preset", "")
    custom = row.get("custom_desc", "").strip().lower()

    no_building_presets = {"근린공원·주제공원", "하천·수변공간", "광장·공공공지"}
    if preset in no_building_presets:
        return True

    no_building_keywords = [
        "no buildings", "park", "trail", "forest", "golf",
        "pool", "water", "green buffer", "landscape", "garden",
        "walking", "pedestrian", "plaza", "retention", "healing",
        "open space", "lawn", "wetland",
    ]
    return any(k in custom for k in no_building_keywords)

# ──────────────────────────────────────────────────────────────
# 합성 입력 이미지 생성
# 위성(배경) + site 내부 흰색 + 검정 경계선 + [Z] 레이블
# 공원/녹지 구역은 원본 색상 유지
# ──────────────────────────────────────────────────────────────
def build_composite_with_labels(
    landuse_bytes: bytes, table: list, sat_bytes: bytes = None
) -> tuple:
    if not (CV2_AVAILABLE and np is not None):
        return landuse_bytes, {}

    landuse_arr = np.array(bytes_to_pil(landuse_bytes))
    h, w = landuse_arr.shape[:2]

    # 배경 준비
    if sat_bytes:
        sat = bytes_to_pil(sat_bytes)
        try:
            sat = sat.resize((w, h), Image.Resampling.LANCZOS)
        except AttributeError:
            sat = sat.resize((w, h), Image.LANCZOS)
        result = np.array(sat).copy()
    else:
        result = np.ones((h, w, 3), dtype=np.uint8) * 255

    # 검정 경계선 마스크
    gray = cv2.cvtColor(landuse_arr, cv2.COLOR_RGB2GRAY)
    _, black_mask = cv2.threshold(gray, 60, 255, cv2.THRESH_BINARY_INV)

    # 흰색 외부 배경 마스크
    white_bg = (
        (landuse_arr[:, :, 0] > 240) &
        (landuse_arr[:, :, 1] > 240) &
        (landuse_arr[:, :, 2] > 240)
    )

    # site 내부 → 흰색
    site_interior = ~white_bg & (black_mask == 0)
    result[site_interior] = [255, 255, 255]

    # 검정 경계선 복원
    result[black_mask > 0] = [30, 30, 30]

    # Z번호 그룹화
    def get_zone_key(row: dict) -> str:
        preset = row.get("preset", "[직접입력]")
        custom = row.get("custom_desc", "").strip()
        if custom:
            return "custom::" + custom[:40]
        return preset

    zone_key_to_z = {}
    zone_label_map = {}
    z_counter = [1]

    def get_z_num(row):
        key = get_zone_key(row)
        if key not in zone_key_to_z:
            zone_key_to_z[key] = z_counter[0]
            zone_label_map["Z%d" % z_counter[0]] = row
            z_counter[0] += 1
        return zone_key_to_z[key]

    # 구역별 처리
    for i, row in enumerate(table):
        if not row.get("enabled", True):
            continue
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        tol = int(row.get("tolerance", 25))
        lo = np.array([max(0, r-tol), max(0, g-tol), max(0, b-tol)], dtype=np.uint8)
        hi = np.array([min(255, r+tol), min(255, g+tol), min(255, b+tol)], dtype=np.uint8)
        mask = cv2.inRange(landuse_arr, lo, hi)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8), iterations=2)
        if np.count_nonzero(mask) < 200:
            continue

        if should_keep_color(row):
            result[mask > 0] = [r, g, b]
            continue

        z_num = get_z_num(row)
        label_text = "[Z%d]" % z_num

        num_comp, _, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
        for ci in range(1, num_comp):
            comp_area = stats[ci, cv2.CC_STAT_AREA]
            if comp_area < 100:
                continue
            cx = int(centroids[ci][0])
            cy = int(centroids[ci][1])

            font_scale = max(0.4, min(1.5, comp_area ** 0.5 / 130))
            thickness = max(1, int(font_scale * 2))
            (tw, th), _ = cv2.getTextSize(
                label_text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
            )
            tx = max(tw // 2, min(w - tw, cx - tw // 2))
            ty = max(th, min(h - 4, cy + th // 2))

            cv2.rectangle(result,
                (tx - 2, ty - th - 2), (tx + tw + 2, ty + 2),
                (255, 255, 255), -1)
            cv2.putText(result, label_text, (tx, ty),
                cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                (20, 20, 20), thickness, cv2.LINE_AA)

    return pil_to_png_bytes(Image.fromarray(result)), zone_label_map

# ──────────────────────────────────────────────────────────────
# 흰색 경계선 제거 후처리
# ──────────────────────────────────────────────────────────────
def remove_white_lines(img_bytes: bytes) -> bytes:
    if not (CV2_AVAILABLE and np is not None):
        return img_bytes
    try:
        arr = np.array(bytes_to_pil(img_bytes))
        bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        _, white = cv2.threshold(gray, 240, 255, cv2.THRESH_BINARY)
        num, lbl, stats, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
        line_mask = np.zeros_like(white)
        for i in range(1, num):
            area = stats[i, cv2.CC_STAT_AREA]
            bw = stats[i, cv2.CC_STAT_WIDTH]
            bh = stats[i, cv2.CC_STAT_HEIGHT]
            if area < 5000 and (bw < 15 or bh < 15):
                line_mask[lbl == i] = 255
        if np.sum(line_mask) < 10:
            return img_bytes
        dilated = cv2.dilate(line_mask, np.ones((3, 3), np.uint8), iterations=1)
        result = cv2.inpaint(bgr, dilated, 4, cv2.INPAINT_TELEA)
        return pil_to_png_bytes(Image.fromarray(cv2.cvtColor(result, cv2.COLOR_BGR2RGB)))
    except Exception:
        return img_bytes

# ──────────────────────────────────────────────────────────────
# PASS1 프롬프트
# ──────────────────────────────────────────────────────────────
def build_pass1_prompt(
    table: list, zone_masks: dict, site_area: float, zone_label_map: dict = None
) -> str:
    lines = [
        "You are given TWO images:",
        "- Image 1: masterplan canvas — white zones with [Z] labels = building zones,",
        "  colored zones = parks, greenery, water (already correctly colored).",
        "- Image 2: satellite photo of the same site — use as context reference.",
        "",
        "TASK: Transform Image 1 into a premium top-down 2D urban masterplan illustration.",
        "The result must read as a single unified aerial image consistent with Image 2.",
        "",
        "MATERIALS — EVERY SURFACE MUST USE REAL PHYSICAL MATERIALS ONLY:",
        "Rooftops: green roof vegetation, solar panel arrays, HVAC units,",
        "  skylights, exposed concrete, or reflective glass.",
        "Facades: glass curtain wall, brick, exposed concrete, metal cladding,",
        "  stone panel, ceramic tile, painted plaster.",
        "Ground: asphalt, concrete pavement, gravel, natural soil,",
        "  grass, tree canopy, stone paving, pedestrian tiles.",
        "No surface may display a flat zone color — any flat-colored surface",
        "is a generation error. Override with permitted materials above.",
        "",
        "ZONE RULES:",
        "- White [Z] zones: fill fully with buildings, roads, landscape per zone type below.",
        "- Colored zones: enhance with trees, texture, paths. NO buildings whatsoever.",
        "- Preserve ALL zone boundaries exactly. Do NOT redraw or merge zones.",
        "- NO text, labels, or zone numbers in the output.",
        "- TOTAL SITE AREA: ~%s sqm." % "{:,.0f}".format(site_area),
        "",
        "BUILDING ZONE TYPES:",
    ]

    if zone_label_map:
        for z_key, row in zone_label_map.items():
            preset_key = row.get("preset", "[직접입력]")
            custom = row.get("custom_desc", "").strip()
            if custom:
                desc = custom
            elif preset_key in ZONE_PRESETS_SIMPLE:
                desc = ZONE_PRESETS_SIMPLE[preset_key].get("prompt_note", preset_key)
            else:
                desc = row.get("name", z_key)
            user_area = row.get("area_sqm", 0)
            area_str = " | ~%s sqm" % "{:,.0f}".format(user_area) if user_area > 0 else ""
            lines.append("  [%s] = %s%s" % (z_key, desc, area_str))
    else:
        seen_rgb = set()
        for row in table:
            if not row.get("enabled", True):
                continue
            r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
            if (r, g, b) in seen_rgb:
                continue
            seen_rgb.add((r, g, b))
            preset_key = row.get("preset", "[직접입력]")
            custom = row.get("custom_desc", "").strip()
            desc = custom if custom else ZONE_PRESETS_SIMPLE.get(preset_key, {}).get("prompt_note", row.get("name", ""))
            lines.append("  RGB(%d,%d,%d) = %s" % (r, g, b, desc))

    lines += [
        "",
        "ARCHITECTURE:",
        "Varied massing per zone: stepped volumes, courtyard typologies, podium-tower compositions.",
        "Allow 1–2 landmark buildings within their respective footprints.",
        "All facades: realistic window systems, material transitions, floor-level articulation.",
        "",
        "OUTPUT STYLE — PREMIUM 2D MASTERPLAN:",
        "Style: high-end Korean urban development competition board.",
        "Color palette:",
        "  Residential: warm beige/cream buildings, grey slate rooftops, soft drop shadows.",
        "  Parks/green: rich dark green canopy over light green lawn, circular tree shadows.",
        "  Public: terracotta/orange accent roofs, civic plazas.",
        "  Water: vivid blue-green with subtle ripple texture.",
        "  Roads: light warm grey asphalt, white lane markings, curb lines.",
        "Buildings: many varied footprints — L-shape, U-shape, courtyard, slab, point tower.",
        "Landscape: lush dark green canopies, light green lawns, dense street trees.",
        "Quality: competition-board quality. Rich, dense, colorful, highly detailed.",
        "Crisp clean edges. No text, no labels, no zone markers in output.",
        "",
        "HARD CONSTRAINTS:",
        "DO NOT generate anything in white areas outside the site boundary.",
        "DO NOT produce CG, cartoon, or plastic-looking output.",
    ]
    return "\n".join(lines).strip()

# ──────────────────────────────────────────────────────────────
# PASS2 프롬프트
# ──────────────────────────────────────────────────────────────
FIXED_QUALITY_OBLIQUE = (
    "RENDER QUALITY — PHOTOREALISTIC (competition-grade archviz):\n"
    "Lighting: Late-afternoon golden-hour sun, low angle. Strong directional shadows. "
    "Warm orange-gold on sunlit faces. Cool blue-grey in shadows. Filmic HDR.\n"
    "Glass: Fresnel reflections, sky color reflected, sharp sun glints on curtain walls.\n"
    "Brick/concrete: Visible mortar joints, surface grain, shadow lines under overhangs.\n"
    "Vegetation: 3D volumetric tree canopies, translucent leaf edges, cast shadows.\n"
    "Roads: Asphalt texture, curb shadow lines, sidewalk paving patterns.\n"
    "No blur, no cartoon shading, no flat uniform colors. Photorealistic throughout.\n"
)

def build_pass2_prompt(table: list) -> str:
    lines = [
        "Convert the input 2D masterplan into a photorealistic 3D oblique aerial archviz render.",
        "",
        "MATERIALS — EVERY SURFACE MUST USE REAL PHYSICAL MATERIALS ONLY:",
        "Rooftops: green roof vegetation, solar panel arrays, HVAC units,",
        "  skylights, exposed concrete, or reflective glass.",
        "Facades: glass curtain wall, brick, exposed concrete, metal cladding,",
        "  stone panel, ceramic tile, painted plaster.",
        "Ground: asphalt, concrete pavement, gravel, natural soil,",
        "  grass, tree canopy, stone paving, pedestrian tiles.",
        "No surface may display a flat zone color — any flat-colored surface",
        "is a generation error. Override with permitted materials above.",
        "",
        "LAND USE REFERENCE:",
    ]

    seen_rgb = set()
    for row in table:
        if not row.get("enabled", True):
            continue
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        if (r, g, b) in seen_rgb:
            continue
        seen_rgb.add((r, g, b))
        preset_key = row.get("preset", "[직접입력]")
        custom = row.get("custom_desc", "").strip()
        desc = custom[:80] if custom else ZONE_PRESETS_SIMPLE.get(preset_key, {}).get("prompt_note", row.get("name", ""))
        lines.append("  RGB(%d,%d,%d) = %s" % (r, g, b, desc))

    lines += [
        "",
        "Keep all geometry exactly as in the input. Do NOT redesign or crop.",
        "CAMERA: 45–55 degree oblique aerial view, matched to input perspective.",
        "",
        FIXED_QUALITY_OBLIQUE,
        "HARD CONSTRAINTS:",
        "DO NOT produce CG, cartoon, or plastic-looking output.",
        "DO NOT render any text or labels.",
    ]
    return "\n".join(lines).strip()

# ──────────────────────────────────────────────────────────────
# PASS3 프롬프트
# ──────────────────────────────────────────────────────────────
def build_pass3_prompt(angle: int) -> str:
    return (
        "Keep everything exactly the same. "
        "Only change the camera angle to %d degrees oblique aerial view." % angle
    )

# ──────────────────────────────────────────────────────────────
# Gemini helpers
# ──────────────────────────────────────────────────────────────
def _part_from_text(text):
    if GENAI_TYPES_AVAILABLE:
        try: return types.Part.from_text(text=text)
        except: return types.Part(text=text)
    return {"text": text}

def _part_from_bytes(data, mime="image/png"):
    if GENAI_TYPES_AVAILABLE:
        try: return types.Part.from_bytes(data=data, mime_type=mime)
        except: return types.Part(inline_data=types.Blob(mime_type=mime, data=data))
    return {"inline_data": {"mime_type": mime, "data": data}}

def make_contents(prompt: str, images: list) -> list:
    return [_part_from_text(prompt)] + [_part_from_bytes(b) for b in images]

def get_image_from_resp(resp):
    parts = getattr(resp, "parts", None)
    if parts is None:
        cands = getattr(resp, "candidates", [])
        content = getattr(cands[0], "content", None) if cands else None
        parts = getattr(content, "parts", []) if content else []
    for part in parts:
        inline = getattr(part, "inline_data", None)
        if inline:
            data = getattr(inline, "data", None)
            if data:
                return data
    return None

# ──────────────────────────────────────────────────────────────
# 이미지 선택 UI
# ──────────────────────────────────────────────────────────────
def render_selector(outputs, sel_key, label):
    if not outputs:
        return None
    for row_start in range(0, len(outputs), 2):
        cols = st.columns(2, gap="medium")
        for j, img_bytes in enumerate(outputs[row_start:row_start+2]):
            i = row_start + j
            with cols[j]:
                im = bytes_to_pil(img_bytes)
                w, h = im.size
                is_sel = (st.session_state[sel_key] == i)
                border = "2px solid #2563EB" if is_sel else "1px solid #E5E7EB"
                st.markdown('<div style="border:%s;border-radius:10px;padding:6px;">' % border,
                            unsafe_allow_html=True)
                st.image(im, caption="%s #%d — %dx%d" % (label, i+1, w, h),
                         use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                btn_label = "선택됨 #%d" % (i+1) if is_sel else "선택 #%d" % (i+1)
                if st.button(btn_label, key="%s_btn_%d" % (sel_key, i),
                             use_container_width=True,
                             type="primary" if is_sel else "secondary"):
                    st.session_state[sel_key] = i
                    st.rerun()
    return outputs[st.session_state[sel_key]]

# ──────────────────────────────────────────────────────────────
# 상단 네비게이션
# ──────────────────────────────────────────────────────────────
STEPS = ["① 이미지 입력", "② 토지이용계획표", "③ 생성"]
cur_step = st.session_state.step

cols_nav = st.columns(len(STEPS))
for _i, _label in enumerate(STEPS):
    with cols_nav[_i]:
        _active = (_i == cur_step)
        _done = (_i < cur_step)
        _bg = "#2563EB" if _active else ("#DCFCE7" if _done else "#F9FAFB")
        _fg = "#fff" if _active else ("#15803D" if _done else "#9CA3AF")
        _border = "#2563EB" if _active else ("#86EFAC" if _done else "#E5E7EB")
        st.markdown(
            '<div style="background:%s;color:%s;border:2px solid %s;'
            'border-radius:10px;padding:10px 0;text-align:center;'
            'font-weight:700;font-size:14px;">%s%s</div>'
            % (_bg, _fg, _border, "✓ " if _done else "", _label),
            unsafe_allow_html=True
        )

nav_c1, nav_c2, _ = st.columns([1, 1, 4])
with nav_c1:
    if st.button("◀ 이전", disabled=(cur_step == 0)):
        st.session_state.step -= 1
        st.rerun()
with nav_c2:
    _can_next = (
        (cur_step == 0 and st.session_state.img_landuse_bytes is not None) or
        (cur_step == 1)
    )
    if st.button("다음 ▶", disabled=(cur_step >= 2 or not _can_next)):
        st.session_state.step += 1
        st.rerun()

st.markdown(
    '<div style="height:3px;background:linear-gradient(90deg,#2563EB,#1E293B 80%);'
    'border-radius:2px;margin:16px 0 28px 0;"></div>',
    unsafe_allow_html=True
)

# 에러 표시
if st.session_state._errors:
    for err in st.session_state._errors:
        st.error(err)
    st.session_state._errors = []

# ══════════════════════════════════════════════════════════════
# STEP 0: 이미지 입력
# ══════════════════════════════════════════════════════════════
if cur_step == 0:
    st.markdown('<div class="section-header">① 이미지 입력</div>', unsafe_allow_html=True)

    col_landuse, col_sat = st.columns(2, gap="large")

    with col_landuse:
        st.markdown("**토지이용계획도** ⭐ 필수")
        st.caption("색상으로 구역이 구분된 토지이용계획 이미지")
        f2 = st.file_uploader("토지이용계획도 업로드", type=["png","jpg","jpeg"], key="up_landuse")
        if f2:
            st.session_state.img_landuse_bytes = f2.getvalue()
        if st.session_state.img_landuse_bytes:
            st.image(bytes_to_pil(st.session_state.img_landuse_bytes),
                     use_container_width=True, caption="토지이용계획도")

    with col_sat:
        st.markdown("**위성사진** (선택)")
        st.caption("동일 위치 위성사진 — 배경 합성 및 클립 기준으로 사용됩니다")
        f3 = st.file_uploader("위성사진 업로드", type=["png","jpg","jpeg"], key="up_sat")
        if f3:
            st.session_state.img_sat_bytes = f3.getvalue()
        if st.session_state.img_sat_bytes:
            st.image(bytes_to_pil(st.session_state.img_sat_bytes),
                     use_container_width=True, caption="위성사진")

    st.markdown('<div class="sub-label">계획부지 전체 면적</div>', unsafe_allow_html=True)
    st.session_state.site_area_sqm = st.number_input(
        "계획부지 전체면적 (㎡)", min_value=1.0,
        value=float(st.session_state.site_area_sqm),
        step=1000.0, format="%.0f"
    )

    if not st.session_state.img_landuse_bytes:
        st.warning("토지이용계획도는 필수입니다. 업로드 후 다음 단계로 이동하세요.")
    else:
        st.success("확인됨. '다음 ▶'으로 이동하세요.")

# ══════════════════════════════════════════════════════════════
# STEP 1: 토지이용계획표
# ══════════════════════════════════════════════════════════════
elif cur_step == 1:
    st.markdown('<div class="section-header">② 토지이용계획표</div>', unsafe_allow_html=True)
    st.caption("각 토지이용 항목의 RGB 색상, 면적, 용도 설명을 설정하세요.")

    # 엑셀 업로드
    with st.expander("📥 엑셀로 토지이용계획표 불러오기", expanded=False):
        st.caption("컬럼 순서: 용도명 / R / G / B / 면적(㎡) / 용도설명(영문) / 프리셋(선택)")

        if st.button("📄 템플릿 다운로드"):
            import io as _io
            try:
                import openpyxl as _xl
                _wb = _xl.Workbook()
                _ws = _wb.active
                _ws.title = "토지이용계획표"
                _ws.append(["용도명", "R", "G", "B", "면적(㎡)", "용도설명(영문)", "프리셋"])
                for _r in [
                    ("단독주택",  255, 255, 127, 10000, "Low-rise detached housing, 2~3F, garden plots", "단독주택"),
                    ("공원",        0, 165,   0, 15000, "Neighborhood park, tree canopy, walking paths", "근린공원·주제공원"),
                    ("숙박시설",  255, 191, 127, 12000, "resort hotel with amenity facilities, 5~10F, warm facade", "[직접입력]"),
                    ("치유의숲",  127, 255,   0, 20000, "healing forest with walking trails, meditation zones, no buildings", "[직접입력]"),
                ]:
                    _ws.append(_r)
                _buf = _io.BytesIO()
                _wb.save(_buf)
                _buf.seek(0)
                st.download_button(
                    "⬇️ 템플릿 xlsx 다운로드", data=_buf.getvalue(),
                    file_name="토지이용계획표_템플릿.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except ImportError:
                st.error("openpyxl 패키지가 필요합니다.")

        xl_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=["xlsx"], key="xl_upload")
        if xl_file and st.button("테이블에 적용", type="primary", key="apply_xl"):
            try:
                import openpyxl as _xl
                import io as _io
                _wb = _xl.load_workbook(_io.BytesIO(xl_file.getvalue()), data_only=True)
                _ws = _wb.active
                _new_rows = []
                for _row in _ws.iter_rows(min_row=2, values_only=True):
                    if not _row or not _row[0] or str(_row[0]).strip() == "":
                        continue
                    _name   = str(_row[0]).strip()
                    _r      = max(0, min(255, int(float(_row[1] or 0))))
                    _g      = max(0, min(255, int(float(_row[2] or 0))))
                    _b      = max(0, min(255, int(float(_row[3] or 0))))
                    _area   = float(_row[4] or 0)
                    _custom = str(_row[5] or "").strip()
                    _preset = str(_row[6] or "[직접입력]").strip()
                    if _preset not in PRESET_OPTIONS:
                        _preset = "[직접입력]"
                    _new_rows.append({
                        "name": _name, "r": _r, "g": _g, "b": _b,
                        "preset": _preset, "custom_desc": _custom,
                        "area_sqm": _area, "tolerance": 25, "enabled": True,
                    })
                if _new_rows:
                    st.session_state.land_use_table = _new_rows
                    st.success("%d개 항목 불러옴" % len(_new_rows))
                    st.rerun()
                else:
                    st.warning("불러온 데이터가 없습니다.")
            except Exception as _e:
                st.error("엑셀 파일 오류: %s" % str(_e))

    # 색상 자동 추출
    if st.session_state.img_landuse_bytes and CV2_AVAILABLE:
        if st.button("🎨 감지된 색상만으로 토지이용 항목 재생성", type="primary"):
            with st.spinner("색상 및 면적비 자동 계산 중..."):
                colors = extract_dominant_colors(
                    st.session_state.img_landuse_bytes,
                    n_colors=20
                )

                new_rows = []

                if colors:
                    # 흰색 배경과 검정 도로/경계 제외 후 유효 픽셀 기준 총량 계산
                    arr = np.array(bytes_to_pil(st.session_state.img_landuse_bytes))

                    white_bg = (
                        (arr[:, :, 0] > 240) &
                        (arr[:, :, 1] > 240) &
                        (arr[:, :, 2] > 240)
                    )

                    black_line = (
                        (arr[:, :, 0] < 60) &
                        (arr[:, :, 1] < 60) &
                        (arr[:, :, 2] < 60)
                    )

                    valid_mask = (~white_bg) & (~black_line)
                    total_valid_px = max(1, int(np.count_nonzero(valid_mask)))

                    for i, (r, g, b, ratio_old) in enumerate(colors, start=1):
                        tol = 20

                        lo = np.array(
                            [max(0, r - tol), max(0, g - tol), max(0, b - tol)],
                            dtype=np.uint8
                        )
                        hi = np.array(
                            [min(255, r + tol), min(255, g + tol), min(255, b + tol)],
                            dtype=np.uint8
                        )

                        mask = cv2.inRange(arr, lo, hi)
                        mask = (mask > 0) & valid_mask

                        area_px = int(np.count_nonzero(mask))
                        ratio = area_px / total_valid_px
                        area_sqm = float(st.session_state.site_area_sqm) * ratio

                        if ratio < 0.003:
                            continue

                        new_rows.append({
                            "name": "",
                            "r": int(r),
                            "g": int(g),
                            "b": int(b),
                            "preset": "",
                            "custom_desc": "",
                            "area_sqm": round(area_sqm, 1),
                            "tolerance": tol,
                            "enabled": True,
                        })

            if new_rows:
                # 핵심: 기존 디폴트 삭제하고 감지 색상만 반영
                st.session_state.land_use_table = new_rows
                st.session_state["_auto_colors"] = []
                st.success(f"{len(new_rows)}개 색상 항목으로 테이블을 재생성했습니다.")
                st.rerun()
            else:
                st.warning("감지된 색상이 없습니다. 흰 배경 + 색상 구역 이미지인지 확인하세요.")

    st.markdown("---")

    # 표준 항목 추가
    with st.expander("+ 항목 추가", expanded=False):
        lu_names = [lu[0] for lu in STANDARD_LAND_USES]
        ac1, ac2 = st.columns([3, 1])
        with ac1:
            sel_lu = st.selectbox("표준 항목에서 선택", lu_names)
        with ac2:
            if st.button("추가", type="primary"):
                idx = lu_names.index(sel_lu)
                item = STANDARD_LAND_USES[idx]
                st.session_state.land_use_table.append({
                    "name": item[0], "r": item[1][0], "g": item[1][1], "b": item[1][2],
                    "preset": item[2], "custom_desc": "",
                    "area_sqm": 10000.0, "tolerance": 25, "enabled": True,
                })
                st.rerun()

        st.markdown("**직접 입력**")
        dc1, dc2, dc3, dc4, dc5 = st.columns([2, 0.7, 0.7, 0.7, 1.5])
        new_name   = dc1.text_input("용도명", key="new_name")
        new_r      = dc2.number_input("R", 0, 255, 128, key="new_r")
        new_g      = dc3.number_input("G", 0, 255, 128, key="new_g")
        new_b      = dc4.number_input("B", 0, 255, 128, key="new_b")
        new_preset = dc5.selectbox("프리셋", PRESET_OPTIONS, key="new_preset")
        if st.button("직접 추가"):
            if new_name:
                st.session_state.land_use_table.append({
                    "name": new_name, "r": int(new_r), "g": int(new_g), "b": int(new_b),
                    "preset": new_preset, "custom_desc": "",
                    "area_sqm": 10000.0, "tolerance": 25, "enabled": True,
                })
                st.rerun()

    # 테이블 편집
    st.markdown('<div class="sub-label">토지이용 항목 목록</div>', unsafe_allow_html=True)
    table = st.session_state.land_use_table

    if not table:
        st.info("등록된 항목이 없습니다. 엑셀 업로드 또는 직접 추가하세요.")

    to_delete = []
    for i, row in enumerate(table):
        c_en, c_name, c_r, c_g, c_b, c_tol, c_area, c_preset, c_chip, c_del = st.columns(
            [0.4, 1.6, 0.6, 0.6, 0.6, 0.7, 1.1, 2.0, 0.5, 0.4]
        )
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        hex_color = "#%02x%02x%02x" % (r, g, b)

        table[i]["enabled"]   = c_en.checkbox("", value=row.get("enabled", True), key="en_%d" % i)
        table[i]["name"]      = c_name.text_input("", value=row.get("name", ""), key="name_%d" % i, label_visibility="collapsed", placeholder="용도 입력")
        table[i]["r"]         = c_r.number_input("R", 0, 255, r, key="r_%d" % i, label_visibility="collapsed")
        table[i]["g"]         = c_g.number_input("G", 0, 255, g, key="g_%d" % i, label_visibility="collapsed")
        table[i]["b"]         = c_b.number_input("B", 0, 255, b, key="b_%d" % i, label_visibility="collapsed")
        table[i]["tolerance"] = c_tol.number_input("Tol", 5, 80, int(row.get("tolerance", 25)), key="tol_%d" % i, label_visibility="collapsed")
        table[i]["area_sqm"]  = c_area.number_input("sqm", 0.0, 9999999.0, float(row.get("area_sqm", 10000.0)), step=500.0, key="area_%d" % i, label_visibility="collapsed")

        cur_preset = row.get("preset", "")
        table[i]["preset"] = c_preset.selectbox(
            "", PRESET_OPTIONS, index=None if cur_preset == "" else PRESET_OPTIONS.index(cur_preset) if cur_preset in PRESET_OPTIONS else 0,
            key="preset_%d" % i, label_visibility="collapsed"
        )

        c_chip.markdown(
            '<div style="margin-top:6px;width:26px;height:26px;border-radius:5px;'
            'background:%s;border:1px solid rgba(0,0,0,0.2);"></div>' % hex_color,
            unsafe_allow_html=True
        )
        if c_del.button("x", key="del_%d" % i):
            to_delete.append(i)

        if table[i]["preset"] == "[직접입력]":
            table[i]["custom_desc"] = st.text_input(
                "용도 설명 (영문 권장)",
                value=row.get("custom_desc", ""),
                key="cdesc_%d" % i,
                placeholder="예: glamping resort with log cabins, 1~2F, natural wood facade",
                help="이 설명이 프롬프트에 직접 사용됩니다"
            )

    if to_delete:
        st.session_state.land_use_table = [r for idx, r in enumerate(table) if idx not in to_delete]
        st.rerun()

    # RGB 추출 미리보기
    st.markdown('<div class="sub-label">RGB 추출 미리보기</div>', unsafe_allow_html=True)
    if st.session_state.img_landuse_bytes and CV2_AVAILABLE and table:
        if st.button("구역 추출 미리보기", type="secondary"):
            with st.spinner("구역 추출 중..."):
                zm = extract_zone_masks(st.session_state.img_landuse_bytes, table)
            if zm:
                overlay = np.array(bytes_to_pil(st.session_state.img_landuse_bytes)).copy()
                total_px = sum(v["area_px"] for v in zm.values()) or 1
                for idx, z in zm.items():
                    cnts, _ = cv2.findContours(z["mask"], cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                    cv2.drawContours(overlay, cnts, -1, (255, 0, 0), 3)
                    cx, cy = z["centroid"]
                    cv2.circle(overlay, (cx, cy), 8, (255, 0, 0), -1)
                    ratio = z["area_px"] / total_px * 100
                    name = table[idx].get("name", "Zone %d" % idx)
                    st.markdown("**%s**: %s px (%.1f%%) — %s"
                                % (name, "{:,}".format(z["area_px"]), ratio,
                                   describe_position(cx, cy, *z["img_size"])))
                st.image(Image.fromarray(overlay), caption="추출된 구역 (빨간 윤곽선)",
                         use_container_width=True)
            else:
                st.warning("추출된 구역 없음. RGB 값과 tolerance를 조정하세요.")

    # 면적 합계
    total_area = sum(row.get("area_sqm", 0) for row in table if row.get("enabled", True))
    site_area  = st.session_state.site_area_sqm
    diff = site_area - total_area
    diff_color = "#DC2626" if abs(diff) > site_area * 0.05 else "#16A34A"
    st.markdown(
        '<div style="background:#F0FDF4;border:1px solid #86EFAC;border-radius:8px;'
        'padding:12px 16px;margin-top:12px;">'
        '<b>면적 합계:</b> 개별 합계 <b>%s㎡</b> / 전체 부지 <b>%s㎡</b> / '
        '차이 <b style="color:%s;">%+.0f㎡</b></div>'
        % ("{:,.0f}".format(total_area), "{:,.0f}".format(site_area), diff_color, diff),
        unsafe_allow_html=True
    )

    st.success("설정 완료 시 '다음 ▶'로 이동하여 이미지를 생성하세요.")

# ══════════════════════════════════════════════════════════════
# STEP 2: 생성
# ══════════════════════════════════════════════════════════════
else:
    st.markdown('<div class="section-header">③ 이미지 생성</div>', unsafe_allow_html=True)

    if not GENAI_AVAILABLE:
        st.error("google-genai 패키지가 없습니다.")
        st.stop()

    if not st.session_state.img_landuse_bytes:
        st.error("토지이용계획도가 없습니다. 이전 단계로 돌아가세요.")
        st.stop()

    api_key = st.text_input("Google AI Studio API 키", type="password").strip()
    st.caption("모델: %s" % MODEL_NAME)

    table = st.session_state.land_use_table

    # 위성사진 상태
    if st.session_state.img_sat_bytes:
        st.success("✅ 위성사진 로드됨 — 합성 배경 및 경계 클립에 사용됩니다")
    else:
        st.warning("⚠️ 위성사진 없음 — 업로드하면 경계 클립 품질이 크게 향상됩니다")
        with st.expander("위성사진 업로드", expanded=True):
            f_sat_retry = st.file_uploader(
                "위성사진 (.png/.jpg/.jpeg)",
                type=["png","jpg","jpeg"],
                key="up_sat_retry"
            )
            if f_sat_retry:
                st.session_state.img_sat_bytes = f_sat_retry.getvalue()
                st.rerun()

    # 합성 입력 이미지 생성
    composite_bytes = None
    zone_label_map = {}
    site_mask = None

    if CV2_AVAILABLE:
        with st.spinner("입력 이미지 합성 중..."):
            composite_bytes, zone_label_map = build_composite_with_labels(
                st.session_state.img_landuse_bytes,
                table,
                st.session_state.img_sat_bytes
            )
            # 마스크 추출 (경계 클립용)
            site_mask = extract_site_mask(st.session_state.img_landuse_bytes)

    if composite_bytes:
        st.markdown('<div class="sub-label">합성 입력 이미지 (PASS1 입력)</div>',
                    unsafe_allow_html=True)
        st.image(bytes_to_pil(composite_bytes),
                 caption="위성배경 + 흰백판 + Z레이블 + 공원녹지 색상",
                 use_container_width=True)

    input_for_pass1 = composite_bytes if composite_bytes else st.session_state.img_landuse_bytes

    # 범례 이미지
    legend_bytes = build_legend_image(table)
    if legend_bytes:
        st.markdown('<div class="sub-label">범례 이미지 (UI 확인용)</div>', unsafe_allow_html=True)
        st.image(bytes_to_pil(legend_bytes), width=400,
                 caption="범례 — 모델 입력에는 사용되지 않습니다")

    # 프롬프트 생성
    zone_masks = {}
    if CV2_AVAILABLE:
        zone_masks = extract_zone_masks(st.session_state.img_landuse_bytes, table)

    pass1_prompt = build_pass1_prompt(
        table, zone_masks, st.session_state.site_area_sqm, zone_label_map
    )
    pass2_prompt = build_pass2_prompt(table)

    # 개발자 확인
    dev_pw = st.text_input("개발자 비밀번호", type="password", key="dev_pw")
    if dev_pw == "126791":
        with st.expander("PASS1 프롬프트", expanded=False):
            st.code(pass1_prompt, language="text")
        with st.expander("PASS2 프롬프트", expanded=False):
            st.code(pass2_prompt, language="text")
        with st.expander("Z 레이블 매핑", expanded=False):
            for z_key, row in zone_label_map.items():
                st.write("[%s] → %s (%s)" % (z_key, row.get("name", ""), row.get("preset", "")))

    st.markdown("---")

    # ── PASS 1 ────────────────────────────────────────────
    st.markdown("### STEP 1 — 2D 배치도 생성")

    # PASS1 이미지 입력: composite(Image1) + 위성(Image2)
    def get_pass1_images():
        imgs = [input_for_pass1]
        if st.session_state.img_sat_bytes:
            imgs.append(st.session_state.img_sat_bytes)
        return imgs

    def run_pass1():
        client = genai.Client(api_key=api_key)
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=make_contents(pass1_prompt, get_pass1_images())
            )
            out = get_image_from_resp(resp)
            if out:
                # 후처리 1: 흰선 제거
                out = remove_white_lines(out)
                # 후처리 2: 경계 클립 (구조적 경계 이탈 차단)
                if site_mask is not None and st.session_state.img_sat_bytes:
                    out = apply_clip(out, st.session_state.img_sat_bytes, site_mask)
                st.session_state.pass1_outputs.append(out)
                st.session_state.pass1_selected_idx = len(st.session_state.pass1_outputs) - 1
                st.session_state.pass1_output_bytes = out
                st.session_state.pass2_outputs = []
                st.session_state.pass3_outputs = []
                st.session_state.pass2_output_bytes = None
            else:
                st.session_state._errors.append("PASS1: 이미지가 반환되지 않았습니다.")
        except Exception as e:
            st.session_state._errors.append("PASS1 오류: %s" % str(e))

    p1c1, p1c2, p1c3 = st.columns([1.2, 1.5, 3])
    with p1c1:
        if st.button("STEP 1 생성", type="primary", disabled=len(api_key) < 10):
            st.session_state.pass1_outputs = []
            st.session_state.pass1_selected_idx = 0
            with st.spinner("STEP 1 생성 중..."):
                run_pass1()
            st.rerun()
    with p1c2:
        if st.button("한 번 더 생성",
                     disabled=(len(api_key) < 10 or
                               not st.session_state.pass1_outputs or
                               len(st.session_state.pass1_outputs) >= 5)):
            with st.spinner("추가 생성 (%d번째)..." % (len(st.session_state.pass1_outputs) + 1)):
                run_pass1()
            st.rerun()
    with p1c3:
        if st.session_state.pass1_outputs:
            st.caption("%d개 생성됨 (최대 5개)" % len(st.session_state.pass1_outputs))

    if st.session_state.pass1_outputs:
        st.markdown("**STEP 1 결과 — 최적 이미지 선택**")
        selected_p1 = render_selector(st.session_state.pass1_outputs, "pass1_selected_idx", "STEP1")
        if selected_p1:
            st.session_state.pass1_output_bytes = selected_p1
        st.download_button("⬇️ STEP 1 다운로드",
                           data=st.session_state.pass1_output_bytes,
                           file_name="planvision_step1_2d.png", mime="image/png")

    st.markdown("---")

    # ── PASS 2 ────────────────────────────────────────────
    st.markdown("### STEP 2 — 3D 조감도 생성")
    p2_disabled = len(api_key) < 10 or not st.session_state.pass1_output_bytes

    def run_pass2():
        client = genai.Client(api_key=api_key)
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=make_contents(pass2_prompt, [
                    st.session_state.pass1_output_bytes,
                    st.session_state.img_landuse_bytes,
                ])
            )
            out = get_image_from_resp(resp)
            if out:
                st.session_state.pass2_outputs.append(out)
                st.session_state.pass2_selected_idx = len(st.session_state.pass2_outputs) - 1
                st.session_state.pass2_output_bytes = out
                st.session_state.pass3_outputs = []
            else:
                st.session_state._errors.append("PASS2: 이미지가 반환되지 않았습니다.")
        except Exception as e:
            st.session_state._errors.append("PASS2 오류: %s" % str(e))

    p2c1, p2c2, p2c3 = st.columns([1.2, 1.5, 3])
    with p2c1:
        if st.button("STEP 2 생성", type="primary", disabled=p2_disabled):
            st.session_state.pass2_outputs = []
            st.session_state.pass2_selected_idx = 0
            with st.spinner("STEP 2 생성 중..."):
                run_pass2()
            st.rerun()
    with p2c2:
        if st.button("한 번 더 생성 ",
                     disabled=(p2_disabled or
                               not st.session_state.pass2_outputs or
                               len(st.session_state.pass2_outputs) >= 5)):
            with st.spinner("추가 생성 (%d번째)..." % (len(st.session_state.pass2_outputs) + 1)):
                run_pass2()
            st.rerun()
    with p2c3:
        if st.session_state.pass2_outputs:
            st.caption("%d개 생성됨 (최대 5개)" % len(st.session_state.pass2_outputs))

    if st.session_state.pass2_outputs:
        st.markdown("**STEP 2 결과 — 최적 이미지 선택**")
        selected_p2 = render_selector(st.session_state.pass2_outputs, "pass2_selected_idx", "STEP2")
        if selected_p2:
            st.session_state.pass2_output_bytes = selected_p2
        st.download_button("⬇️ STEP 2 다운로드",
                           data=st.session_state.pass2_output_bytes,
                           file_name="planvision_step2_3d.png", mime="image/png")

        st.markdown("---")

        # ── PASS 3 ────────────────────────────────────────
        st.markdown("### STEP 3 — 각도 변환 (선택사항)")
        p3_angle = st.selectbox("변환 각도",
                                ["30° (저각도)", "45° (중각도)", "60° (준조감도)"], index=1)
        angle_deg = {"30° (저각도)": 30, "45° (중각도)": 45, "60° (준조감도)": 60}[p3_angle]
        p3_disabled = len(api_key) < 10 or not st.session_state.pass2_output_bytes

        def run_pass3():
            client = genai.Client(api_key=api_key)
            try:
                resp = client.models.generate_content(
                    model=MODEL_NAME,
                    contents=make_contents(
                        build_pass3_prompt(angle_deg),
                        [st.session_state.pass2_output_bytes]
                    )
                )
                out = get_image_from_resp(resp)
                if out:
                    st.session_state.pass3_outputs.append(out)
                    st.session_state.pass3_selected_idx = len(st.session_state.pass3_outputs) - 1
                else:
                    st.session_state._errors.append("PASS3: 이미지가 반환되지 않았습니다.")
            except Exception as e:
                st.session_state._errors.append("PASS3 오류: %s" % str(e))

        p3c1, p3c2, p3c3 = st.columns([1.2, 1.5, 3])
        with p3c1:
            if st.button("STEP 3 변환", type="secondary", disabled=p3_disabled):
                st.session_state.pass3_outputs = []
                st.session_state.pass3_selected_idx = 0
                with st.spinner("STEP 3 생성 중..."):
                    run_pass3()
                st.rerun()
        with p3c2:
            if st.button("한 번 더 생성  ",
                         disabled=(p3_disabled or
                                   not st.session_state.pass3_outputs or
                                   len(st.session_state.pass3_outputs) >= 5)):
                with st.spinner("추가 생성 (%d번째)..." % (len(st.session_state.pass3_outputs) + 1)):
                    run_pass3()
                st.rerun()
        with p3c3:
            if st.session_state.pass3_outputs:
                st.caption("%d개 생성됨" % len(st.session_state.pass3_outputs))

        if st.session_state.pass3_outputs:
            st.markdown("**STEP 3 결과**")
            selected_p3 = render_selector(st.session_state.pass3_outputs, "pass3_selected_idx", "STEP3")
            p3_final = selected_p3 or st.session_state.pass3_outputs[0]
            st.download_button(
                "⬇️ 최종 다운로드 (STEP 3)", data=p3_final,
                file_name="planvision_final_%ddeg.png" % angle_deg,
                mime="image/png", use_container_width=True
            )
        else:
            st.download_button(
                "⬇️ 최종 다운로드 (STEP 2)",
                data=st.session_state.pass2_output_bytes,
                file_name="planvision_final_step2.png",
                mime="image/png"
            )
