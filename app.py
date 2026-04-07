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
    --text: #111827;
    --muted: #6B7280;
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
# 표준 토지이용 항목 — 실제 사용 RGB값 기반
# (용도명, RGB, 프리셋키, 설명)
# ──────────────────────────────────────────────────────────────
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
# 프리셋 데이터
# ──────────────────────────────────────────────────────────────
ZONE_PRESETS_SIMPLE = {
    "단독주택": {
        "Primary Function": "Residential - Detached housing",
        "mass_types": ["Terraced / stepped mass — 테라스/계단형"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "Low", "far_level": "Low", "floor_level": "Low",
        "Primary Façade Material": ["brick"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Low-rise detached housing, 2~3F, garden plots",
    },
    "연립·다세대주택": {
        "Primary Function": "Residential - Attached housing",
        "mass_types": ["Courtyard block — 중정형 블록"],
        "Height Strategy": "Mid-rise field",
        "bcr_level": "Medium", "far_level": "Low", "floor_level": "Low",
        "Primary Façade Material": ["brick"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Low-to-mid rise attached housing, 3~5F, courtyard arrangement",
    },
    "공동주택(판상형 아파트)": {
        "Primary Function": "Residential - Slab apartment complex",
        "mass_types": ["Slab bar — 판상형"],
        "Height Strategy": "Mid-rise field",
        "bcr_level": "Low", "far_level": "Medium", "floor_level": "Medium–High",
        "Primary Façade Material": ["concrete"],
        "Landscape Density Strategy": "Green corridor emphasis",
        "prompt_note": "Slab-type apartment, 8~15F, south-facing, central green",
    },
    "공동주택(타워형 아파트)": {
        "Primary Function": "Residential - High-rise tower apartment",
        "mass_types": ["Point tower — 타워형"],
        "Height Strategy": "Scattered high-rise accents",
        "bcr_level": "Very low", "far_level": "Medium–High", "floor_level": "High",
        "Primary Façade Material": ["glass", "concrete"],
        "Landscape Density Strategy": "Park-heavy composition",
        "prompt_note": "High-rise point tower apartment, 20~30F, large landscaped podium",
    },
    "준주거용지": {
        "Primary Function": "Quasi-residential mixed-use",
        "mass_types": ["Perimeter block — 가로연접 블록"],
        "Height Strategy": "Mid-rise field",
        "bcr_level": "Medium–High", "far_level": "Medium", "floor_level": "Low",
        "Primary Façade Material": ["brick", "glass"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Mixed-use quasi-residential, ground retail with residential above, 3~6F",
    },
    "근린생활시설용지": {
        "Primary Function": "Commercial dominant",
        "mass_types": ["Perimeter block — 가로연접 블록"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "High", "far_level": "Low", "floor_level": "Low",
        "Primary Façade Material": ["brick"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Low-rise neighborhood commercial strip, 2~4F storefronts",
    },
    "일반상업용지": {
        "Primary Function": "Commercial dominant",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Stepped skyline",
        "bcr_level": "Medium–High", "far_level": "High", "floor_level": "Medium–High",
        "Primary Façade Material": ["glass", "metal"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "General commercial zone, podium-and-tower typology, 8~20F",
    },
    "복합상업시설(대형몰·복합몰)": {
        "Primary Function": "Commercial dominant",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Single landmark tower",
        "bcr_level": "High", "far_level": "High", "floor_level": "Medium–High",
        "Primary Façade Material": ["glass", "metal"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Large-scale mixed commercial complex, COEX style, 10~25F",
    },
    "업무시설용지(오피스)": {
        "Primary Function": "Office dominant",
        "mass_types": ["Point tower — 타워형"],
        "Height Strategy": "Scattered high-rise accents",
        "bcr_level": "Medium", "far_level": "High", "floor_level": "High",
        "Primary Façade Material": ["glass"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Office tower district, plaza-level retail, 15~30F",
    },
    "복합업무용지(오피스+상업)": {
        "Primary Function": "Office + Commercial mixed-use",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Stepped skyline",
        "bcr_level": "Medium–High", "far_level": "High", "floor_level": "High",
        "Primary Façade Material": ["glass", "metal"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Mixed office and commercial complex, podium retail with tower, 15~30F",
    },
    "첨단산업단지(R&D·지식산업)": {
        "Primary Function": "Innovation/R&D dominant",
        "mass_types": ["Low-rise campus cluster — 저층 캠퍼스 클러스터"],
        "Height Strategy": "Mid-rise field",
        "bcr_level": "Low", "far_level": "Medium", "floor_level": "Medium",
        "Primary Façade Material": ["glass", "metal"],
        "Landscape Density Strategy": "Green corridor emphasis",
        "prompt_note": "High-tech R&D campus, courtyard green network, 3~8F",
    },
    "근린공원·주제공원": {
        "Primary Function": "Park / Open space",
        "mass_types": [],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "Very low", "far_level": "Very low", "floor_level": "Very low",
        "Primary Façade Material": ["concrete"],
        "Landscape Density Strategy": "Park-heavy composition",
        "prompt_note": "Neighborhood park, tree canopy, walking paths, event lawn",
    },
    "하천·수변공간": {
        "Primary Function": "Park / Open space",
        "mass_types": [],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "Very low", "far_level": "Very low", "floor_level": "Very low",
        "Primary Façade Material": ["concrete"],
        "Landscape Density Strategy": "Park-heavy composition",
        "prompt_note": "River corridor, riparian planting, boardwalk, water feature visible",
    },
    "공공청사·행정시설": {
        "Primary Function": "Civic / Government",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Mid-rise field",
        "bcr_level": "Medium", "far_level": "Medium", "floor_level": "Medium",
        "Primary Façade Material": ["concrete", "glass"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Civic government building, formal plaza entry, 5~12F",
    },
    "학교·교육시설": {
        "Primary Function": "Education",
        "mass_types": ["Low-rise campus cluster — 저층 캠퍼스 클러스터"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "Low", "far_level": "Low", "floor_level": "Low",
        "Primary Façade Material": ["brick", "concrete"],
        "Landscape Density Strategy": "Green corridor emphasis",
        "prompt_note": "School campus, playgrounds and sports fields, 2~4F",
    },
    "종합의료시설(병원)": {
        "Primary Function": "Medical / Healthcare",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Scattered high-rise accents",
        "bcr_level": "Medium", "far_level": "Medium–High", "floor_level": "Medium–High",
        "Primary Façade Material": ["glass", "concrete"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "General hospital complex, tower block with podium, 8~20F",
    },
    "대규모 문화시설(공연·전시·컨벤션)": {
        "Primary Function": "Large-scale cultural / Convention",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Single landmark tower",
        "bcr_level": "Medium", "far_level": "Medium", "floor_level": "Medium",
        "Primary Façade Material": ["glass", "metal"],
        "Landscape Density Strategy": "Park-heavy composition",
        "prompt_note": "Large cultural landmark: convention center, grand civic plaza",
    },
    "광장·공공공지": {
        "Primary Function": "Open space dominant",
        "mass_types": [],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "Very low", "far_level": "Very low", "floor_level": "Very low",
        "Primary Façade Material": ["concrete"],
        "Landscape Density Strategy": "Sparse planting",
        "prompt_note": "Civic plaza, paved surface, fountain or public art, no buildings",
    },
    "주차장": {
        "Primary Function": "Open space dominant",
        "mass_types": ["Slab bar — 판상형"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "High", "far_level": "Very low", "floor_level": "Very low",
        "Primary Façade Material": ["concrete"],
        "Landscape Density Strategy": "Sparse planting",
        "prompt_note": "Surface or structured parking lot, 1~3F",
    },
    "일반산업단지(공장용지)": {
        "Primary Function": "General industrial",
        "mass_types": ["Slab bar — 판상형"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "High", "far_level": "Medium", "floor_level": "Low",
        "Primary Façade Material": ["metal", "concrete"],
        "Landscape Density Strategy": "Sparse planting",
        "prompt_note": "General industrial zone, large-footprint factory buildings",
    },
    "첨단물류단지": {
        "Primary Function": "Logistics / Distribution",
        "mass_types": ["Slab bar — 판상형"],
        "Height Strategy": "Uniform low-rise",
        "bcr_level": "High", "far_level": "Medium", "floor_level": "Low",
        "Primary Façade Material": ["metal"],
        "Landscape Density Strategy": "Sparse planting",
        "prompt_note": "Advanced logistics center, large-scale warehouse buildings",
    },
    "복합용지(혼합개발)": {
        "Primary Function": "Mixed urban fabric",
        "mass_types": ["Podium + tower — 포디움+타워"],
        "Height Strategy": "Stepped skyline",
        "bcr_level": "Medium–High", "far_level": "High", "floor_level": "Medium–High",
        "Primary Façade Material": ["glass", "concrete"],
        "Landscape Density Strategy": "Street tree dominant",
        "prompt_note": "Mixed-use development zone, podium base with tower elements",
    },
}

FLOOR_MAP = {
    "Very low": "1–3F", "Low": "2–5F", "Medium": "4–8F",
    "Medium–High": "7–15F", "High": "30F+",
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
    }
    for k, v in defs.items():
        if k not in st.session_state:
            st.session_state[k] = v

ensure_session()

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
# 범례 이미지 자동 생성
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

        draw.rectangle(
            [padding, y, padding + chip_w, y + chip_h],
            fill=(r, g, b), outline=(80, 80, 80), width=1
        )
        draw.text((padding, y + chip_h + 1), "R%d G%d B%d" % (r, g, b), fill=(140, 140, 140))

        name = row.get("name", "")
        preset_key = row.get("preset", "")
        custom = row.get("custom_desc", "").strip()

        # 영문 라벨 생성 — 한글 name 대신 영문 desc 우선 사용
        if custom:
            label_main = custom[:40]
            label_sub = ""
        elif preset_key in ZONE_PRESETS_SIMPLE:
            p = ZONE_PRESETS_SIMPLE[preset_key]
            label_main = p.get("Primary Function", preset_key)[:45]
            label_sub = p.get("prompt_note", "")[:55]
        else:
            label_main = name[:45]  # 한글이라도 일단 출력
            label_sub = ""

        draw.text((text_x, y + 4),  label_main, fill=(20, 20, 20))
        if label_sub:
            draw.text((text_x, y + 20), label_sub, fill=(90, 90, 90))
        draw.line([padding, y + row_h - 1, img_w - padding, y + row_h - 1],
                  fill=(230, 230, 230), width=1)

    return pil_to_png_bytes(img)

# ──────────────────────────────────────────────────────────────
# 픽셀 빈도 기반 색상 자동 추출 (벡터 도면 최적화)
# ──────────────────────────────────────────────────────────────
def extract_dominant_colors(img_bytes: bytes, n_colors: int = 12) -> list:
    if not (CV2_AVAILABLE and np is not None):
        return []
    arr = np.array(bytes_to_pil(img_bytes)).reshape(-1, 3)

    # 검정 배경 제거
    arr = arr[arr.sum(axis=1) > 60]
    # 흰색·회백색(도로선) 제거
    arr = arr[~((arr[:, 0] > 230) & (arr[:, 1] > 230) & (arr[:, 2] > 230))]

    if len(arr) < 100:
        return []

    # 4단위 양자화 → 안티앨리어싱 노이즈 흡수
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

        # 유사색 병합 (L1 거리 30 이내)
        if any(abs(r - er) + abs(g - eg) + abs(b - eb) < 30 for er, eg, eb, _ in results):
            continue

        results.append((r, g, b, float(ratio)))
        if len(results) >= n_colors:
            break

    return results

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
        lo = np.array([max(0, r - tol), max(0, g - tol), max(0, b - tol)], dtype=np.uint8)
        hi = np.array([min(255, r + tol), min(255, g + tol), min(255, b + tol)], dtype=np.uint8)
        mask = cv2.inRange(rgb_arr, lo, hi)
        k = np.ones((5, 5), np.uint8)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k, iterations=2)
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
# Site 마스크 + 위성 합성
# ──────────────────────────────────────────────────────────────
def extract_site_mask_from_landuse(landuse_bytes: bytes, table: list):
    if not (CV2_AVAILABLE and np is not None):
        return None, None
    rgb_arr = np.array(bytes_to_pil(landuse_bytes))
    h, w = rgb_arr.shape[:2]
    full_mask = np.zeros((h, w), dtype=np.uint8)
    for row in table:
        if not row.get("enabled", True):
            continue
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        tol = int(row.get("tolerance", 25))
        lo = np.array([max(0, r - tol), max(0, g - tol), max(0, b - tol)], dtype=np.uint8)
        hi = np.array([min(255, r + tol), min(255, g + tol), min(255, b + tol)], dtype=np.uint8)
        full_mask = cv2.bitwise_or(full_mask, cv2.inRange(rgb_arr, lo, hi))
    full_mask = cv2.morphologyEx(
        full_mask, cv2.MORPH_CLOSE, np.ones((20, 20), np.uint8), iterations=4
    )
    return full_mask, rgb_arr

def apply_satellite_outside(sat_bytes: bytes, generated_bytes: bytes, site_mask) -> bytes:
    if not (CV2_AVAILABLE and np is not None) or site_mask is None:
        return generated_bytes
    try:
        sat = bytes_to_pil(sat_bytes)
        gen = bytes_to_pil(generated_bytes)
        w_sat, h_sat = sat.size
        try:
            gen_r = gen.resize((w_sat, h_sat), Image.Resampling.LANCZOS)
        except AttributeError:
            gen_r = gen.resize((w_sat, h_sat), Image.LANCZOS)
        gen_arr = np.array(gen_r)
        sat_arr = np.array(sat)
        mask_r = cv2.resize(site_mask, (w_sat, h_sat), interpolation=cv2.INTER_NEAREST)

        # 추가: 생성 이미지에서 검정 픽셀도 외부로 처리
        black_pixels = (gen_arr.sum(axis=2) < 30)
        result = gen_arr.copy()
        result[mask_r == 0] = sat_arr[mask_r == 0]
        result[black_pixels] = sat_arr[black_pixels]  # 검정 배경 → 위성으로 교체
        return pil_to_png_bytes(Image.fromarray(result))
    except Exception:
        return generated_bytes

# ──────────────────────────────────────────────────────────────
# 흰색 구역 경계선 제거
# ──────────────────────────────────────────────────────────────
def remove_white_lines(img_bytes: bytes) -> bytes:
    """생성 이미지의 흰색 구역 경계선 제거"""
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
# 프롬프트 빌더
# ──────────────────────────────────────────────────────────────
FIXED_QUALITY_OBLIQUE = (
    "RENDER QUALITY — PHOTOREALISTIC (competition-grade archviz):\n"
    "\n"
    "Lighting:\n"
    "- Late-afternoon golden-hour sun at low angle. Strong directional shadows across facades and rooftops.\n"
    "- Warm orange-gold on sunlit faces. Cool blue-grey in shadow areas. High contrast, filmic.\n"
    "- Soft bounce light filling shadows. Ambient occlusion at ground contacts.\n"
    "\n"
    "Glass / windows:\n"
    "- Fresnel reflections: bright at edges, semi-transparent at center.\n"
    "- Sky color and surroundings reflected in glass surfaces.\n"
    "- Sharp sun glints on window frames and curtain wall edges.\n"
    "- Every window must look like real glass — NO flat colored rectangles.\n"
    "\n"
    "Brick / concrete facades:\n"
    "- Visible mortar joints, surface grain, micro-weathering.\n"
    "- Sharp shadow lines under overhangs, balconies, cornices.\n"
    "- Flat roofs: concrete texture, parapet shadow lines visible.\n"
    "\n"
    "Vegetation:\n"
    "- 3D volumetric tree canopies. Light passes through leaf edges.\n"
    "- Distinct tree crown shapes. Shadow cast on ground and adjacent surfaces.\n"
    "- Ground cover: grass texture, gravel, paving patterns — not flat green fills.\n"
    "\n"
    "Roads / ground:\n"
    "- Asphalt texture with fine grain. Curb edges casting thin shadow lines.\n"
    "- Sidewalk paving pattern visible. Crosswalk markings where appropriate.\n"
    "\n"
    "Overall: no blur, no cartoon shading, no flat uniform colors. Every pixel physically grounded.\n"
)

SKIP_COLORS = {(255, 255, 255)}  # 도로(흰색)는 zone 채우기 대상 아니므로 제외

def simplify_zone_desc(desc: str) -> str:
    d = (desc or "").strip()
    replacements = [
        ("public park with dense trees, walking paths, open lawn", "public park, dense trees, lawn, no buildings"),
        ("green buffer zone with natural vegetation, no buildings", "green buffer zone, natural vegetation, no buildings"),
        ("low-rise detached housing, 2~3F, private gardens", "detached housing, 2~3F, private gardens"),
        ("small neighborhood park, trees and seating areas", "neighborhood park, trees and seating, no buildings"),
        ("outdoor performance plaza, stage and open gathering space", "performance plaza, stage and open space"),
        ("pedestrian street, paving, no vehicles", "pedestrian street, paving, no vehicles"),
        ("community complex with cultural and welfare facilities, 2~5F", "community complex, 2~5F buildings"),
        ("walking trail through green landscape, natural path", "walking trail network, integrated with landscape, no buildings"),
        ("smart farm with greenhouse structures and agricultural facilities", "smart farm, greenhouse clusters"),
        ("infinity pool with leisure deck, resort-style design", "infinity pool, leisure deck, no buildings"),
        ("stormwater retention basin, water surface and landscape edges", "retention basin, water surface, landscape edges, no buildings"),
        ("local convenience facilities, small-scale mixed use buildings", "local mixed-use buildings, small scale"),
        ("parking lot or parking structure, organized layout", "parking area, structured layout"),
        ("healing forest with trails and meditation zones, no buildings", "healing forest, trails and meditation zones, no buildings"),
        ("resort condominium, mid-rise, leisure-oriented design", "resort condominium, mid-rise buildings"),
        ("open-air farmers market, stalls and small pavilions", "farmers market, stalls and small pavilions"),
        ("park golf course, open grass field with light facilities", "park golf course, open grass field, no buildings"),
        ("agri-processing and rural experience complex, low-rise cluster", "agri-processing complex, low-rise cluster"),
    ]
    for old, new in replacements:
        if d == old:
            return new
    return d

def is_no_building_zone(desc: str) -> bool:
    d = (desc or "").lower()
    keywords = ["park", "green buffer", "trail", "retention basin",
                "healing forest", "golf course", "pool", "no buildings"]
    return any(k in d for k in keywords)


def describe_color_name(r: int, g: int, b: int) -> str:
    special = {
        (150, 0, 200):   "deep purple",
        (200, 0, 255):   "bright purple",
        (255, 0, 255):   "magenta",
        (0, 150, 0):     "dark green",
        (0, 200, 0):     "bright green",
        (100, 255, 100): "light green",
        (50, 100, 50):   "forest green",
        (100, 180, 80):  "olive green",
        (255, 255, 0):   "bright yellow",
        (255, 150, 0):   "orange",
        (150, 100, 50):  "brown",
        (0, 200, 255):   "cyan",
        (100, 200, 255): "sky blue",
        (0, 100, 255):   "blue",
        (120, 120, 120): "grey",
        (255, 255, 255): "white",
        (0, 0, 0):       "black",
    }
    if (r, g, b) in special:
        return special[(r, g, b)]

    candidates = [
        ((255, 255, 0),   "yellow"),
        ((0, 180, 0),     "green"),
        ((0, 180, 255),   "cyan"),
        ((255, 0, 255),   "magenta"),
        ((150, 100, 50),  "brown"),
        ((120, 120, 120), "grey"),
    ]
    best_name = "colored"
    best_dist = 10**9
    for (cr, cg, cb), name in candidates:
        dist = abs(r - cr) + abs(g - cg) + abs(b - cb)
        if dist < best_dist:
            best_dist = dist
            best_name = name
    return best_name


def make_clean_bg_like_landuse(landuse_bytes: bytes, site_mask) -> bytes:
    if not (CV2_AVAILABLE and np is not None) or site_mask is None:
        return landuse_bytes
    try:
        arr = np.array(bytes_to_pil(landuse_bytes))
        h, w = arr.shape[:2]
        bg = np.full((h, w, 3), 255, dtype=np.uint8)  # 흡 배경
        bg[site_mask > 0] = arr[site_mask > 0]        # site 내부만 원본 유지
        return pil_to_png_bytes(Image.fromarray(bg))
    except Exception:
        return landuse_bytes


def build_white_mask_landuse_input(landuse_bytes, sat_bytes, site_mask):
    """
    PASS1 입력용:
    - site 내부: 원래 토지이용 색상 유지
    - site 외부: 흰색(white mask concept)
    """
    if not (CV2_AVAILABLE and np is not None) or site_mask is None:
        return landuse_bytes
    try:
        land_arr = np.array(bytes_to_pil(landuse_bytes))
        h, w = land_arr.shape[:2]
        result = np.full((h, w, 3), 255, dtype=np.uint8)
        result[site_mask > 0] = land_arr[site_mask > 0]
        return pil_to_png_bytes(Image.fromarray(result))
    except Exception:
        return landuse_bytes

(table: list, zone_masks: dict, site_area: float) -> str:
    lines = [
        "You are given ONE image.",
        "",
        "SITE PERIMETER — NON-NEGOTIABLE:",
        "- White region = development site boundary",
        "- Render ONLY inside the white region",
        "- Everything outside the white region must remain unchanged",
        "",
        "CRITICAL GEOMETRY LOCK:",
        "- The input image already defines the final layout",
        "- All colored zones and roads are fixed geometry",
        "- This is not a concept redesign task",
        "- Do not invent, rearrange, expand, simplify, or reinterpret the plan",
        "- Do not create new blocks, new roads, or new open spaces",
        "- The only allowed action is to render detailed contents inside the existing colored zones",
        "",
        "RULES (HIGHEST PRIORITY):",
        "- Preserve all zone boundaries exactly",
        "- Preserve all roads exactly",
        "- Do NOT modify geometry in any way",
        "- Only fill inside each colored zone",
        "- No text or labels",
        "- If a zone is open space, render landscape only and do not place buildings",
        "- TOTAL SITE AREA: ~%s sqm" % "{:,.0f}".format(site_area),
        "",
        "LAND USE (SECOND PRIORITY):",
    ]

    seen_rgb = set()
    for row in table:
        if not row.get("enabled", True):
            continue

        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        if (r, g, b) in seen_rgb:
            continue
        seen_rgb.add((r, g, b))

        # white / black road 계열
        if (r, g, b) in {(255, 255, 255), (0, 0, 0)}:
            lines.append("RGB(%d,%d,%d) | Road network | fixed road geometry | keep unchanged" % (r, g, b))
            continue

        preset_key = row.get("preset", "[직접입력]")
        custom = row.get("custom_desc", "").strip()
        name = row.get("name", "").strip()

        if custom:
            desc = custom
        elif preset_key in ZONE_PRESETS_SIMPLE:
            p = ZONE_PRESETS_SIMPLE[preset_key]
            desc = p.get("prompt_note", p.get("Primary Function", ""))
        else:
            desc = name

        desc = simplify_zone_desc(desc)

        if (
            is_no_building_zone(desc)
            and "parking" not in desc.lower()
            and "no buildings" not in desc.lower()
        ):
            desc += ", no buildings"

        color_name = describe_color_name(r, g, b)

        # 용도별 character intent 보강
        extra = ""

        if "단독주택" in name:
            extra = " | Residential - Detached housing | low-rise | BCR 20–40% | FAR 80–120% | 2–3F | garden plots | street trees"
        elif "콘도미니엄" in name:
            extra = " | Resort condominium | mid-rise | BCR 25–45% | FAR 120–220% | 4–8F | leisure landscape"
        elif "공원" in name and "골프" not in name and "마을" not in name:
            extra = " | Public park | no buildings | dense trees | lawn | walking paths"
        elif "마을공원" in name:
            extra = " | Neighborhood park | no buildings | trees | seating | pocket open space"
        elif "녹지" in name:
            extra = " | Green buffer | no buildings | natural vegetation"
        elif "치유의숲" in name:
            extra = " | Healing forest | no buildings | forest trails | meditation spaces"
        elif "파크골프" in name:
            extra = " | Park golf course | no buildings | open grass field"
        elif "저류지" in name:
            extra = " | Retention basin | no buildings | water surface | landscape edge"
        elif "주차장" in name:
            extra = " | Parking area | paved surface | structured layout"
        elif "복합커뮤니티" in name:
            extra = " | Community complex | mid-rise | BCR 30–50% | FAR 100–180% | 2–5F | civic plaza"
        elif "주민편의" in name:
            extra = " | Local mixed-use | low-rise | BCR 30–50% | FAR 80–150% | 2–4F | neighborhood frontage"
        elif "6차산업" in name:
            extra = " | Agri-processing complex | low-rise cluster | productive landscape"
        elif "스마트팜" in name:
            extra = " | Smart farm | greenhouse clusters | agricultural facilities"
        elif "파머스마켓" in name:
            extra = " | Farmers market | stalls and small pavilions | active public space"
        elif "보행자전용" in name:
            extra = " | Pedestrian street | paving | no vehicles"
        elif "산책로" in name:
            extra = " | Walking trail | landscape path | no buildings"

        if extra:
            lines.append("RGB(%d,%d,%d) | %s zone%s" % (r, g, b, color_name, extra))
        else:
            lines.append("RGB(%d,%d,%d) | %s zone | %s" % (r, g, b, color_name, desc))

    lines += [
        "",
        "TASK:",
        "Fill the white site region with a top-down 2D masterplan layout.",
        "",
        "OUTPUT STYLE (LOW PRIORITY):",
        "- Premium Korean urban development masterplan illustration",
        "- Fill the entire site completely — no empty areas",
        "",
        "BUILDINGS:",
        "- Many individual building footprints",
        "- Use articulated shapes: L-shape, U-shape, courtyard, slab, podium",
        "- Realistic spacing and setbacks per zone type",
        "",
        "ROADS:",
        "- Strong road hierarchy — primary, secondary, local access roads clearly differentiated",
        "",
        "LANDSCAPE:",
        "- Rich and layered — tree canopy clusters, street trees, central greens, pocket parks",
        "- Each zone must have visually distinct character matching its assigned program",
        "- High visual density. No large empty areas",
    ]

    return "\n".join(lines).strip()


def build_pass2_prompt(table: list) -> str:
    lines = [
        "You are given TWO images:",
        "- Image 1: 2D top-down masterplan layout to convert.",
        "- Image 2: Original land use plan map (zone color reference).",
        "",
        "TASK: Convert Image 1 into a photorealistic 3D archviz rendering.",
        "Apply facade materials and building heights per zone using the legend below.",
        "",
        "LAND USE LEGEND:",
    ]
    seen_rgb = set()
    for row in table:
        if not row.get("enabled", True):
            continue
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        if (r, g, b) in SKIP_COLORS:
            continue
        if (r, g, b) in seen_rgb:
            continue
        seen_rgb.add((r, g, b))
        preset_key = row.get("preset", "[직접입력]")
        custom = row.get("custom_desc", "").strip()
        if custom:
            desc = custom[:80]
        elif preset_key in ZONE_PRESETS_SIMPLE:
            p = ZONE_PRESETS_SIMPLE[preset_key]
            desc = p.get("prompt_note", "")
        else:
            desc = row.get("name", "")
        lines.append("  RGB(%d,%d,%d) = %s" % (r, g, b, desc))

    lines += [
        "",
        "- Keep all geometry exactly as in Image 1. Do NOT redesign.",
        "- Maintain exact geographic extent. Do NOT crop or zoom.",
        "CAMERA: 45-55 degree oblique aerial view.",
        "",
        FIXED_QUALITY_OBLIQUE,
        "Negative: No text, no labels. No white blank areas.",
    ]
    return "\n".join(lines).strip()


def build_pass3_prompt(angle: int) -> str:
    return (
        "Same scene, %d-degree oblique aerial view. "
        "Preserve exact layout and all building massing. "
        "Golden-hour sunlight, realistic glass reflections, crisp facade highlights. "
        "No labels, no text." % angle
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
        for j, img_bytes in enumerate(outputs[row_start:row_start + 2]):
            i = row_start + j
            with cols[j]:
                im = bytes_to_pil(img_bytes)
                w, h = im.size
                is_sel = (st.session_state[sel_key] == i)
                border = "2px solid #2563EB" if is_sel else "1px solid #E5E7EB"
                st.markdown(
                    '<div style="border:%s;border-radius:10px;padding:6px;">' % border,
                    unsafe_allow_html=True
                )
                st.image(im, caption="%s #%d — %dx%d" % (label, i + 1, w, h),
                         use_container_width=True)
                st.markdown('</div>', unsafe_allow_html=True)
                btn_label = "선택됨 #%d" % (i + 1) if is_sel else "선택 #%d" % (i + 1)
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

# ══════════════════════════════════════════════════════════════
# STEP 0: 이미지 입력
# ══════════════════════════════════════════════════════════════
if cur_step == 0:
    st.markdown('<div class="section-header">① 이미지 입력</div>', unsafe_allow_html=True)

    col_landuse, col_sat = st.columns(2, gap="large")

    with col_landuse:
        st.markdown("**토지이용계획도** ⭐ 필수")
        st.caption("수치지형도 백판 위에 토지이용계획이 색상으로 표시된 이미지")
        f2 = st.file_uploader("토지이용계획도 업로드", type=["png", "jpg", "jpeg"], key="up_landuse")
        if f2:
            st.session_state.img_landuse_bytes = f2.getvalue()
        if st.session_state.img_landuse_bytes:
            st.image(bytes_to_pil(st.session_state.img_landuse_bytes),
                     use_container_width=True, caption="토지이용계획도")

    with col_sat:
        st.markdown("**위성사진** (선택)")
        st.caption("동일 위치 위성사진 — site 외부 컨텍스트 복원용")
        f3 = st.file_uploader("위성사진 업로드", type=["png", "jpg", "jpeg"], key="up_sat")
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
    st.caption("각 토지이용 항목의 RGB 색상, 면적, 프리셋을 설정하세요.")
    st.caption("⚠️ 자동 추출값은 참고용입니다. 정확한 RGB는 범례표를 보고 직접 수정하세요.")

    # ── 엑셀 업로드 ──────────────────────────────────────────
    with st.expander("📥 엑셀로 토지이용계획표 불러오기", expanded=False):
        st.caption("컬럼 순서: 용도명 / R / G / B / 면적(㎡) / 용도설명(영문) / 프리셋(선택)")

        if st.button("📄 템플릿 다운로드"):
            import io as _io
            try:
                import openpyxl as _openpyxl
                _wb = _openpyxl.Workbook()
                _ws = _wb.active
                _ws.title = "토지이용계획표"
                _ws.append(["용도명", "R", "G", "B", "면적(㎡)", "용도설명(영문)", "프리셋"])
                for _r in [
                    ("단독주택", 255, 255, 127, 10000, "Low-rise detached housing, 2~3F, garden plots", "단독주택"),
                    ("공원", 0, 165, 0, 15000, "Neighborhood park, tree canopy, walking paths", "근린공원·주제공원"),
                    ("숙박시설", 255, 191, 127, 12000, "resort hotel with amenity facilities, 5~10F, warm facade", "[직접입력]"),
                    ("치유의숲", 127, 255, 0, 20000, "healing forest with walking trails, meditation zones, no buildings", "[직접입력]"),
                ]:
                    _ws.append(_r)
                _buf = _io.BytesIO()
                _wb.save(_buf)
                _buf.seek(0)
                st.download_button(
                    "⬇️ 템플릿 xlsx 다운로드",
                    data=_buf.getvalue(),
                    file_name="토지이용계획표_템플릿.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            except ImportError:
                st.error("openpyxl 패키지가 필요합니다. pip install openpyxl")

        xl_file = st.file_uploader("엑셀 파일 업로드 (.xlsx)", type=["xlsx"], key="xl_upload")

        if xl_file and st.button("테이블에 적용", type="primary", key="apply_xl"):
            try:
                import openpyxl as _openpyxl
                import io as _io

                _wb = _openpyxl.load_workbook(_io.BytesIO(xl_file.getvalue()), data_only=True)
                _ws = _wb.active

                _new_rows = []
                for _row in _ws.iter_rows(min_row=2, values_only=True):
                    # 완전 빈 행 스킵
                    if _row is None or all(v is None or str(v).strip() == "" for v in _row):
                        continue

                    # 용도명 없으면 스킵
                    if _row[0] is None or str(_row[0]).strip() == "":
                        continue

                    _name = str(_row[0]).strip()
                    _r = max(0, min(255, int(float(_row[1] or 0))))
                    _g = max(0, min(255, int(float(_row[2] or 0))))
                    _b = max(0, min(255, int(float(_row[3] or 0))))
                    _area = float(_row[4] or 0)
                    _custom = str(_row[5] or "").strip()
                    _preset = str(_row[6] or "[직접입력]").strip()

                    if _preset not in PRESET_OPTIONS:
                        _preset = "[직접입력]"

                    _new_rows.append({
                        "name": _name,
                        "r": _r,
                        "g": _g,
                        "b": _b,
                        "preset": _preset,
                        "custom_desc": _custom,
                        "area_sqm": _area,
                        "tolerance": 18,
                        "enabled": True,
                    })

                # 업로드한 엑셀 내용만 남기기
                st.session_state.land_use_table = _new_rows
                st.session_state["_auto_colors"] = []

                if _new_rows:
                    st.success("%d개 항목 불러옴" % len(_new_rows))
                else:
                    st.warning("엑셀에서 불러온 유효 행이 없습니다. 2행부터 데이터를 확인하세요.")

                st.rerun()

            except Exception as _e:
                st.error("엑셀 파일 오류: %s" % str(_e))

    # ── 테이블 편집 ───────────────────────────────────────
    st.markdown('<div class="sub-label">토지이용 항목 목록</div>', unsafe_allow_html=True)
    table = st.session_state.land_use_table

    if not table:
        st.info("현재 등록된 토지이용 항목이 없습니다. 엑셀 파일을 업로드해 테이블에 적용하세요.")
    to_delete = []

    for i, row in enumerate(table):
        c_en, c_name, c_r, c_g, c_b, c_tol, c_area, c_preset, c_chip, c_del = st.columns(
            [0.4, 1.6, 0.6, 0.6, 0.6, 0.7, 1.1, 2.0, 0.5, 0.4]
        )
        r, g, b = int(row["r"]), int(row["g"]), int(row["b"])
        hex_color = "#%02x%02x%02x" % (r, g, b)

        table[i]["enabled"]   = c_en.checkbox("", value=row.get("enabled", True), key="en_%d" % i)
        table[i]["name"]      = c_name.text_input("", value=row.get("name", ""), key="name_%d" % i, label_visibility="collapsed")
        table[i]["r"]         = c_r.number_input("R", 0, 255, r, key="r_%d" % i, label_visibility="collapsed")
        table[i]["g"]         = c_g.number_input("G", 0, 255, g, key="g_%d" % i, label_visibility="collapsed")
        table[i]["b"]         = c_b.number_input("B", 0, 255, b, key="b_%d" % i, label_visibility="collapsed")
        table[i]["tolerance"] = c_tol.number_input("Tol", 5, 80, int(row.get("tolerance", 25)), key="tol_%d" % i, label_visibility="collapsed")
        table[i]["area_sqm"]  = c_area.number_input("sqm", 0.0, 9999999.0, float(row.get("area_sqm", 10000.0)), step=500.0, key="area_%d" % i, label_visibility="collapsed")

        cur_preset = row.get("preset", "[직접입력]")
        if cur_preset not in PRESET_OPTIONS:
            cur_preset = "[직접입력]"
        table[i]["preset"] = c_preset.selectbox(
            "", PRESET_OPTIONS,
            index=PRESET_OPTIONS.index(cur_preset),
            key="preset_%d" % i,
            label_visibility="collapsed"
        )

        c_chip.markdown(
            '<div style="margin-top:6px;width:26px;height:26px;border-radius:5px;'
            'background:%s;border:1px solid rgba(0,0,0,0.2);"></div>' % hex_color,
            unsafe_allow_html=True
        )
        if c_del.button("x", key="del_%d" % i):
            to_delete.append(i)

        # 직접입력 선택 시 설명 필드
        if table[i]["preset"] == "[직접입력]":
            table[i]["custom_desc"] = st.text_input(
                "용도 설명 (영문 권장)",
                value=row.get("custom_desc", ""),
                key="cdesc_%d" % i,
                placeholder="예: glamping resort with log cabins, 1~2F, natural wood facade",
                help="이 설명이 범례 이미지와 프롬프트에 직접 사용됩니다"
            )

    if to_delete:
        st.session_state.land_use_table = [r for idx, r in enumerate(table) if idx not in to_delete]
        st.rerun()

    # ── RGB 추출 미리보기 ────────────────────────────────
    st.markdown('<div class="sub-label">RGB 추출 미리보기</div>', unsafe_allow_html=True)
    if st.session_state.img_landuse_bytes and CV2_AVAILABLE:
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

    # ── 면적 합계 ──────────────────────────────────────
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
        st.error("google-genai 패키지가 없습니다. pip install google-genai 후 재시작하세요.")
        st.stop()

    if not st.session_state.img_landuse_bytes:
        st.error("토지이용계획도가 없습니다. 이전 단계로 돌아가세요.")
        st.stop()

    api_key = st.text_input("Google AI Studio API 키", type="password").strip()
    model_name = st.selectbox(
        "모델 선택",
        [
            "gemini-3-pro-image-preview",
            "gemini-3.1-flash-image-preview",
        ],
        index=1
    )
    st.caption("선택된 모델: %s" % model_name)

    # ── 공통 준비 ──────────────────────────────────────────
    table = st.session_state.land_use_table

    pass1_site_mask = None
    if CV2_AVAILABLE:
        pass1_site_mask, _ = extract_site_mask_from_landuse(st.session_state.img_landuse_bytes, table)

    if pass1_site_mask is not None:
        input_for_pass1 = build_white_mask_landuse_input(
            st.session_state.img_landuse_bytes,
            st.session_state.img_sat_bytes,
            pass1_site_mask
        )
        st.info("PASS1 입력: white mask 기반 토지이용계획도")
    else:
        input_for_pass1 = st.session_state.img_landuse_bytes
        st.info("PASS1 입력: 토지이용계획도")

    with st.expander("PASS1 입력 이미지 미리보기", expanded=False):
        st.image(bytes_to_pil(input_for_pass1), use_container_width=True)

    # 범례 이미지 — UI 미리보기 전용 (API 입력에는 사용 안 함)
    legend_bytes = build_legend_image(table)
    if legend_bytes:
        st.markdown('<div class="sub-label">범례 이미지 미리보기 (UI 확인용)</div>',
                    unsafe_allow_html=True)
        st.image(bytes_to_pil(legend_bytes), width=420,
                 caption="범례 이미지 — 사용자 확인용 미리보기 (PASS1 모델 입력에는 사용하지 않음)")

    # 구역 마스크 (위치 정보용)
    zone_masks = {}
    if CV2_AVAILABLE:
        zone_masks = extract_zone_masks(st.session_state.img_landuse_bytes, table)

    # 프롬프트
    pass1_prompt = build_pass1_prompt(table, zone_masks, st.session_state.site_area_sqm)
    pass2_prompt = build_pass2_prompt(table)

    # 개발자 확인
    dev_pw = st.text_input("개발자 비밀번호", type="password", key="dev_pw")
    if dev_pw == "126791":
        with st.expander("PASS1 프롬프트", expanded=False):
            st.code(pass1_prompt, language="text")
            st.write("---- PROMPT LENGTH ----", len(pass1_prompt))
        with st.expander("PASS2 프롬프트", expanded=False):
            st.code(pass2_prompt, language="text")
        if legend_bytes:
            with st.expander("범례 이미지 (풀사이즈)", expanded=False):
                st.image(bytes_to_pil(legend_bytes), use_container_width=True)

    st.markdown("---")

    # ── PASS 1 ────────────────────────────────────────────
    st.markdown("### STEP 1 — 2D 배치도 생성")

    def run_pass1():
        client = genai.Client(api_key=api_key)
        try:
            # PASS1은 반드시 단일 이미지만 사용
            resp = client.models.generate_content(
                model=model_name,
                contents=make_contents(pass1_prompt, [input_for_pass1])
            )
            out = get_image_from_resp(resp)
            if out:
                out_img = bytes_to_pil(out)
                st.caption(
                    "[DEBUG] PASS1 model=%s / size=%dx%d" % (
                        model_name, out_img.size[0], out_img.size[1]
                    )
                )
                out = remove_white_lines(out)
                if CV2_AVAILABLE:
                    site_mask, _ = extract_site_mask_from_landuse(
                        st.session_state.img_landuse_bytes, table
                    )
                    if st.session_state.img_sat_bytes and site_mask is not None:
                        # 위성사진 있으면 위성으로 외부 복원
                        out = apply_satellite_outside(
                            st.session_state.img_sat_bytes, out, site_mask
                        )
                    elif site_mask is not None:
                        # 위성사진 없으면 흰 배경으로 외부 복원
                        clean_bg = make_clean_bg_like_landuse(
                            st.session_state.img_landuse_bytes, site_mask
                        )
                        out = apply_satellite_outside(clean_bg, out, site_mask)
                st.session_state.pass1_outputs.append(out)
                st.session_state.pass1_selected_idx = len(st.session_state.pass1_outputs) - 1
                st.session_state.pass1_output_bytes = out
                st.session_state.pass2_outputs = []
                st.session_state.pass3_outputs = []
                st.session_state.pass2_output_bytes = None
            else:
                st.warning("이미지가 반환되지 않았습니다.")
        except Exception as e:
            st.error("PASS1 오류: %s" % str(e))

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

    if len(api_key) >= 10:
        if st.button("모델 비교 테스트 (2회 연속 생성)", key="model_compare"):
            st.session_state.pass1_outputs = []
            st.session_state.pass1_selected_idx = 0
            for _ in range(2):
                with st.spinner("비교 생성 중 (%d/2)..." % (_ + 1)):
                    run_pass1()
            st.rerun()

    if st.session_state.pass1_outputs:
        st.markdown("**STEP 1 결과 — 최적 이미지 선택**")
        selected_p1 = render_selector(st.session_state.pass1_outputs, "pass1_selected_idx", "STEP1")
        if selected_p1:
            st.session_state.pass1_output_bytes = selected_p1
        st.download_button("STEP 1 다운로드",
                           data=st.session_state.pass1_output_bytes,
                           file_name="planvision_step1_2d.png", mime="image/png")

    st.markdown("---")

    # ── PASS 2 ────────────────────────────────────────────
    st.markdown("### STEP 2 — 3D 조감도 생성")
    p2_disabled = len(api_key) < 10 or not st.session_state.pass1_output_bytes

    def run_pass2():
        client = genai.Client(api_key=api_key)
        try:
            images = [
                st.session_state.pass1_output_bytes,   # Image 1: 2D 배치도
                st.session_state.img_landuse_bytes,    # Image 2: 원본 토지이용도
            ]
            resp = client.models.generate_content(
                model=model_name,
                contents=make_contents(pass2_prompt, images)
            )
            out = get_image_from_resp(resp)
            if out:
                st.session_state.pass2_outputs.append(out)
                st.session_state.pass2_selected_idx = len(st.session_state.pass2_outputs) - 1
                st.session_state.pass2_output_bytes = out
                st.session_state.pass3_outputs = []
            else:
                st.warning("이미지가 반환되지 않았습니다.")
        except Exception as e:
            st.error("PASS2 오류: %s" % str(e))

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
        st.download_button("STEP 2 다운로드",
                           data=st.session_state.pass2_output_bytes,
                           file_name="planvision_step2_3d.png", mime="image/png")

        st.markdown("---")

        # ── PASS 3 ────────────────────────────────────────
        st.markdown("### STEP 3 — 각도 변환 (선택사항)")
        p3_angle = st.selectbox(
            "변환 각도", ["30° (저각도)", "45° (중각도)", "60° (준조감도)"], index=1
        )
        angle_deg = {"30° (저각도)": 30, "45° (중각도)": 45, "60° (준조감도)": 60}[p3_angle]
        p3_disabled = len(api_key) < 10 or not st.session_state.pass2_output_bytes

        def run_pass3():
            client = genai.Client(api_key=api_key)
            try:
                resp = client.models.generate_content(
                    model=model_name,
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
                    st.warning("이미지가 반환되지 않았습니다.")
            except Exception as e:
                st.error("PASS3 오류: %s" % str(e))

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
                "최종 다운로드 (STEP 3)", data=p3_final,
                file_name="planvision_final_%ddeg.png" % angle_deg,
                mime="image/png", use_container_width=True
            )
        else:
            st.download_button(
                "최종 다운로드 (STEP 2)",
                data=st.session_state.pass2_output_bytes,
                file_name="planvision_final_step2.png",
                mime="image/png"
            )
