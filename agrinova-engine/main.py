from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import requests
import csv
import os

app = FastAPI(title="Agrivoltaics Decision Engine API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Location(BaseModel):
    latitude: float
    longitude: float

class SiteInput(BaseModel):
    project_id: str
    location: Location
    land_area_acres: float
    current_crop: str
    state: str
    max_investment_inr: float
    daily_electricity_req_kwh: float
    irrigation_available: bool
    preferred_operation: str

CROP_DATABASE = {
    "paddy": {"type": "Full Sun", "max_panel_coverage": 0.3},
    "wheat": {"type": "Full Sun", "max_panel_coverage": 0.3},
    "maize": {"type": "Full Sun", "max_panel_coverage": 0.3},
    "turmeric": {"type": "Shade Tolerant", "max_panel_coverage": 0.6},
    "ginger": {"type": "Shade Tolerant", "max_panel_coverage": 0.6},
    "tomato": {"type": "Partial Shade", "max_panel_coverage": 0.45},
    "potato": {"type": "Partial Shade", "max_panel_coverage": 0.45},
}

DISCOM_DATABASE = {
    "assam": {"discom": "APDCL", "rate_inr_per_kwh": 3.75, "policy": "Net Metering"},
    "gujarat": {"discom": "DGVCL / UGVCL", "rate_inr_per_kwh": 2.25, "policy": "Surya Gujarat Tariff"},
    "maharashtra": {"discom": "MSEDCL", "rate_inr_per_kwh": 3.20, "policy": "Net Metering"},
    "rajasthan": {"discom": "JVVNL / AVVNL", "rate_inr_per_kwh": 2.65, "policy": "Gross/Net Hybrid"},
    "uttar pradesh": {"discom": "UPPCL", "rate_inr_per_kwh": 3.30, "policy": "Net Metering"},
}

DB_FILE = "agrinova_assessments_db.csv"

@app.get("/")
def health_check():
    return {"status": "Decision Engine is running"}

@app.post("/api/assess-site")
def assess_site(data: SiteInput):
    lat = data.location.latitude
    lon = data.location.longitude
    crop_name = data.current_crop.strip().lower()
    state_name = data.state.strip().lower()
    
    # Layer 3: Crop Intelligence
    if crop_name in CROP_DATABASE:
        crop_profile = CROP_DATABASE[crop_name]
        coverage_factor = crop_profile["max_panel_coverage"]
        crop_type = crop_profile["type"]
    else:
        coverage_factor = 0.4 
        crop_type = "Unknown/General"

    # State DISCOM Tariff lookup
    if state_name in DISCOM_DATABASE:
        discom_info = DISCOM_DATABASE[state_name]
        tariff_rate = discom_info["rate_inr_per_kwh"]
        discom_name = discom_info["discom"]
        policy_type = discom_info["policy"]
    else:
        tariff_rate = 3.00
        discom_name = "Local State DISCOM"
        policy_type = "Standard Tariff"

    # Layer 1 & 2: NASA API
    nasa_url = f"https://power.larc.nasa.gov/api/temporal/climatology/point?parameters=ALLSKY_SFC_SW_DWN&community=RE&longitude={lon}&latitude={lat}&format=JSON"
    try:
        response = requests.get(nasa_url, timeout=10)
        response.raise_for_status()
        nasa_data = response.json()
        solar_irradiance = nasa_data["properties"]["parameter"]["ALLSKY_SFC_SW_DWN"]["ANN"]
        data_source = "NASA POWER API (Real-Time)"
    except Exception as e:
        solar_irradiance = 4.5
        data_source = "Fallback Simulated"

    # Layer 4: Optimization Engine
    COST_PER_KWP = 60000 
    SQM_PER_KWP = 10      
    ACRE_TO_SQM = 4046

    max_physical_kwp = (data.land_area_acres * ACRE_TO_SQM * coverage_factor) / SQM_PER_KWP
    max_financial_kwp = data.max_investment_inr / COST_PER_KWP
    recommended_pv_kwp = round(min(max_physical_kwp, max_financial_kwp), 2)

    final_capex = round(recommended_pv_kwp * COST_PER_KWP, 2)
    land_used_sqm = round(recommended_pv_kwp * SQM_PER_KWP, 2)
    land_used_acres = round(land_used_sqm / ACRE_TO_SQM, 2)
    
    daily_generation_kwh = round(recommended_pv_kwp * solar_irradiance * 0.75, 2)
    yearly_generation_kwh = daily_generation_kwh * 365
    
    yearly_savings_inr = round(yearly_generation_kwh * tariff_rate, 2)
    payback_years = round(final_capex / yearly_savings_inr, 1) if yearly_savings_inr > 0 else 0

    if final_capex < max_physical_kwp * COST_PER_KWP:
        status = f"Optimized for Budget: Downscaled to fit INR {data.max_investment_inr/100000}L limit."
    else:
        status = f"Optimized for Crop ({crop_type}): Maximum {int(coverage_factor*100)}% land coverage achieved."

    # --- NEW: DYNAMIC CHALLENGES & RISKS GENERATOR ---
    challenges_list = []
    
    # Challenge 1: Grid Reliability
    if data.preferred_operation == "Grid-connected":
        challenges_list.append("Grid Downtime Risk: Rural feeder lines experience frequent power cuts; on-grid systems will shut down during outages unless a hybrid battery backup is integrated.")
    
    # Challenge 2: Crop Sunlight Sensitivity
    if crop_type == "Full Sun":
        challenges_list.append("Crop Yield Sensitivity: Crops like " + data.current_crop.capitalize() + " require high sunlight. Exceeding recommended panel density can reduce grain filling or crop weight.")
    
    # Challenge 3: Tariff / Policy Risk
    if tariff_rate < 3.00:
        challenges_list.append("Low Feed-in Tariff Risk: Current DISCOM policy rate (₹" + str(tariff_rate) + "/unit) in " + data.state.capitalize() + " is relatively low, which may extend the financial payback period.")
    else:
        challenges_list.append("Net Metering Compliance: Approval from " + discom_name + " for bidirectional meter clearance can take 4-6 weeks during bureaucratic processing.")

    # CSV Logging
    file_exists = os.path.isfile(DB_FILE)
    with open(DB_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        if not file_exists:
            writer.writerow(["Project_ID", "State", "DISCOM", "Crop", "Recommended_kWp", "Capex_INR", "Payback_Years"])
        writer.writerow([data.project_id, data.state, discom_name, crop_name, recommended_pv_kwp, final_capex, payback_years])

    return {
        "project_id": data.project_id,
        "layer_3_crop_intelligence": {
            "detected_crop": crop_name.capitalize(),
            "crop_type": crop_type,
            "allowed_panel_coverage": f"{int(coverage_factor * 100)}%"
        },
        "layer_1_environmental": {
            "source": data_source,
            "annual_avg_irradiance_kwh_m2_day": solar_irradiance
        },
        "discom_policy_data": {
            "state": data.state.capitalize(),
            "discom_name": discom_name,
            "feed_in_tariff_inr_per_kwh": tariff_rate,
            "policy_type": policy_type
        },
        "layer_4_optimization_engine": {
            "decision_status": status,
            "recommended_capacity_kwp": recommended_pv_kwp,
            "required_capex_inr": final_capex,
            "land_utilized_acres": land_used_acres,
            "remaining_pure_agri_acres": round(data.land_area_acres - land_used_acres, 2)
        },
        "layer_5_financials": {
            "expected_daily_generation_kwh": daily_generation_kwh,
            "estimated_yearly_savings_inr": yearly_savings_inr,
            "estimated_payback_period_years": payback_years
        },
        "implementation_challenges": challenges_list  # Sending risks to frontend
    }