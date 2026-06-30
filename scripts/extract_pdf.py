"""
One-shot extraction of Series 76 actuator data from PDF using Gemini Flash via OpenRouter.
Produces data/actuators.json validated against the Pydantic schema.

Run from konecto-assessment/ directory:
    OPENROUTER_API_KEY=<key> python scripts/extract_pdf.py [path/to/series_76_tables.pdf]
"""
import json
import os
import pathlib
import sys
import base64
from openai import OpenAI

OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Paths relative to konecto-assessment/ package root
_SCRIPT_DIR = pathlib.Path(__file__).parent          # konecto-assessment/scripts/
_PKG_ROOT = _SCRIPT_DIR.parent                       # konecto-assessment/

# Raw source PDF ships in data/raw/ so extraction is reproducible from a fresh clone.
DEFAULT_PDF_PATH = _PKG_ROOT / "data" / "raw" / "series_76_tables.pdf"
OUT_PATH = _PKG_ROOT / "data" / "actuators.json"

PROMPT = """
You are a precise data extraction assistant. Extract ALL actuator records from this PDF into a JSON array.

The PDF contains electrical data tables for Series 76 Electric Actuators organized by:
- Enclosure type: "weatherproof" or "explosionproof"
- Voltage: "110V", "220V", "24V", "3-phase"
- Application type: "on/off", "modulating", or "on/off and modulating"

For EACH row in EVERY table, extract one JSON object with these exact fields:
{
  "base_part_number": string (e.g. "761A00-11300000/A"),
  "enclosure_type": string ("weatherproof" or "explosionproof"),
  "voltage": string ("110V", "220V", "24V", "3-phase"),
  "phase": string ("single", "three", "dc", "ac/dc"),
  "application_type": string ("on/off", "modulating", "on/off and modulating"),
  "torque_inlbs": number (In-Lbs column),
  "torque_nm": number (Nm column),
  "duty_cycle": number (S4% column, numeric only),
  "cycles_per_hour": number (Cycles Per Hour column),
  "starts_per_hour": number (Starts Per Hour or Starts column),
  "motor_power_watts": number (Motor Power Watts column),
  "csa_certified": boolean (true unless row is marked with * as NOT CSA certified),
  "speed_60hz": number or null,
  "speed_50hz": number or null,
  "fla_60hz": number or null,
  "fla_50hz": number or null,
  "lra_60hz": number or null,
  "lra_50hz": number or null
}

CRITICAL RULES:
1. Extract EVERY row from EVERY table — weatherproof AND explosionproof, all voltages.
2. Weatherproof tables have both On/Off and Modulating torque columns for the same part number.
   Create TWO separate records per row: one with application_type="on/off" (using On/Off torque),
   and one with application_type="modulating" (using Modulating torque).
   They share the same base_part_number but differ in application_type and torque values.
3. Rows marked with * are NOT CSA certified — set csa_certified=false.
4. 24V AC/DC on/off table: phase="ac/dc". 24V DC modulating table: phase="dc".
   3-phase table: phase="three". Single phase tables: phase="single".
5. For 3-phase rows where electrical data shows "N/A", still include the row but set all
   speed/fla/lra fields to null.
6. Motor Power is a merged cell shared across multiple rows — apply the same wattage to all
   rows in that group (e.g. 15W applies to 761A and 761B rows).
7. Return ONLY the raw JSON array. No markdown fences, no explanation, nothing else.
"""

def main():
    if not OPENROUTER_API_KEY:
        sys.exit("Error: OPENROUTER_API_KEY env var is required. Export it before running.")

    pdf_path = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PDF_PATH

    client = OpenAI(
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
    )

    print(f"Reading PDF: {pdf_path}")
    pdf_bytes = pdf_path.read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    print("Sending to Gemini Flash via OpenRouter...")
    response = client.chat.completions.create(
        model="google/gemini-2.5-flash",
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "file",
                        "file": {
                            "filename": "series_76_tables.pdf",
                            "file_data": f"data:application/pdf;base64,{pdf_b64}",
                        },
                    },
                    {
                        "type": "text",
                        "text": PROMPT,
                    },
                ],
            }
        ],
    )

    raw = response.choices[0].message.content.strip()

    # Strip markdown code fences if present
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    print("Parsing JSON response...")
    data = json.loads(raw)
    print(f"Extracted {len(data)} records")

    # Post-process: fix known extraction issues
    # 1. 3-phase N/A rows: torque/duty_cycle/cycles/starts/motor_power are N/A in PDF
    #    These rows are valid actuators — drop them (they have no usable electrical data)
    NA_3PHASE = {"761A00-11330C00/A", "761B00-11330C00/A", "762A00-11330C00/A", "762B00-11330C00/A"}
    data = [d for d in data if d.get("base_part_number") not in NA_3PHASE]
    print(f"After removing N/A 3-phase rows: {len(data)} records")

    # 2. Explosionproof 24V: motor_power is 40W for all models (merged cell in PDF)
    EXPLO_24V_MOTOR_W = 40.0
    for d in data:
        if d.get("enclosure_type") == "explosionproof" and d.get("voltage") == "24V":
            if d.get("motor_power_watts") is None:
                d["motor_power_watts"] = EXPLO_24V_MOTOR_W

    # Validate against Pydantic schema
    sys.path.insert(0, str(_PKG_ROOT))
    from app.db.schema import Actuator

    errors = []
    for i, record in enumerate(data):
        try:
            Actuator.model_validate(record)
        except Exception as e:
            errors.append((i, record.get("base_part_number", "?"), str(e)))

    if errors:
        print(f"\nValidation ERRORS ({len(errors)}):")
        for i, pn, e in errors[:10]:
            print(f"  [{i}] {pn}: {e}")
        sys.exit(1)

    print(f"Pydantic validation: OK — all {len(data)} records valid")

    OUT_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Written to {OUT_PATH}")

    from collections import Counter
    enc = Counter(d["enclosure_type"] for d in data)
    volt = Counter(d["voltage"] for d in data)
    app = Counter(d["application_type"] for d in data)
    print(f"\nSummary:")
    print(f"  Enclosure:   {dict(enc)}")
    print(f"  Voltage:     {dict(volt)}")
    print(f"  Application: {dict(app)}")

if __name__ == "__main__":
    main()
