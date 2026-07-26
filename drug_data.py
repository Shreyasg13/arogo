"""
drug_data.py — a small, curated list of common medications for name
autocomplete when adding a medicine.

Scope is deliberately narrow and SAFE: each entry is just a real medication
name plus a short identifier hint (the generic, for a brand; or a plain-language
use, for a generic). There is NO dosing guidance and NO drug-interaction data
here — the free NIH interaction API was retired in 2024, and shipping an
unvetted interaction dataset would be worse than shipping none. This module
only helps the user type the right name faster.

Served via GET /api/medicines/drugs?q=… exactly like food_data.py's search.
"""

# {name, hint}. `hint` identifies the drug (generic name for a brand, or a
# plain use for a generic) — an aid to recognition, never a clinical claim.
DRUGS = [
    # ── Pain / fever ──
    {"name": "Paracetamol", "hint": "Pain / fever"},
    {"name": "Acetaminophen", "hint": "Pain / fever"},
    {"name": "Ibuprofen", "hint": "Pain / anti-inflammatory"},
    {"name": "Aspirin", "hint": "Pain / blood thinner"},
    {"name": "Diclofenac", "hint": "Pain / anti-inflammatory"},
    {"name": "Aceclofenac", "hint": "Pain / anti-inflammatory"},
    {"name": "Naproxen", "hint": "Pain / anti-inflammatory"},
    {"name": "Mefenamic acid", "hint": "Pain / cramps"},
    {"name": "Tramadol", "hint": "Pain"},
    {"name": "Dolo 650", "hint": "Paracetamol"},
    {"name": "Crocin", "hint": "Paracetamol"},
    {"name": "Calpol", "hint": "Paracetamol"},
    {"name": "Combiflam", "hint": "Ibuprofen + Paracetamol"},
    {"name": "Brufen", "hint": "Ibuprofen"},
    {"name": "Zerodol", "hint": "Aceclofenac"},
    {"name": "Disprin", "hint": "Aspirin"},
    {"name": "Volini", "hint": "Pain relief gel"},

    # ── Antibiotics ──
    {"name": "Amoxicillin", "hint": "Antibiotic"},
    {"name": "Amoxicillin + Clavulanate", "hint": "Antibiotic"},
    {"name": "Azithromycin", "hint": "Antibiotic"},
    {"name": "Ciprofloxacin", "hint": "Antibiotic"},
    {"name": "Levofloxacin", "hint": "Antibiotic"},
    {"name": "Ofloxacin", "hint": "Antibiotic"},
    {"name": "Doxycycline", "hint": "Antibiotic"},
    {"name": "Cefixime", "hint": "Antibiotic"},
    {"name": "Cephalexin", "hint": "Antibiotic"},
    {"name": "Metronidazole", "hint": "Antibiotic"},
    {"name": "Clarithromycin", "hint": "Antibiotic"},
    {"name": "Augmentin", "hint": "Amoxicillin + Clavulanate"},
    {"name": "Azithral", "hint": "Azithromycin"},
    {"name": "Azee", "hint": "Azithromycin"},
    {"name": "Ciplox", "hint": "Ciprofloxacin"},
    {"name": "Monocef", "hint": "Ceftriaxone"},

    # ── Acidity / stomach ──
    {"name": "Omeprazole", "hint": "Acidity"},
    {"name": "Pantoprazole", "hint": "Acidity"},
    {"name": "Esomeprazole", "hint": "Acidity"},
    {"name": "Rabeprazole", "hint": "Acidity"},
    {"name": "Ranitidine", "hint": "Acidity"},
    {"name": "Famotidine", "hint": "Acidity"},
    {"name": "Domperidone", "hint": "Nausea"},
    {"name": "Ondansetron", "hint": "Nausea"},
    {"name": "Pan 40", "hint": "Pantoprazole"},
    {"name": "Pantop", "hint": "Pantoprazole"},
    {"name": "Pan-D", "hint": "Pantoprazole + Domperidone"},
    {"name": "Omez", "hint": "Omeprazole"},
    {"name": "Digene", "hint": "Antacid"},
    {"name": "Gelusil", "hint": "Antacid"},
    {"name": "Eno", "hint": "Antacid"},

    # ── Blood pressure / heart ──
    {"name": "Amlodipine", "hint": "Blood pressure"},
    {"name": "Telmisartan", "hint": "Blood pressure"},
    {"name": "Losartan", "hint": "Blood pressure"},
    {"name": "Olmesartan", "hint": "Blood pressure"},
    {"name": "Ramipril", "hint": "Blood pressure"},
    {"name": "Enalapril", "hint": "Blood pressure"},
    {"name": "Metoprolol", "hint": "Blood pressure / heart"},
    {"name": "Atenolol", "hint": "Blood pressure / heart"},
    {"name": "Bisoprolol", "hint": "Blood pressure / heart"},
    {"name": "Hydrochlorothiazide", "hint": "Water pill"},
    {"name": "Furosemide", "hint": "Water pill"},
    {"name": "Clopidogrel", "hint": "Blood thinner"},
    {"name": "Atorvastatin", "hint": "Cholesterol"},
    {"name": "Rosuvastatin", "hint": "Cholesterol"},
    {"name": "Simvastatin", "hint": "Cholesterol"},
    {"name": "Telma", "hint": "Telmisartan"},
    {"name": "Amlong", "hint": "Amlodipine"},
    {"name": "Ecosprin", "hint": "Aspirin"},
    {"name": "Ecosprin AV", "hint": "Aspirin + Atorvastatin"},
    {"name": "Storvas", "hint": "Atorvastatin"},
    {"name": "Rosuvas", "hint": "Rosuvastatin"},

    # ── Diabetes ──
    {"name": "Metformin", "hint": "Diabetes"},
    {"name": "Glimepiride", "hint": "Diabetes"},
    {"name": "Gliclazide", "hint": "Diabetes"},
    {"name": "Sitagliptin", "hint": "Diabetes"},
    {"name": "Vildagliptin", "hint": "Diabetes"},
    {"name": "Teneligliptin", "hint": "Diabetes"},
    {"name": "Empagliflozin", "hint": "Diabetes"},
    {"name": "Dapagliflozin", "hint": "Diabetes"},
    {"name": "Insulin", "hint": "Diabetes"},
    {"name": "Glycomet", "hint": "Metformin"},
    {"name": "Janumet", "hint": "Sitagliptin + Metformin"},

    # ── Thyroid / hormones ──
    {"name": "Levothyroxine", "hint": "Thyroid"},
    {"name": "Thyronorm", "hint": "Levothyroxine"},
    {"name": "Eltroxin", "hint": "Levothyroxine"},

    # ── Allergy / cold / respiratory ──
    {"name": "Cetirizine", "hint": "Allergy"},
    {"name": "Levocetirizine", "hint": "Allergy"},
    {"name": "Fexofenadine", "hint": "Allergy"},
    {"name": "Loratadine", "hint": "Allergy"},
    {"name": "Montelukast", "hint": "Asthma / allergy"},
    {"name": "Chlorpheniramine", "hint": "Allergy / cold"},
    {"name": "Salbutamol", "hint": "Asthma inhaler"},
    {"name": "Albuterol", "hint": "Asthma inhaler"},
    {"name": "Budesonide", "hint": "Asthma inhaler"},
    {"name": "Levocetirizine + Montelukast", "hint": "Allergy"},
    {"name": "Allegra", "hint": "Fexofenadine"},
    {"name": "Montair", "hint": "Montelukast"},
    {"name": "Montair-LC", "hint": "Montelukast + Levocetirizine"},
    {"name": "Cetzine", "hint": "Cetirizine"},
    {"name": "Okacet", "hint": "Cetirizine"},
    {"name": "Cheston Cold", "hint": "Cold & allergy"},
    {"name": "Sinarest", "hint": "Cold & fever"},
    {"name": "Ascoril", "hint": "Cough"},
    {"name": "Benadryl", "hint": "Cough / allergy"},

    # ── Vitamins / supplements ──
    {"name": "Vitamin D3 (Cholecalciferol)", "hint": "Vitamin D"},
    {"name": "Vitamin B12 (Methylcobalamin)", "hint": "Vitamin B12"},
    {"name": "Vitamin C (Ascorbic acid)", "hint": "Vitamin C"},
    {"name": "Calcium + Vitamin D3", "hint": "Bone health"},
    {"name": "Ferrous sulphate", "hint": "Iron"},
    {"name": "Ferrous ascorbate", "hint": "Iron"},
    {"name": "Folic acid", "hint": "Folate"},
    {"name": "Multivitamin", "hint": "Supplement"},
    {"name": "Shelcal", "hint": "Calcium + Vitamin D3"},
    {"name": "Neurobion Forte", "hint": "B-complex"},
    {"name": "Becosules", "hint": "B-complex"},
    {"name": "Limcee", "hint": "Vitamin C"},

    # ── Mental health / neuro ──
    {"name": "Sertraline", "hint": "Antidepressant"},
    {"name": "Escitalopram", "hint": "Antidepressant"},
    {"name": "Fluoxetine", "hint": "Antidepressant"},
    {"name": "Amitriptyline", "hint": "Antidepressant / nerve pain"},
    {"name": "Alprazolam", "hint": "Anxiety"},
    {"name": "Clonazepam", "hint": "Anxiety / seizures"},
    {"name": "Gabapentin", "hint": "Nerve pain"},
    {"name": "Pregabalin", "hint": "Nerve pain"},
    {"name": "Levetiracetam", "hint": "Seizures"},

    # ── Other common ──
    {"name": "Prednisolone", "hint": "Steroid"},
    {"name": "Dexamethasone", "hint": "Steroid"},
    {"name": "Hydroxychloroquine", "hint": "Immune / arthritis"},
    {"name": "Thyroxine", "hint": "Thyroid"},
    {"name": "Warfarin", "hint": "Blood thinner"},
    {"name": "Levothyroxine sodium", "hint": "Thyroid"},
    {"name": "Ursodeoxycholic acid", "hint": "Liver"},
    {"name": "Silymarin", "hint": "Liver"},
    {"name": "Cyclobenzaprine", "hint": "Muscle relaxant"},
    {"name": "Thiocolchicoside", "hint": "Muscle relaxant"},
    {"name": "Rabeprazole + Domperidone", "hint": "Acidity"},
]


def search_drugs(query: str = "", limit: int = 8) -> list:
    """Substring match on name and hint; exact/prefix hits ranked first."""
    q = (query or "").strip().lower()
    if not q:
        return []
    starts, contains = [], []
    for d in DRUGS:
        name = d["name"].lower()
        if name.startswith(q):
            starts.append(d)
        elif q in name or q in d["hint"].lower():
            contains.append(d)
    return (starts + contains)[:max(1, min(limit, 25))]
