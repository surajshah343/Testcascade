import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="Global Fleet Cascading Auditor", layout="wide")

def run_optimized_cascade_with_health(df_fleet, df_contracts):
    # --- 1. Setup & Data Cleaning ---
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
    health_snapshots = []

    for year in range(start_year, max_end_year + 1):
        if year > start_year:
            current_fleet['Current Age'] += 1
            
        for t in ['A', 'C', 'VAN']:
            # --- Phase 2: Identify Needs and Potential Movers ---
            needs = []
            surplus_pool = [] 
            
            for loc in df_contracts['Location'].unique():
                c_row = df_contracts[df_contracts['Location'] == loc].iloc[0]
                is_active = (year <= c_row['End Year'])
                req_col = f'Vehicle Count {t}' if t != 'VAN' else 'Vehicle Count Van'
                target_qty = int(c_row[req_col]) if is_active else 0
                max_age_loc = c_row[f'Max age type {t}']
                
                loc_units = current_fleet[(current_fleet['Location'] == loc) & (current_fleet['Type'] == t)]
                
                # Split units into "Fits Here" vs "Must Leave"
                too_old_here = loc_units[loc_units['Current Age'] > max_age_loc]
                fit_here = loc_units[loc_units['Current Age'] <= max_age_loc]
                
                for _, row in too_old_here.iterrows():
                    surplus_pool.append({'vin': row['VIN'], 'age': row['Current Age'], 'orig_loc': loc})
                
                if len(fit_here) > target_qty:
                    extras = fit_here.sort_values('Current Age', ascending=True).head(len(fit_here) - target_qty)
                    for _, row in extras.iterrows():
                        surplus_pool.append({'vin': row['VIN'], 'age': row['Current Age'], 'orig_loc': loc})
                    # Temporarily drop them from current fleet so they can be re-homed
                    current_fleet = current_fleet[~current_fleet['VIN'].isin(extras['VIN'])]
                
                # Units actually too old for this location must be removed from current_fleet to be re-homed
                current_fleet = current_fleet[~current_fleet['VIN'].isin(too_old_here['VIN'])]

                if len(fit_here) < target_qty:
                    needs.append({'loc': loc, 'needed': target_qty - len(fit_here), 'max_age': max_age_loc})

            # --- Phase 3: Execute Moves (The Cascade) ---
            for need in needs:
                loc_to = need['loc']
                age_limit_to = need['max_age']
                
                for _ in range(need['needed']):
                    eligible_surplus = [u for u in surplus_pool if u['age'] <= age_limit_to]
                    
                    if eligible_surplus:
                        chosen = min(eligible_surplus, key=lambda x: x['age'])
                        surplus_pool.remove(chosen)
                        
                        # Re-add to fleet with new location
                        new_unit_data = df_fleet[df_fleet['VIN'] == chosen['vin']].copy()
                        new_unit_data['Location'] = loc_to
                        new_unit_data['Current Age'] = chosen['age']
                        current_fleet = pd.concat([current_fleet, new_unit_data])
                        
                        vin_audit_trail.append({
                            "Year": year, "VIN": chosen['vin'], "Type": t,
                            "Action": "CASCADED", "From": chosen['orig_loc'], "To": loc_to, 
                            "Reason": f"Re-homed (Age {chosen['age']} fits limit {age_limit_to})"
                        })
                    else:
                        new_vin = f"LSE-{year}-{t}-{np.random.randint(1000,9999)}"
                        new_row = pd.DataFrame([{'VIN': new_vin, 'Model Year': year, 'Current Age': 0, 'Type': t, 'Location': loc_to}])
                        current_fleet = pd.concat([current_fleet, new_row], ignore_index=True)
                        vin_audit_trail.append({"Year": year, "VIN": new_vin, "Type": t, "Action": "NEW LEASE", "From": "FACTORY", "To": loc_to, "Reason": "No eligible surplus"})

            # Any remaining in pool too old for ANYWHERE are retired
            for s in surplus_pool:
                if s['age'] > global_max_ages[t]:
                    vin_audit_trail.append({"Year": year, "VIN": s['vin'], "Type": t, "Action": "RETIRED", "From": s['orig_loc'], "To": "SCRAP", "Reason": "Exceeded all possible limits"})

        # --- Phase 4: Take Health Snapshot ---
        for loc in df_contracts['Location'].unique():
            loc_stats = current_fleet[current_fleet['Location'] == loc]
            avg_age = loc_stats['Current Age'].mean() if not loc_stats.empty else 0
            count = len(loc_stats)
            health_snapshots.append({'Year': year, 'Location': loc, 'Avg Age': round(avg_age, 1), 'Unit Count': count})

    return pd.DataFrame(vin_audit_trail), pd.DataFrame(health_snapshots)

# --- UI INTERFACE ---
st.title("🚌 Fleet Waterfall & Cascading Auditor")

uploaded_file = st.file_uploader("Upload Excel with 'Contracts' and 'Fleet File' tabs", type=["xlsx"])

if uploaded_file:
    df_c = pd.read_excel(uploaded_file, sheet_name="Contracts")
    df_f = pd.read_excel(uploaded_file, sheet_name="Fleet File")
    
    if st.button("Generate Detailed Analysis"):
        audit_trail, health_df = run_optimized_cascade_with_health(df_f, df_c)
        
        # 1. VIN Detailed Audit
        st.header("📍 Detailed VIN Movement Log")
        st.dataframe(audit_trail, use_container_width=True)

        # 2. Location Health Matrix (Age by Year and Location)
        st.header("📊 Fleet Maturity Matrix (Avg Age by Location)")
        st.write("This table shows the progression of average age at each location after cascades.")
        
        age_pivot = health_df.pivot(index='Location', columns='Year', values='Avg Age')
        st.table(age_pivot)

        # 3. Count Matrix (Units by Year and Location)
        st.header("🔢 Unit Count Matrix")
        count_pivot = health_df.pivot(index='Location', columns='Year', values='Unit Count')
        st.table(count_pivot)

        # Download
        csv = audit_trail.to_csv(index=False).encode('utf-8')
        st.download_button("Download Full Audit CSV", data=csv, file_name="fleet_audit_report.csv")
