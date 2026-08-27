"""
GS1 company-prefix -> country/region lookup.

Ranges are (start, end, country) on the first 3 digits of an EAN-13 barcode.
Source: GS1 GS1 General Specifications public prefix registry (gs1.org).
This is not exhaustive of every sub-range GS1 has ever issued, but covers the
practical set needed to route lookups correctly for a global product base.
"""

GS1_PREFIX_RANGES = [
    (0, 139, "United States / Canada"),
    (300, 379, "France"),
    (400, 440, "Germany"),
    (450, 459, "Japan"),
    (460, 469, "Russia"),
    (471, 471, "Taiwan"),
    (474, 474, "Estonia"),
    (480, 480, "Philippines"),
    (482, 482, "Uzbekistan"),
    (484, 484, "Moldova"),
    (485, 485, "Armenia"),
    (486, 486, "Georgia"),
    (487, 487, "Kazakhstan"),
    (489, 489, "Hong Kong"),
    (490, 499, "Japan"),
    (500, 509, "United Kingdom"),
    (520, 521, "Greece"),
    (528, 528, "Lebanon"),
    (529, 529, "Cyprus"),
    (531, 531, "North Macedonia"),
    (535, 535, "Malta"),
    (539, 539, "Ireland"),
    (540, 549, "Belgium / Luxembourg"),
    (560, 560, "Portugal"),
    (569, 569, "Iceland"),
    (570, 579, "Denmark"),
    (590, 590, "Poland"),
    (594, 594, "Romania"),
    (599, 599, "Hungary"),
    (600, 601, "South Africa"),
    (603, 603, "Ghana"),
    (608, 608, "Bahrain"),
    (609, 609, "Mauritius"),
    (611, 611, "Morocco"),
    (613, 613, "Algeria"),
    (616, 616, "Kenya"),
    (618, 618, "Ivory Coast"),
    (619, 619, "Tunisia"),
    (621, 621, "Syria"),
    (622, 622, "Egypt"),
    (624, 624, "Libya"),
    (625, 625, "Jordan"),
    (626, 626, "Iran"),
    (627, 627, "Kuwait"),
    (628, 628, "Saudi Arabia"),
    (629, 629, "United Arab Emirates"),
    (640, 649, "Finland"),
    (690, 699, "China"),
    (700, 709, "Norway"),
    (729, 729, "Israel"),
    (730, 739, "Sweden"),
    (740, 740, "Guatemala"),
    (741, 741, "El Salvador"),
    (742, 742, "Honduras"),
    (743, 743, "Nicaragua"),
    (744, 744, "Costa Rica"),
    (745, 745, "Panama"),
    (746, 746, "Dominican Republic"),
    (750, 750, "Mexico"),
    (754, 755, "Canada"),
    (759, 759, "Venezuela"),
    (760, 769, "Switzerland / Liechtenstein"),
    (770, 771, "Colombia"),
    (773, 773, "Uruguay"),
    (775, 775, "Peru"),
    (777, 777, "Bolivia"),
    (778, 779, "Argentina"),
    (780, 780, "Chile"),
    (784, 784, "Paraguay"),
    (786, 786, "Ecuador"),
    (789, 790, "Brazil"),
    (800, 839, "Italy"),
    (840, 849, "Spain"),
    (850, 850, "Cuba"),
    (858, 858, "Slovakia"),
    (859, 859, "Czech Republic"),
    (860, 860, "Serbia"),
    (865, 865, "Mongolia"),
    (867, 867, "North Korea"),
    (868, 869, "Turkey"),
    (870, 879, "Netherlands"),
    (880, 880, "South Korea"),
    (883, 883, "Myanmar"),
    (884, 884, "Cambodia"),
    (885, 885, "Thailand"),
    (888, 888, "Singapore"),
    (890, 890, "India"),
    (893, 893, "Vietnam"),
    (896, 896, "Pakistan"),
    (899, 899, "Indonesia"),
    (900, 919, "Austria"),
    (930, 939, "Australia"),
    (940, 949, "New Zealand"),
    (955, 955, "Malaysia"),
    (958, 958, "Macau"),
]


def country_for_prefix(barcode_digits: str) -> str | None:
    """
    barcode_digits: normalized 13-digit (or 8/12/14 -> already normalized to 13)
    numeric string. Returns the country name or None if no range matches.
    """
    if not barcode_digits or not barcode_digits.isdigit() or len(barcode_digits) < 3:
        return None
    prefix = int(barcode_digits[:3])
    for start, end, country in GS1_PREFIX_RANGES:
        if start <= prefix <= end:
            return country
    return None
