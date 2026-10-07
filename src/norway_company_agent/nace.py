"""English NACE Rev. 2 division labels (first two digits of the Norwegian SN industry code)."""
from __future__ import annotations

DIVISIONS = {
    "01": "Crop and animal production, hunting and related services", "02": "Forestry and logging", "03": "Fishing and aquaculture",
    "05": "Mining of coal and lignite", "06": "Extraction of crude petroleum and natural gas", "07": "Mining of metal ores",
    "08": "Other mining and quarrying", "09": "Mining support services", "10": "Manufacture of food products", "11": "Manufacture of beverages",
    "12": "Manufacture of tobacco products", "13": "Manufacture of textiles", "14": "Manufacture of wearing apparel",
    "15": "Manufacture of leather products", "16": "Manufacture of wood products (except furniture)", "17": "Manufacture of paper products",
    "18": "Printing and reproduction of recorded media", "19": "Manufacture of coke and refined petroleum products",
    "20": "Manufacture of chemicals", "21": "Manufacture of pharmaceutical products", "22": "Manufacture of rubber and plastic products",
    "23": "Manufacture of other non-metallic mineral products", "24": "Manufacture of basic metals", "25": "Manufacture of fabricated metal products",
    "26": "Manufacture of computer, electronic and optical products", "27": "Manufacture of electrical equipment",
    "28": "Manufacture of machinery and equipment", "29": "Manufacture of motor vehicles and trailers", "30": "Manufacture of other transport equipment",
    "31": "Manufacture of furniture", "32": "Other manufacturing", "33": "Repair and installation of machinery and equipment",
    "35": "Electricity, gas, steam and air conditioning supply", "36": "Water collection, treatment and supply", "37": "Sewerage",
    "38": "Waste collection, treatment and disposal; materials recovery", "39": "Remediation and other waste management services",
    "41": "Construction of buildings", "42": "Civil engineering", "43": "Specialised construction activities",
    "45": "Trade and repair of motor vehicles and motorcycles", "46": "Wholesale trade", "47": "Retail trade",
    "49": "Land transport and transport via pipelines", "50": "Water transport", "51": "Air transport",
    "52": "Warehousing and support activities for transportation", "53": "Postal and courier activities", "55": "Accommodation",
    "56": "Food and beverage service activities", "58": "Publishing activities", "59": "Film, video, TV production, sound recording and music publishing",
    "60": "Programming, broadcasting and content distribution", "61": "Telecommunications", "62": "Computer programming, consultancy and related activities",
    "63": "Information and data processing services", "64": "Financial services (except insurance and pensions)",
    "65": "Insurance, reinsurance and pension funding", "66": "Activities auxiliary to financial services and insurance", "68": "Real estate activities",
    "69": "Legal and accounting activities", "70": "Head office activities; management consultancy", "71": "Architectural and engineering activities; technical testing",
    "72": "Scientific research and development", "73": "Advertising and market research", "74": "Other professional, scientific and technical activities",
    "75": "Veterinary activities", "77": "Rental and leasing activities", "78": "Employment activities", "79": "Travel agency and tour operator activities",
    "80": "Security and investigation activities", "81": "Services to buildings and landscape activities", "82": "Office administrative and business support activities",
    "84": "Public administration and defence", "85": "Education", "86": "Human health activities", "87": "Residential care activities",
    "88": "Social work activities without accommodation", "90": "Creative, arts and entertainment activities", "91": "Libraries, archives, museums and other cultural activities",
    "92": "Gambling and betting activities", "93": "Sports, amusement and recreation activities", "94": "Activities of membership organisations",
    "95": "Repair of computers and personal and household goods", "96": "Other personal service activities", "97": "Households as employers of domestic personnel",
    "98": "Households producing goods and services for own use", "99": "Extraterritorial organisations and bodies",
}


def division_label(code: str | None) -> str | None:
    digits = "".join(ch for ch in str(code or "") if ch.isdigit())
    return DIVISIONS.get(digits[:2]) if len(digits) >= 2 else None
