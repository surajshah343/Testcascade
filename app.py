import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Global Fleet Cascading Auditor", layout="wide")

def run_optimized_cascade(df_fleet, df_contracts):
    # 1. Setup
    df_fleet.columns = df_fleet.columns.str.strip()
    df_contracts.columns = df_contracts.columns.str.strip()
    
    start_year = 2024
    max_end_year = int(df_contracts['End Year'].max())
    
    # Global Max Age across all locations to know when a bus is truly "Dead"
    global_max_ages = {
        'A': df_contracts['Max age type A'].max(),
        'C': df_contracts['Max age type C'].max(),
        'VAN': df_contracts['Max age type VAN'].max()
    }
    
    current_fleet = df_fleet.copy()
    current_fleet['Current Age'] = pd.to_numeric(current_fleet['Current Age'], errors='coerce').fillna(0)
    
    vin_audit_trail = []

    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        for t in ['A', 'C', 'VAN']:
            # --- Phase 1: Identify Needs and Potential Movers ---
            needs = []
            surplus_pool = [] # Units that are either extra OR over-age for their current home
            
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                is_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = int(c_row[req_col]) if is_active else 0
                max_age_loc = c_row[f'Max age type {t}']
                
                # Current units at this specific location
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                
                # Identify units that MUST leave this location (too old for HERE)
                too_old_here = loc_units[loc_units['Current Age'] > max_age_loc]
                fit_here = loc_units[loc_units['Current Age'] <= max_age_loc]
                
                # Anyone too old for this location goes to surplus pool immediately
                for _, row in too_old_here.iterrows():
                    surplus_pool.append({'vin': row['VIN'], 'age': row['Current Age'], 'orig_loc': loc})
                
                # If we have more 'fit' units than needed, move extra young ones to surplus
                if len(fit_here) > target_qty:
                    extras = fit_here.sort_values('Current Age', ascending=True).head(len(fit_here) - target_qty)
                    for _, row in extras.iterrows():
                        surplus_pool.append({'vin': row['VIN'], 'age': row['Current Age'], 'orig_loc': loc})
                
                # If we have fewer 'fit' units than needed, we have a deficit
                if len(fit_here) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(fit_here), 'max_age': max_age_loc})

            # --- Phase 2: Execute Moves (The Cascade) ---
            for need in needs:
                loc_to = need['loc']
                age_limit_to = need['max_age']
                
                for _ in range(need['needed']):
                    # Check if anyone in surplus pool fits the age requirement of this new location
                    eligible_surplus = [u for u in surplus_pool if u['age'] <= age_limit_to]
                    
                    if eligible_surplus:
                        # Pick the best unit (youngest available that fits)
                        chosen = min(eligible_surplus, key=lambda x: x['age'])
                        surplus_pool.remove(chosen)
                        
                        current_fleet.loc[current_fleet['VIN'] == chosen['vin'], 'Location'] = loc_to
                        vin_audit_trail.append({
                            "Year": year, "VIN": chosen['vin'], "Type": t,
                            "Action": "CASCADED", "From": chosen['orig_loc'], "To": loc_to, 
                            "Reason": f"Utilized surplus (Age {chosen['age']} fits limit {age_limit_to})"
                        })
                    else:
                        # No one fits? New Lease.
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(1000,9999)}"
                        new_row = pd.DataFrame([{
                            'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc_to
                        }])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        vin_audit_trail.append({
                            "Year": year, "VIN": new_vin, "Type": t,
                            "Action": "NEW LEASE", "From": "FACTORY", "To": loc_to, "Reason": "No eligible surplus"
                        })

            # --- Phase 3: Final Retirement ---
            # Any units left in surplus pool that weren't picked up and are over their global max age
            for s in surplus_pool:
                if s['age'] > global_max_ages[t]:
                    current_fleet = current_fleet[current_fleet['VIN'] != s['vin']]
                    vin_audit_trail.append({
                        "Year": year, "VIN": s['vin'], "Type": t,
                        "Action": "RETIRED", "From": s['orig_loc'], "To": "SCRAP", "Reason": "Exceeded all contract limits"
                    })

    return pd.DataFrame(vin_audit_trail)

# Streamlit UI (Standard Load)
st.title("🚌 Intelligent Fleet Cascading System")
uploaded_file = st.file_uploader("Upload Excel", type=["xlsx"])

if uploaded_file:
    df_c = pd.read_excel(uploaded_file, sheet_name="Contracts")
    df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File")
    
    if st.button("Run Optimized Audit"):
        audit_trail = run_optimized_cascade(df_f, df_c)
        st.write("### VIN Movement Audit")
        st.dataframe(audit_trail, use_container_width=True)
