"""Labeled benchmark corpus for CivicLens AI.

No municipal complaint dataset ships with this project, so Phase 2 trains and
evaluates its models on this **seeded, labeled corpus** instead.  Everything
here is generated deterministically (fixed seeds), and the README states
plainly that every reported metric is measured on this corpus - never invented.

The corpus is designed to exercise the real pipeline:

* 25 real Bengaluru wards across eight BBMP zones, each with schools/hospitals
  and a "personality" (volume, severity and resolution-speed profile) so the
  dashboards show realistic ward-to-ward patterns.
* 10 complaint categories with parallel English / Hindi / Kannada phrasings
  (the Hindi and Kannada templates are translations of the corresponding
  English ones, which gives multilingual duplicate pairs real ground truth).
* 180 days of daily complaint history with weekly seasonality and a monsoon
  burst, used for hotspot forecasting.
* Explicit cross-language duplicate groups so duplicate-detection precision can
  be measured.
* Synthetic before/after image pairs with labels for the resolution comparator.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta

from PIL import Image, ImageDraw

from app.models.complaint import ComplaintCategory, ComplaintStatus
from app.models.ward import GeoPoint

# --- Geography ----------------------------------------------------------------
# 25 real Bengaluru wards spread across the eight BBMP zones.  Coordinates are
# the ward centroids; each ward gets a square polygon of ~3.5 km per side.
_GRID = [
    # (ward_no, name, zone, lng, lat)
    (1, "Jayanagar", "South Zone", 77.500, 12.905),
    (2, "Basavanagudi", "South Zone", 77.536, 12.905),
    (3, "Banashankari", "South Zone", 77.572, 12.905),
    (4, "JP Nagar", "South Zone", 77.608, 12.905),
    (5, "BTM Layout", "South-East Zone", 77.644, 12.905),
    (6, "Koramangala", "South-East Zone", 77.500, 12.945),
    (7, "HSR Layout", "South-East Zone", 77.536, 12.945),
    (8, "Indiranagar", "East Zone", 77.572, 12.945),
    (9, "Shivajinagar", "Central Zone", 77.608, 12.945),
    (10, "Malleshwaram", "West Zone", 77.644, 12.945),
    (11, "Rajajinagar", "West Zone", 77.500, 12.985),
    (12, "Vijayanagar", "West Zone", 77.536, 12.985),
    (13, "Whitefield", "East Zone", 77.572, 12.985),
    (14, "Hebbal", "North Zone", 77.608, 12.985),
    (15, "Yelahanka", "North Zone", 77.644, 12.985),
    (16, "Marathahalli", "South-East Zone", 77.680, 12.905),
    (17, "Bellandur", "South-East Zone", 77.680, 12.945),
    (18, "Sarjapur Road", "South-East Zone", 77.680, 12.985),
    (19, "Electronic City", "South Zone", 77.660, 12.845),
    (20, "Bommanahalli", "South Zone", 77.590, 12.845),
    (21, "Rajajeshwari Nagar", "South Zone", 77.460, 12.845),
    (22, "Dasarahalli", "North Zone", 77.500, 13.045),
    (23, "Jalahalli", "North Zone", 77.536, 13.045),
    (24, "Kengeri", "West Zone", 77.460, 12.905),
    (25, "Mahadevapura", "East Zone", 77.644, 12.985),
]

_CELL_HALF_LNG = 0.016  # ~1.8 km half-width
_CELL_HALF_LAT = 0.018  # ~2.0 km half-height

# Plausible street names per zone flavour; the seed picks from the ward's zone
# so Jayanagar reports "9th Cross, 4th Block" while Whitefield reports named
# tech-corridor roads.  This is what keeps the addresses from looking uniform.
_STREETS_BY_ZONE: dict[str, list[str]] = {
    "South Zone": [
        "10th Main Road", "4th Cross Road", "Gandhi Bazaar Road", "Kanakapura Main Road",
        "Jayanagar 11th Block Road", "Banashankari Temple Street", "100 Feet Road",
    ],
    "South-East Zone": [
        "27th Main Road", "HSR Sector 2 Road", "100 Feet Road", "Sarjapur Outer Ring Road",
        "Koramangala 5th Block Road", "BTM 16th Main Road", "Marathahalli Bridge Road",
    ],
    "East Zone": [
        "100 Feet Road", "CMS Road", "Old Airport Road", "Varthur Main Road",
        "Whitefield Main Road", "ITPL Main Road", "Kundalahalli Gate Road",
    ],
    "Central Zone": [
        "Commercial Street", "Shivajinagar Main Road", "Cubbon Road", "Russell Market Road",
    ],
    "West Zone": [
        "Dr Rajkumar Road", "1st Main Road", "Mahalakshmi Layout Road",
        "Mysore Road", "Rajajinagar Entrance Road",
    ],
    "North Zone": [
        "Banaswadi Main Road", "Hennur Main Road", "Bellary Road",
        "Yelahanka New Town Road", "Jalahalli Cross Road",
    ],
}

_LANDMARKS = [
    "Near bus stop", "Opposite the market", "Behind the temple", "Next to the school",
    "Near the hospital gate", "Beside the park", "At the junction", "Near the metro station",
    "Opposite the apartment complex", "Beside the lake",
]

# --- Ward "personalities" -----------------------------------------------------
# Real cities are not uniform: dense commercial wards generate more complaints,
# poorer wards drain slower.  These multipliers give the charts visible
# structure (that is the point of the demo) while staying deterministic.
#
#   volume   – multiplier on complaint rate (density of population/commerce)
#   severity – additive shift on severity sampling (infrastructure condition)
#   speed    – multiplier on resolution time (crew capacity); >1 = slower
_WARD_PROFILE: dict[int, dict[str, float]] = {
    1:  {"volume": 1.15, "severity": 0.0, "speed": 0.85},   # Jayanagar: organised
    2:  {"volume": 1.00, "severity": 0.1, "speed": 0.95},   # Basavanagudi
    3:  {"volume": 1.20, "severity": 0.2, "speed": 1.25},   # Banashankari: sprawling
    4:  {"volume": 1.05, "severity": 0.0, "speed": 0.90},   # JP Nagar
    5:  {"volume": 1.30, "severity": 0.1, "speed": 1.10},   # BTM: dense rentals
    6:  {"volume": 1.45, "severity": 0.3, "speed": 1.35},   # Koramangala: nightlife+floods
    7:  {"volume": 1.25, "severity": 0.1, "speed": 0.95},   # HSR: civic-minded
    8:  {"volume": 1.10, "severity": 0.0, "speed": 0.80},   # Indiranagar: well-served
    9:  {"volume": 1.55, "severity": 0.4, "speed": 1.55},   # Shivajinagar: dense, slow
    10: {"volume": 0.95, "severity": 0.0, "speed": 0.85},   # Malleshwaram
    11: {"volume": 1.15, "severity": 0.2, "speed": 1.20},   # Rajajinagar
    12: {"volume": 1.00, "severity": 0.1, "speed": 1.00},   # Vijayanagar
    13: {"volume": 1.50, "severity": 0.3, "speed": 1.30},   # Whitefield: construction
    14: {"volume": 1.20, "severity": 0.2, "speed": 1.15},   # Hebbal: lake overflow
    15: {"volume": 0.85, "severity": 0.0, "speed": 1.05},   # Yelahanka: peripheral
    16: {"volume": 1.40, "severity": 0.3, "speed": 1.30},   # Marathahalli: tech sprawl
    17: {"volume": 1.25, "severity": 0.2, "speed": 1.10},   # Bellandur: lake fumes
    18: {"volume": 1.35, "severity": 0.2, "speed": 1.25},   # Sarjapur Road: rapid growth
    19: {"volume": 1.30, "severity": 0.2, "speed": 1.00},   # Electronic City
    20: {"volume": 1.20, "severity": 0.2, "speed": 1.20},   # Bommanahalli
    21: {"volume": 1.00, "severity": 0.1, "speed": 1.05},   # Rajajeshwari Nagar
    22: {"volume": 1.10, "severity": 0.3, "speed": 1.40},   # Dasarahalli: underserved
    23: {"volume": 0.90, "severity": 0.1, "speed": 1.10},   # Jalahalli
    24: {"volume": 0.95, "severity": 0.1, "speed": 1.15},   # Kengeri
    25: {"volume": 1.30, "severity": 0.3, "speed": 1.25},   # Mahadevapura: IT flood zone
}

_SENSITIVE_NAMES = {
    "school": [
        "Government Higher Primary School",
        "St. Mary's High School",
        "Vidya Vardhaka School",
        "Nagarjuna Public School",
    ],
    "hospital": [
        "City General Hospital",
        "Suguna Health Centre",
        "Apex Multispeciality Hospital",
        "Ward Community Clinic",
    ],
}

CATEGORY_BASE_WEIGHT: dict[ComplaintCategory, float] = {
    ComplaintCategory.ROADS: 1.6,
    ComplaintCategory.DRAINAGE: 1.2,
    ComplaintCategory.WATER_SUPPLY: 0.9,
    ComplaintCategory.SANITATION: 0.7,
    ComplaintCategory.WASTE_MANAGEMENT: 1.1,
    ComplaintCategory.STREETLIGHT: 0.9,
    ComplaintCategory.TRAFFIC_SIGNAL: 0.5,
    ComplaintCategory.NOISE: 0.5,
    ComplaintCategory.PARKS_TREES: 0.5,
    ComplaintCategory.OTHER: 0.6,
}

# --- Complaint templates ------------------------------------------------------
# Each entry is (title, description).  Index 0 and 1 of every category have
# Hindi and Kannada translations, which are used as cross-language duplicates.
TEMPLATES: dict[ComplaintCategory, dict[str, list[tuple[str, str]]]] = {
    ComplaintCategory.ROADS: {
        "en": [
            (
                "Deep pothole on 10th Main Road",
                "A large pothole has formed near the bus stop after the rains. "
                "Two-wheelers are skidding and it is dangerous at night.",
            ),
            (
                "Broken road surface near market",
                "The asphalt has crumbled over a 20 metre stretch in front of the "
                "vegetable market. Vehicles are swerving into oncoming traffic.",
            ),
            (
                "Pothole cluster at junction",
                "Three deep potholes at the junction make it hard for cars and autos "
                "to pass. Water collects inside them.",
            ),
            (
                "Damaged footpath slabs",
                "Several footpath slabs are broken and raised, causing pedestrians to "
                "trip near the school gate.",
            ),
            (
                "Road caved in after pipeline work",
                "The road has sunk where the water board dug it up last month. The "
                "barricade was removed and the gap is open.",
            ),
            (
                "Unsafe speed breaker",
                "An unmarked speed breaker was built without paint; bikes jump and "
                "nearly collide with pedestrians.",
            ),
            (
                "Pothole filled with rainwater",
                "A wide pothole in the middle of the lane is full of muddy water. It "
                "is invisible to drivers at night and has already damaged two cars.",
            ),
            (
                "Footpath blocked by rubble",
                "Construction rubble has been left on the footpath for two weeks. "
                "People with prams are forced onto the busy road.",
            ),
        ],
        "hi": [
            (
                "सड़क पर गहरा गड्ढा",
                "बारिश के बाद बस स्टॉप के पास बड़ा गड्ढा बन गया है। दोपहिया वाहन "
                "फिसल रहे हैं और रात में खतरा बना हुआ है।",
            ),
            (
                "बाजार के सामने टूटी सड़क",
                "बाजार के सामने बीस मीटर तक सड़क की सतह टूट गई है और कई गड्ढे हैं। "
                "वाहनों को बचाकर निकलना मुश्किल है।",
            ),
        ],
        "kn": [
            (
                "ರಸ್ತೆಯಲ್ಲಿ ಆಳವಾದ ಗುಂಡಿ",
                "ಮಳೆಯ ನಂತರ ಬಸ್ ನಿಲ್ದಾಣದ ಬಳಿ ದೊಡ್ಡ ಗುಂಡಿ ಉಂಟಾಗಿದೆ. ದ್ವಿಚಕ್ರ "
                "ವಾಹನಗಳು ಜಾರುತ್ತಿವೆ ಮತ್ತು ರಾತ್ರಿ ಅಪಾಯವಿದೆ.",
            ),
            (
                "ಮಾರುಕಟ್ಟೆ ಎದುರು ಒಡೆದ ರಸ್ತೆ",
                "ಮಾರುಕಟ್ಟೆ ಎದುರು ಇಪ್ಪತ್ತು ಮೀಟರ್ ಉದ್ದಕ್ಕೂ ರಸ್ತೆ ಮೇಲ್ಮೈ ಒಡೆದು ಹಲವು "
                "ಗುಂಡಿಗಳಾಗಿವೆ. ವಾಹನಗಳು ಪಕ್ಕಕ್ಕೆ ತಿರುಗಿ ಹೋಗಬೇಕಾಗಿದೆ.",
            ),
        ],
    },
    ComplaintCategory.DRAINAGE: {
        "en": [
            (
                "Storm drain blocked with silt",
                "The storm-water drain on 4th Cross is blocked. Even a short shower "
                "floods the road up to knee height.",
            ),
            (
                "Sewage overflowing on street",
                "A manhole is overflowing and grey water is running along the street. "
                "The smell is unbearable.",
            ),
            (
                "Water logging outside school",
                "Rainwater has not drained for three days outside the school. Children "
                "have to walk through dirty water.",
            ),
            (
                "Open drain without cover",
                "The drain cover is missing near the park entrance. It is a serious "
                "fall hazard at night.",
            ),
            (
                "Flooded underpass",
                "The underpass fills with water whenever it rains and two-wheelers "
                "stall in the middle.",
            ),
            (
                "Drain water entering homes",
                "Water from the blocked drain is entering the ground floor of our "
                "building. Families cannot stay there.",
            ),
            (
                "Choked drain causing foul smell",
                "The storm drain has not been desilted this year. It is choked and the "
                "whole lane smells of sewage.",
            ),
            (
                "Rainwater pipeline leaking on road",
                "A storm-water pipe joint is broken and water is pouring onto the road, "
                "eroding the edge of the footpath.",
            ),
        ],
        "hi": [
            (
                "नाला बंद होने से सड़क पर पानी",
                "चौथी क्रॉस पर बरसाती नाला सिल्ट से बंद है। थोड़ी बारिश में ही सड़क "
                "पर घुटनों तक पानी भर जाता है।",
            ),
            (
                "सीवेज का पानी सड़क पर",
                "मैनहोल ओवरफ्लो हो रहा है और गंदा पानी सड़क पर बह रहा है। बदबू से "
                "गुजरना मुश्किल है।",
            ),
        ],
        "kn": [
            (
                "ಚರಂಡಿ ಕಟ್ಟಿ ರಸ್ತೆಯಲ್ಲಿ ನೀರು",
                "ನಾಲ್ಕನೇ ಕ್ರಾಸ್ನಲ್ಲಿ ಮಳೆನೀರಿನ ಚರಂಡಿ ಕೆಸರಿನಿಂದ ಕಟ್ಟಿದೆ. ಸ್ವಲ್ಪ ಮಳೆ "
                "ಬಂದರೂ ರಸ್ತೆಯಲ್ಲಿ ಮೊಣಕಾಲಿನವರೆಗೆ ನೀರು ನಿಲ್ಲುತ್ತದೆ.",
            ),
            (
                "ಒಳಚರಂಡಿ ನೀರು ರಸ್ತೆಗೆ",
                "ಮ್ಯಾನ್ಹೋಲ್ ಉಕ್ಕಿ ಬರುತ್ತಿದೆ ಮತ್ತು ಕೊಳಚೆ ನೀರು ರಸ್ತೆಯಲ್ಲಿ ಹರಿಯುತ್ತಿದೆ. "
                "ವಾಸನೆ ತಡೆಯಲಾಗುತ್ತಿಲ್ಲ.",
            ),
        ],
    },
    ComplaintCategory.WATER_SUPPLY: {
        "en": [
            (
                "No water supply for five days",
                "Our street has not received municipal water for five days. Residents "
                "are buying tankers at high cost.",
            ),
            (
                "Pipeline leaking continuously",
                "A water main is leaking at the corner and clean water has been running "
                "into the drain all week.",
            ),
            (
                "Dirty water from tap",
                "The water coming from the tap is brown and smells metallic. Several "
                "children in the lane have fallen ill.",
            ),
            (
                "Low pressure in upper floors",
                "Supply pressure is so low that water does not reach the second floor. "
                "We need a booster or a new line.",
            ),
            (
                "Water tanker not arriving",
                "The ward tanker has skipped our area for two weeks even though we "
                "registered with the helpline.",
            ),
            (
                "Illegal connection reducing supply",
                "A commercial building has tapped the main line illegally, leaving our "
                "lane without water in the mornings.",
            ),
            (
                "Borewell water muddy",
                "The public borewell is pumping muddy water with a strong smell. People "
                "have stopped using it but the motor keeps running.",
            ),
            (
                "Water meter reading wrong",
                "Our water meter has not moved for a month but the bill shows heavy "
                "usage. The meter may be faulty or the line is leaking.",
            ),
        ],
        "hi": [
            (
                "पांच दिन से पानी नहीं",
                "हमारी गली में पांच दिन से नगरपालिका का पानी नहीं आया है। लोग महंगे "
                "दाम पर टैंकर खरीद रहे हैं।",
            ),
            (
                "पाइपलाइन से लगातार पानी बह रहा",
                "कोने पर मुख्य पाइप से साफ पानी लीक होकर नाले में जा रहा है।",
            ),
        ],
        "kn": [
            (
                "ಐದು ದಿನಗಳಿಂದ ನೀರು ಇಲ್ಲ",
                "ನಮ್ಮ ಬೀದಿಗೆ ಐದು ದಿನಗಳಿಂದ ಪುರಸಭೆಯ ನೀರು ಬಂದಿಲ್ಲ. ಜನರು ದುಬಾರಿ "
                "ಬೆಲೆಗೆ ಟ್ಯಾಂಕರ್ ಖರೀದಿಸುತ್ತಿದ್ದಾರೆ.",
            ),
            (
                "ಪೈಪ್ಲೈನ್ ನಿರಂತರ ಸೋರಿಕೆ",
                "ಮೂಲೆಯಲ್ಲಿ ಮುಖ್ಯ ಪೈಪ್ನಿಂದ ಶುದ್ಧ ನೀರು ಸೋರಿ ಚರಂಡಿಗೆ ಹೋಗುತ್ತಿದೆ.",
            ),
        ],
    },
    ComplaintCategory.SANITATION: {
        "en": [
            (
                "Public toilet not cleaned",
                "The community toilet near the bus stand has not been cleaned for a "
                "week. There is no water and the doors are broken.",
            ),
            (
                "Garbage burning near homes",
                "Waste is being burnt in the open behind the apartments every evening. "
                "The smoke enters our windows.",
            ),
            (
                "Rodent problem in market",
                "Rats are coming out of the drains in the market area. Vendors are "
                "worried about contamination.",
            ),
            (
                "Open defecation near park",
                "People are using the vacant plot beside the park as a toilet. It is a "
                "health risk for children.",
            ),
            (
                "Dirty drinking water tank",
                "The overhead tank in the block has not been cleaned in a year and the "
                "water now smells.",
            ),
            (
                "Mosquito breeding in stagnant water",
                "Stagnant water in the sanitation yard is breeding mosquitoes. Dengue "
                "cases are rising in the lane.",
            ),
            (
                "Hotel waste dumped in drain",
                "A restaurant is dumping food waste into the open drain every night. It "
                "is attracting rats and stray dogs.",
            ),
            (
                "No handwash point at public toilet",
                "The public toilet has no soap or handwash point. Users are leaving "
                "without washing, which is a health risk.",
            ),
        ],
        "hi": [
            (
                "सार्वजनिक शौचालय की सफाई नहीं",
                "बस स्टैंड के पास का सामुदायिक शौचालय एक हफ्ते से साफ नहीं हुआ है। "
                "पानी नहीं है और दरवाजे टूटे हैं।",
            ),
            (
                "कूड़ा जलाने से धुआं",
                "हर शाम अपार्टमेंट के पीछे कूड़ा खुले में जलाया जाता है। धुआं हमारी "
                "खिड़कियों में आता है।",
            ),
        ],
        "kn": [
            (
                "ಸಾರ್ವಜನಿಕ ಶೌಚಾಲಯ ಸ್ವಚ್ಛವಿಲ್ಲ",
                "ಬಸ್ ನಿಲ್ದಾಣದ ಬಳಿಯ ಸಮುದಾಯ ಶೌಚಾಲಯವನ್ನು ಒಂದು ವಾರದಿಂದ ಸ್ವಚ್ಛಗೊಳಿಸಿಲ್ಲ. "
                "ನೀರಿಲ್ಲ, ಬಾಗಿಲುಗಳು ಮುರಿದಿವೆ.",
            ),
            (
                "ಕಸ ಸುಡುವುದರಿಂದ ಹೊಗೆ",
                "ಪ್ರತಿ ಸಂಜೆ ಅಪಾರ್ಟ್ಮೆಂಟ್ ಹಿಂದೆ ಕಸವನ್ನು ಬಯಲಿನಲ್ಲಿ ಸುಡುತ್ತಾರೆ. ಹೊಗೆ "
                "ನಮ್ಮ ಕಿಟಕಿಗಳಿಗೆ ಬರುತ್ತದೆ.",
            ),
        ],
    },
    ComplaintCategory.WASTE_MANAGEMENT: {
        "en": [
            (
                "Garbage not collected for a week",
                "The black spot near the temple has not been cleared for eight days. "
                "Stray dogs are scattering waste on the road.",
            ),
            (
                "Overflowing community bin",
                "The bin outside the market overflows every morning and waste is blown "
                "into the storm drain.",
            ),
            (
                "Construction debris dumped on footpath",
                "Bricks and sand from a site are dumped on the footpath, forcing "
                "pedestrians onto the road.",
            ),
            (
                "Stray cattle around dump",
                "Cattle are standing in the garbage heap and blocking the lane. Children "
                "cannot walk to school.",
            ),
            (
                "Burning plastic in vacant lot",
                "Plastic waste is being burnt in the empty lot at night. The fumes are "
                "choking residents.",
            ),
            (
                "Bin missing at bus stop",
                "The bin at the bus stop was removed and people now throw waste on the "
                "road.",
            ),
            (
                "Waste piled beside school wall",
                "A large pile of waste has formed beside the school wall. It is breeding "
                "flies and blocking the drain.",
            ),
            (
                "E-waste dumped in park",
                "Old batteries and electronic waste were dumped inside the park. "
                "Children play near the pile.",
            ),
        ],
        "hi": [
            (
                "एक हफ्ते से कूड़ा नहीं उठा",
                "मंदिर के पास वाली जगह आठ दिनों से साफ नहीं हुई है। आवारा कुत्ते कूड़ा "
                "सड़क पर फैला रहे हैं।",
            ),
            (
                "कूड़ेदान ओवरफ्लो",
                "बाजार के बाहर कूड़ेदान हर सुबह भर जाता है और कचरा बरसाती नाले में उड़ "
                "जाता है।",
            ),
        ],
        "kn": [
            (
                "ಒಂದು ವಾರದಿಂದ ಕಸ ಎತ್ತಿಲ್ಲ",
                "ದೇವಸ್ಥಾನದ ಬಳಿಯ ಸ್ಥಳವನ್ನು ಎಂಟು ದಿನಗಳಿಂದ ಸ್ವಚ್ಛಗೊಳಿಸಿಲ್ಲ. ಬೀದಿ ನಾಯಿಗಳು "
                "ಕಸವನ್ನು ರಸ್ತೆಗೆ ಹರಡುತ್ತಿವೆ.",
            ),
            (
                "ಕಸದ ತೊಟ್ಟಿ ಉಕ್ಕಿ ಹರಿಯುತ್ತದೆ",
                "ಮಾರುಕಟ್ಟೆ ಹೊರಗಿನ ಕಸದ ತೊಟ್ಟಿ ಪ್ರತಿ ಬೆಳಗ್ಗೆ ತುಂಬಿ ಕಸ ಮಳೆನೀರಿನ ಚರಂಡಿಗೆ "
                "ಹಾರುತ್ತದೆ.",
            ),
        ],
    },
    ComplaintCategory.STREETLIGHT: {
        "en": [
            (
                "Street lights not working on 7th Cross",
                "All five street lights on our lane are dark. It is unsafe for women "
                "walking home after 7 pm.",
            ),
            (
                "Flickering lamp outside hospital",
                "The lamp outside the hospital gate flickers and then goes off for "
                "hours, leaving the entrance dark.",
            ),
            (
                "Pole leaning dangerously",
                "A street light pole is leaning over the road after the storm and could "
                "fall on vehicles.",
            ),
            (
                "New poles installed but not connected",
                "Poles were installed three months ago but no power connection or lamp "
                "has been fitted.",
            ),
            (
                "Lights on during the day",
                "Street lights stay on all day in our block, wasting power; they should "
                "be on only at night.",
            ),
            (
                "Dark stretch near school",
                "The stretch between the school and the bus stop has no working light "
                "and is pitch dark by 6:30 pm.",
            ),
            (
                "Street light switch box open",
                "The switch box for the street lights is open with live wires exposed. "
                "Children play right next to it.",
            ),
            (
                "Lamp post damaged by vehicle",
                "A vehicle knocked down the lamp post on the corner. The base is broken "
                "and the whole pole is unstable.",
            ),
        ],
        "hi": [
            (
                "सातवीं क्रॉस पर स्ट्रीट लाइट खराब",
                "हमारी गली की सभी पांच स्ट्रीट लाइटें बंद हैं। शाम सात बजे के बाद "
                "महिलाओं के लिए चलना असुरक्षित है।",
            ),
            (
                "अस्पताल के बाहर लाइट टिमटिमाती है",
                "अस्पताल के गेट के बाहर लाइट टिमटिमाती है और फिर घंटों बंद रहती है।",
            ),
        ],
        "kn": [
            (
                "ಏಳನೇ ಕ್ರಾಸ್ನಲ್ಲಿ ಬೀದಿ ದೀಪಗಳು ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ",
                "ನಮ್ಮ ಬೀದಿಯ ಎಲ್ಲಾ ಐದು ಬೀದಿ ದೀಪಗಳು ಆಫ್ ಆಗಿವೆ. ಸಂಜೆ ಏಳರ ನಂತರ "
                "ಮಹಿಳೆಯರಿಗೆ ನಡೆಯಲು ಸುರಕ್ಷಿತವಲ್ಲ.",
            ),
            (
                "ಆಸ್ಪತ್ರೆ ಹೊರಗೆ ದೀಪ ಮಿನುಗುತ್ತದೆ",
                "ಆಸ್ಪತ್ರೆ ಗೇಟ್ ಹೊರಗಿನ ದೀಪ ಮಿನುಗಿ ನಂತರ ಗಂಟೆಗಳ ಕಾಲ ಆಫ್ ಆಗಿರುತ್ತದೆ.",
            ),
        ],
    },
    ComplaintCategory.TRAFFIC_SIGNAL: {
        "en": [
            (
                "Signal not working at busy junction",
                "The traffic signal at the main junction has been dead since Monday. "
                "Vehicles are crossing blindly during peak hours.",
            ),
            (
                "Signal timing too short for pedestrians",
                "The pedestrian green lasts only eight seconds, so elderly people cannot "
                "cross the wide road.",
            ),
            (
                "No signal at school crossing",
                "There is no signal or zebra crossing at the school gate. Children dart "
                "across traffic every morning.",
            ),
            (
                "Signal stuck on red",
                "One direction stays red for ten minutes at a time, causing a long queue "
                "and honking.",
            ),
            (
                "Broken signal pole after accident",
                "The signal pole was hit by a lorry and is hanging over the road. The "
                "lights stopped working.",
            ),
            (
                "Illegal parking blocking junction",
                "Cars are parked right up to the stop line, so buses cannot turn and the "
                "signal is ineffective.",
            ),
            (
                "Zebra crossing faded away",
                "The zebra crossing near the market has completely faded. Drivers do not "
                "slow down and pedestrians take a risk.",
            ),
            (
                "Blinking signal at night",
                "The signal only blinks yellow after 10 pm. There have been two crashes "
                "at the junction this month.",
            ),
        ],
        "hi": [
            (
                "व्यस्त चौक पर सिग्नल खराब",
                "मुख्य चौक का ट्रैफिक सिग्नल सोमवार से बंद है। व्यस्त समय में वाहन बिना "
                "देखे निकल रहे हैं।",
            ),
            (
                "पैदल यात्रियों के लिए सिग्नल बहुत कम",
                "पैदल यात्रियों की हरी बत्ती सिर्फ आठ सेकंड रहती है, बुजुर्ग सड़क पार "
                "नहीं कर पाते।",
            ),
        ],
        "kn": [
            (
                "ಜನದಟ್ಟಣೆಯ ಜಂಕ್ಷನ್ನಲ್ಲಿ ಸಿಗ್ನಲ್ ಕೆಟ್ಟಿದೆ",
                "ಮುಖ್ಯ ಜಂಕ್ಷನ್ನ ಸಂಚಾರ ಸಿಗ್ನಲ್ ಸೋಮವಾರದಿಂದ ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ. ವಾಹನಗಳು "
                "ಕುರುಡಾಗಿ ದಾಟುತ್ತಿವೆ.",
            ),
            (
                "ಪಾದಚಾರಿಗಳಿಗೆ ಸಿಗ್ನಲ್ ಸಮಯ ಕಡಿಮೆ",
                "ಪಾದಚಾರಿ ಹಸಿರು ಬೆಳಕು ಕೇವಲ ಎಂಟು ಸೆಕೆಂಡು ಇರುತ್ತದೆ, ವೃದ್ಧರು ರಸ್ತೆ "
                "ದಾಟಲಾಗುವುದಿಲ್ಲ.",
            ),
        ],
    },
    ComplaintCategory.NOISE: {
        "en": [
            (
                "Loud music from bar late at night",
                "The bar on the corner plays loud music until 2 am. Residents with small "
                "children cannot sleep.",
            ),
            (
                "Construction noise before dawn",
                "A construction site starts drilling at 5 am every day, well before the "
                "permitted hours.",
            ),
            (
                "Honking at night near hospital",
                "Drivers honk continuously at the hospital junction at night, disturbing "
                "patients.",
            ),
            (
                "Generator noise all day",
                "A commercial generator runs all day next to our homes and the vibration "
                "is unbearable.",
            ),
            (
                "Loudspeaker beyond permitted hours",
                "A shop uses a loudspeaker for announcements until midnight, far beyond "
                "the allowed time.",
            ),
            (
                "Wedding hall noise violation",
                "The wedding hall plays music at full volume past 11 pm despite the court "
                "order on timings.",
            ),
            (
                "Industrial grinder noise at night",
                "A workshop runs an industrial grinder after midnight. The whole street "
                "can hear it and sleep is impossible.",
            ),
            (
                "Temple loudspeaker too loud",
                "The temple loudspeaker starts at 5 am at full volume. Nearby residents "
                "have complained repeatedly.",
            ),
        ],
        "hi": [
            (
                "देर रात बार में तेज संगीत",
                "कोने वाला बार रात दो बजे तक तेज संगीत बजाता है। छोटे बच्चों वाले "
                "परिवार सो नहीं पाते।",
            ),
            (
                "सुबह से पहले निर्माण का शोर",
                "निर्माण स्थल पर रोज सुबह पांच बजे ड्रिलिंग शुरू हो जाती है, अनुमत "
                "समय से पहले।",
            ),
        ],
        "kn": [
            (
                "ರಾತ್ರಿ ವೇಳೆ ಬಾರ್ನಲ್ಲಿ ಜೋರಾದ ಸಂಗೀತ",
                "ಮೂಲೆಯಲ್ಲಿರುವ ಬಾರ್ ರಾತ್ರಿ ಎರಡು ಗಂಟೆಯವರೆಗೆ ಜೋರಾದ ಸಂಗೀತ ಹಾಕುತ್ತದೆ. "
                "ಮಕ್ಕಳಿರುವ ಕುಟುಂಬಗಳಿಗೆ ನಿದ್ದೆ ಬರುತ್ತಿಲ್ಲ.",
            ),
            (
                "ಮುಂಜಾನೆ ನಿರ್ಮಾಣ ಸದ್ದು",
                "ನಿರ್ಮಾಣ ಸ್ಥಳದಲ್ಲಿ ಪ್ರತಿದಿನ ಬೆಳಗ್ಗೆ ಐದು ಗಂಟೆಗೆ ಕೊರೆಯುವ ಕೆಲಸ "
                "ಶುರುವಾಗುತ್ತದೆ.",
            ),
        ],
    },
    ComplaintCategory.PARKS_TREES: {
        "en": [
            (
                "Fallen tree blocking road",
                "A large tree fell during the storm and is blocking the entire lane. "
                "Branches are resting on power lines.",
            ),
            (
                "Dead tree likely to fall",
                "A dead tree near the playground is leaning badly. It could fall on "
                "children during the next rain.",
            ),
            (
                "Park benches and swings broken",
                "The swings and benches in the ward park are broken and rusted. Children "
                "have nowhere safe to play.",
            ),
            (
                "Overgrown weeds in park",
                "The park has not been maintained for months; weeds are waist high and "
                "snakes have been seen.",
            ),
            (
                "Tree roots damaging footpath",
                "Roots have lifted the footpath slabs, creating a trip hazard for elderly "
                "walkers.",
            ),
            (
                "Park lights and gate broken",
                "The park gate and lights are broken, so the space is used for anti-social "
                "activity after dark.",
            ),
            (
                "Tree branch hanging over road",
                "A heavy branch is hanging low over the road after the storm. Buses are "
                "scraping it and it may fall.",
            ),
            (
                "Park pond full of garbage",
                "The pond inside the park is covered in plastic and stagnant water. It "
                "smells and mosquitoes are breeding.",
            ),
        ],
        "hi": [
            (
                "गिरा हुआ पेड़ सड़क रोक रहा है",
                "तूफान में बड़ा पेड़ गिर गया और पूरी गली रुक गई है। टहनियां बिजली की "
                "तारों पर टिकी हैं।",
            ),
            (
                "सूखा पेड़ गिरने की आशंका",
                "खेल के मैदान के पास सूखा पेड़ बुरी तरह झुक गया है। अगली बारिश में "
                "बच्चों पर गिर सकता है।",
            ),
        ],
        "kn": [
            (
                "ಬಿದ್ದ ಮರ ರಸ್ತೆ ತಡೆಯುತ್ತಿದೆ",
                "ಬಿರುಗಾಳಿಯಲ್ಲಿ ದೊಡ್ಡ ಮರ ಬಿದ್ದು ಇಡೀ ಬೀದಿ ತಡೆಯಾಗಿದೆ. ಕೊಂಬೆಗಳು ವಿದ್ಯುತ್ "
                "ತಂತಿಗಳ ಮೇಲೆ ಒರಗಿವೆ.",
            ),
            (
                "ಒಣ ಮರ ಬೀಳುವ ಅಪಾಯ",
                "ಆಟದ ಮೈದಾನದ ಬಳಿ ಒಣ ಮರ ಬಹಳವಾಗಿ ಓರೆಯಾಗಿದೆ. ಮುಂದಿನ ಮಳೆಯಲ್ಲಿ ಮಕ್ಕಳ ಮೇಲೆ "
                "ಬೀಳಬಹುದು.",
            ),
        ],
    },
    ComplaintCategory.OTHER: {
        "en": [
            (
                "Abandoned building unsafe",
                "An abandoned building on our street has a collapsing wall and "
                "trespassers. It needs to be secured.",
            ),
            (
                "Stray dog menace",
                "A pack of stray dogs chases schoolchildren every morning. Vaccination "
                "and sterilisation are needed.",
            ),
            (
                "Illegal hoarding blocking view",
                "A large illegal hoarding at the junction blocks the view of oncoming "
                "traffic.",
            ),
            (
                "Public borewell left open",
                "A borewell pit near the playground has no cover and is full of water. A "
                "child could fall in.",
            ),
            (
                "Encroachment on public land",
                "A shop has extended its platform onto the footpath, leaving no space for "
                "pedestrians.",
            ),
            (
                "Broken public tap wasting water",
                "A public tap has been running continuously for days and the water is "
                "flooding the lane.",
            ),
            (
                "Dangerous electric wires hanging",
                "Loose electric wires are hanging from a pole at head height. Residents "
                "are afraid to walk under them.",
            ),
            (
                "Uncovered manhole on footpath",
                "A manhole on the footpath has lost its cover. It is hidden by grass and "
                "very dangerous at night.",
            ),
        ],
        "hi": [
            (
                "खाली इमारत असुरक्षित",
                "हमारी गली की खाली इमारत की दीवार गिर रही है। इसे सुरक्षित करने की जरूरत "
                "है।",
            ),
            (
                "आवारा कुत्तों का आतंक",
                "आवारा कुत्तों का समूह रोज सुबह स्कूली बच्चों का पीछा करता है। टीकाकरण "
                "और नसबंदी जरूरी है।",
            ),
        ],
        "kn": [
            (
                "ಖಾಲಿ ಕಟ್ಟಡ ಅಸುರಕ್ಷಿತ",
                "ನಮ್ಮ ಬೀದಿಯ ಖಾಲಿ ಕಟ್ಟಡದ ಗೋಡೆ ಬೀಳುತ್ತಿದೆ. ಅದನ್ನು ಸುರಕ್ಷಿತಗೊಳಿಸಬೇಕು.",
            ),
            (
                "ಬೀದಿ ನಾಯಿಗಳ ಹಾವಳಿ",
                "ಬೀದಿ ನಾಯಿಗಳ ಗುಂಪು ಪ್ರತಿ ಬೆಳಗ್ಗೆ ಶಾಲಾ ಮಕ್ಕಳನ್ನು ಅಟ್ಟಿಸಿಕೊಂಡು "
                "ಹೋಗುತ್ತದೆ. ಲಸಿಕೆ ಮತ್ತು ಸಂತಾನಶಕ್ತಿ ಕಾರ್ಯಕ್ರಮ ಬೇಕು.",
            ),
        ],
    },
}

SEVERITY_BY_CATEGORY: dict[ComplaintCategory, list[int]] = {
    ComplaintCategory.ROADS: [2, 3, 3, 4, 4, 5],
    ComplaintCategory.DRAINAGE: [2, 3, 3, 4, 4, 5],
    ComplaintCategory.WATER_SUPPLY: [3, 3, 4, 4, 5],
    ComplaintCategory.SANITATION: [2, 3, 3, 4],
    ComplaintCategory.WASTE_MANAGEMENT: [2, 3, 3, 4],
    ComplaintCategory.STREETLIGHT: [2, 3, 3, 4],
    ComplaintCategory.TRAFFIC_SIGNAL: [3, 4, 4, 5],
    ComplaintCategory.NOISE: [2, 2, 3, 3],
    ComplaintCategory.PARKS_TREES: [2, 3, 3, 4],
    ComplaintCategory.OTHER: [2, 3, 3, 4],
}

LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "kn": "Kannada"}


# --- Data classes -------------------------------------------------------------
@dataclass(frozen=True)
class TextSample:
    """One labeled text for classifier training/evaluation."""

    sample_id: str
    category: ComplaintCategory
    language: str
    title: str
    description: str

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"


@dataclass(frozen=True)
class ComplaintSeed:
    """A generated complaint ready to insert (without ML enrichment fields)."""

    seed_id: str
    title: str
    description: str
    category: ComplaintCategory
    severity: int
    location: GeoPoint
    address: str
    landmark: str | None
    ward: int
    created_at: datetime
    status: ComplaintStatus
    votes: int
    language: str
    duplicate_group: str | None = None
    template_index: int = 0

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.description}"


@dataclass(frozen=True)
class WardSeed:
    """Ward document fields plus helper geometry."""

    ward_no: int
    name: str
    zone: str
    geometry: dict
    sensitive_locations: list[dict] = field(default_factory=list)


# --- Geography helpers --------------------------------------------------------
def _ward_geometry(lng: float, lat: float) -> dict:
    ring = [
        (lng - _CELL_HALF_LNG, lat - _CELL_HALF_LAT),
        (lng + _CELL_HALF_LNG, lat - _CELL_HALF_LAT),
        (lng + _CELL_HALF_LNG, lat + _CELL_HALF_LAT),
        (lng - _CELL_HALF_LNG, lat + _CELL_HALF_LAT),
        (lng - _CELL_HALF_LNG, lat - _CELL_HALF_LAT),
    ]
    return {"type": "Polygon", "coordinates": [[list(point) for point in ring]]}


def generate_wards() -> list[WardSeed]:
    """25 deterministic Bengaluru wards with schools/hospitals in their polygons."""
    wards: list[WardSeed] = []
    for index, (ward_no, name, zone, lng, lat) in enumerate(_GRID):
        sensitive: list[dict] = []
        for kind, offset in (("school", (0.006, 0.005)), ("hospital", (-0.007, -0.004))):
            label = _SENSITIVE_NAMES[kind][index % len(_SENSITIVE_NAMES[kind])]
            sensitive.append(
                {
                    "kind": kind,
                    "name": label,
                    "location": {
                        "type": "Point",
                        "coordinates": [round(lng + offset[0], 6), round(lat + offset[1], 6)],
                    },
                }
            )
        wards.append(
            WardSeed(
                ward_no=ward_no,
                name=name,
                zone=zone,
                geometry=_ward_geometry(lng, lat),
                sensitive_locations=sensitive,
            )
        )
    return wards


def ward_centers() -> dict[int, tuple[float, float]]:
    """Mapping of ward number to (lng, lat) seed centre."""
    return {ward_no: (lng, lat) for ward_no, _, _, lng, lat in _GRID}


def ward_profiles() -> dict[int, dict[str, float]]:
    """Per-ward volume/severity/speed multipliers used by the demo corpus."""
    return {ward_no: dict(profile) for ward_no, profile in _WARD_PROFILE.items()}


# --- Text corpus --------------------------------------------------------------
def iter_text_samples() -> Iterator[TextSample]:
    """All labeled template texts (English, Hindi and Kannada)."""
    for category, by_language in TEMPLATES.items():
        for language, items in by_language.items():
            for index, (title, description) in enumerate(items):
                yield TextSample(
                    sample_id=f"{category.value}-{language}-{index}",
                    category=category,
                    language=language,
                    title=title,
                    description=description,
                )


def split_text_samples(
    *, holdout_modulus: int = 5
) -> tuple[list[TextSample], list[TextSample]]:
    """Deterministic stratified train / held-out split.

    Every 5th template (by position inside its language list) is held out, so
    each category and language contributes to the evaluation set.
    """
    samples = list(iter_text_samples())
    train: list[TextSample] = []
    holdout: list[TextSample] = []
    for category, by_language in TEMPLATES.items():
        for language, items in by_language.items():
            for index, (title, description) in enumerate(items):
                sample = TextSample(
                    sample_id=f"{category.value}-{language}-{index}",
                    category=category,
                    language=language,
                    title=title,
                    description=description,
                )
                (holdout if index % holdout_modulus == 0 else train).append(sample)
    assert len(train) + len(holdout) == len(samples)
    return train, holdout


# --- Complaint history --------------------------------------------------------
def _seasonal(
    day: date,
    rng: random.Random,
    category: ComplaintCategory,
    *,
    burst_start: date,
    burst_end: date,
) -> float:
    """Weekly + annual shape plus a monsoon burst for water-related categories."""
    weekday = 0.85 if day.weekday() >= 5 else 1.0
    month = 1.0 + 0.12 * math.sin((day.month / 12) * 2 * math.pi)
    burst = 1.0
    if category in (
        ComplaintCategory.DRAINAGE,
        ComplaintCategory.WATER_SUPPLY,
        ComplaintCategory.ROADS,
    ) and burst_start <= day <= burst_end:
        burst = 2.4
    return weekday * month * burst * rng.uniform(0.7, 1.3)


def _address(rng: random.Random, ward_name: str, zone: str) -> tuple[str, str]:
    streets = _STREETS_BY_ZONE.get(zone) or _STREETS_BY_ZONE["South Zone"]
    number = rng.randint(1, 18)
    street = rng.choice(streets)
    landmark = rng.choice(_LANDMARKS)
    return f"{number} {street}, {ward_name}, Bengaluru", landmark


def generate_complaints(
    *,
    days: int = 180,
    end_date: date | None = None,
    seed: int = 7,
    duplicate_groups_per_series: int = 2,
) -> list[ComplaintSeed]:
    """Generate a deterministic multi-month complaint history.

    Counts follow a per-series Poisson-ish process with weekly seasonality and
    a monsoon burst, scaled by a per-ward "personality" (volume/severity/speed)
    so the dashboards show real structure instead of uniform noise.  Each
    series also gets a couple of explicit cross-language duplicate groups
    (English + Hindi + Kannada report of the same issue), which are the ground
    truth for duplicate-detection evaluation.
    """
    rng = random.Random(seed)
    end = end_date or date(2026, 10, 31)
    start = end - timedelta(days=days - 1)
    burst_start = start + timedelta(days=35)
    burst_end = start + timedelta(days=int(days * 0.55))
    centers = ward_centers()
    complaints: list[ComplaintSeed] = []
    counter = 0

    for ward_no, ward_name, zone, *_ in _GRID:
        profile = _WARD_PROFILE[ward_no]
        center_lng, center_lat = centers[ward_no]
        for category_index, category in enumerate(ComplaintCategory):
            weight = CATEGORY_BASE_WEIGHT[category]
            # Deterministic per-series variance (volume is dominated by the
            # ward profile, with a small stable per-series wobble).
            series_wobble = 0.85 + ((ward_no * 37 + category_index * 11) % 100) / 100 * 0.3
            # Use a stable per-series stream so adding a series never shifts another
            # (and so the corpus is identical across processes: `hash()` is salted).
            series_key = hashlib.sha256(f"{seed}:{ward_no}:{category.value}".encode()).hexdigest()
            series_rng = random.Random(int(series_key[:16], 16))
            base = 0.055 * weight * profile["volume"] * series_wobble

            daily: list[tuple[date, int]] = []
            for offset in range(days):
                day = start + timedelta(days=offset)
                rate = base * _seasonal(
                    day,
                    series_rng,
                    category,
                    burst_start=burst_start,
                    burst_end=burst_end,
                )
                # Deterministic Poisson sample via Knuth's algorithm.
                threshold = math.exp(-rate)
                count, product = 0, series_rng.random()
                while product > threshold and count < 6:
                    count += 1
                    product *= series_rng.random()
                daily.append((day, count))

            series_complaints: list[ComplaintSeed] = []
            for day, count in daily:
                for _ in range(count):
                    template_index = series_rng.randrange(len(TEMPLATES[category]["en"]))
                    language = series_rng.choices(
                        ["en", "hi", "kn"], weights=[0.76, 0.14, 0.10]
                    )[0]
                    items = TEMPLATES[category][language]
                    title, description = items[template_index % len(items)]
                    lng = center_lng + series_rng.uniform(-0.010, 0.010)
                    lat = center_lat + series_rng.uniform(-0.011, 0.011)
                    address, landmark = _address(series_rng, ward_name, zone)
                    created = datetime.combine(
                        day,
                        time(
                            hour=series_rng.randint(6, 20),
                            minute=series_rng.randint(0, 59),
                        ),
                        tzinfo=UTC,
                    )
                    # Ward-condition severity shift, clamped to 1..5.
                    severity_pool = SEVERITY_BY_CATEGORY[category]
                    if profile["severity"]:
                        shift_odds = abs(profile["severity"]) * 0.7
                        shift = 1 if series_rng.random() < shift_odds else 0
                        if profile["severity"] > 0:
                            severity = min(5, series_rng.choice(severity_pool) + shift)
                        else:
                            severity = max(1, series_rng.choice(severity_pool) - shift)
                    else:
                        severity = series_rng.choice(severity_pool)
                    counter += 1
                    series_complaints.append(
                        ComplaintSeed(
                            seed_id=f"c{counter:05d}",
                            title=title,
                            description=description,
                            category=category,
                            severity=severity,
                            location=GeoPoint(coordinates=(round(lng, 6), round(lat, 6))),
                            address=address,
                            landmark=landmark,
                            ward=ward_no,
                            created_at=created,
                            status=ComplaintStatus.SUBMITTED,
                            votes=max(0, int(series_rng.randint(0, 10) * profile["volume"])),
                            language=language,
                            template_index=template_index,
                        )
                    )

            # Explicit cross-language duplicates: the same issue reported in
            # English, Hindi and Kannada within 80 m and a day of each other.
            eligible = [
                item
                for item in series_complaints
                if item.template_index < 2 and item.language == "en"
            ]
            for group_index, base_complaint in enumerate(
                eligible[:duplicate_groups_per_series]
            ):
                group_id = f"w{ward_no}-{category.value}-dup{group_index}"
                base = ComplaintSeed(
                    **{
                        **base_complaint.__dict__,
                        "duplicate_group": group_id,
                    }
                )
                complaints.append(base)
                for language in ("hi", "kn"):
                    title, description = TEMPLATES[category][language][
                        base_complaint.template_index
                    ]
                    jitter_lng = base_complaint.location.coordinates[0] + rng.uniform(
                        -0.0003, 0.0003
                    )
                    jitter_lat = base_complaint.location.coordinates[1] + rng.uniform(
                        -0.0003, 0.0003
                    )
                    complaints.append(
                        ComplaintSeed(
                            seed_id=f"c{counter:05d}d{language}",
                            title=title,
                            description=description,
                            category=category,
                            severity=base_complaint.severity,
                            location=GeoPoint(
                                coordinates=(round(jitter_lng, 6), round(jitter_lat, 6))
                            ),
                            address=base_complaint.address,
                            landmark=base_complaint.landmark,
                            ward=ward_no,
                            created_at=base_complaint.created_at
                            + timedelta(hours=rng.randint(2, 20)),
                            status=base_complaint.status,
                            votes=0,
                            language=language,
                            duplicate_group=group_id,
                            template_index=base_complaint.template_index,
                        )
                    )

            # Remaining complaints (exclude the English bases already added).
            duplicate_base_ids = {
                item.seed_id for item in eligible[:duplicate_groups_per_series]
            }
            complaints.extend(
                item for item in series_complaints if item.seed_id not in duplicate_base_ids
            )
    # Statuses: older complaints are mostly closed/resolved; recent ones are open.
    final: list[ComplaintSeed] = []
    for item in complaints:
        age_days = (end - item.created_at.date()).days
        if age_days > 21:
            status = rng.choices(
                [ComplaintStatus.CLOSED, ComplaintStatus.RESOLVED, ComplaintStatus.IN_PROGRESS],
                weights=[0.82, 0.16, 0.02],
            )[0]
        elif age_days > 7:
            status = rng.choices(
                [ComplaintStatus.CLOSED, ComplaintStatus.RESOLVED, ComplaintStatus.IN_PROGRESS],
                weights=[0.38, 0.42, 0.20],
            )[0]
        else:
            status = rng.choices(
                [
                    ComplaintStatus.SUBMITTED,
                    ComplaintStatus.ASSIGNED,
                    ComplaintStatus.IN_PROGRESS,
                    ComplaintStatus.RESOLVED,
                    ComplaintStatus.CLOSED,
                ],
                weights=[0.15, 0.35, 0.30, 0.12, 0.08],
            )[0]
        final.append(
            ComplaintSeed(
                **{
                    **item.__dict__,
                    "status": status,
                }
            )
        )
    return final


# --- Resolution image pairs ---------------------------------------------------
def _render_scene(rng: random.Random, *, size: int = 96, defect: bool) -> Image.Image:
    """Synthetic street scene: textured background + optional dark defect."""
    base = rng.randint(105, 150)
    img = Image.new("RGB", (size, size), (base, base, base))
    draw = ImageDraw.Draw(img)
    # Road texture: horizontal bands + speckle.
    for y in range(0, size, 6):
        shade = base + rng.randint(-18, 18)
        draw.rectangle([0, y, size, y + 5], fill=(shade, shade, shade))
    for _ in range(220):
        x, y = rng.randrange(size), rng.randrange(size)
        shade = base + rng.randint(-35, 35)
        draw.point((x, y), fill=(shade, shade, shade))
    # Lane marking.
    draw.rectangle([size // 2 - 2, 0, size // 2 + 2, size], fill=(210, 205, 170))
    if defect:
        cx = rng.randint(size // 4, 3 * size // 4)
        cy = rng.randint(size // 3, 3 * size // 3)
        rx = rng.randint(6, 13)
        ry = rng.randint(5, 10)
        draw.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=(45, 42, 38))
        draw.ellipse(
            [cx - rx + 3, cy - ry + 2, cx + rx - 3, cy + ry - 2], fill=(24, 22, 20)
        )
    return img


def generate_resolution_pairs(
    *, count: int = 120, seed: int = 21
) -> list[tuple[bytes, bytes, int, str]]:
    """Labeled synthetic before/after pairs: ``(before, after, label, pair_id)``.

    Positives: the same scene with the defect patched (label 1).
    Negatives: the after-photo is a different scene entirely (label 0).
    """
    import io

    rng = random.Random(seed)
    pairs: list[tuple[bytes, bytes, int, str]] = []
    for index in range(count):
        label = 1 if index % 2 == 0 else 0
        before = _render_scene(rng, defect=True)
        if label == 1:
            after = _render_scene(rng, defect=False)  # new noise, same style
            # Preserve the defect position but patch it with road texture.
            after = before.copy()
            draw = ImageDraw.Draw(after)
            cx = rng.randint(30, 66)
            cy = rng.randint(32, 66)
            draw.ellipse([cx - 13, cy - 10, cx + 13, cy + 10], fill=(128, 126, 120))
        else:
            after = _render_scene(rng, defect=rng.random() < 0.3)
            after = after.transpose(Image.Transpose.FLIP_LEFT_RIGHT)

        buf_before, buf_after = io.BytesIO(), io.BytesIO()
        before.save(buf_before, format="PNG")
        after.save(buf_after, format="PNG")
        pairs.append((buf_before.getvalue(), buf_after.getvalue(), label, f"pair-{index:04d}"))
    return pairs


def directory_fingerprint() -> str:
    """Stable identifier for this corpus version (used in artifacts/README)."""
    payload = "|".join(sample.sample_id for sample in iter_text_samples())
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
